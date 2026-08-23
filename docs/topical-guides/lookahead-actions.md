# Implementing lookahead policies

*Executing and evaluating a rollout of a baseline policy.*

NestedSimPy can also use its inner simulations to *choose* between
actions: it executes and evaluates a **one-step lookahead** of a
**baseline policy**, which can serve as a building block for iterative
policy optimization.

At user-defined decision points, NestedSimPy can
launch multiple inner simulations per candidate action, with each inner
simulation applying one of the candidate actions (exactly once) and
then following the user-provided baseline policy. The actions are
evaluated and the best action can be executed by the outer simulation
(alternatively, the outer simulation may follow the baseline policy and
simply report on the performance of candidate actions at decision
epochs).

Implementing rollout requires three modifications to the simulation
code:

1. **Defining the decision.** The command
   `yield from env.decide(base_policy, state)` executes the baseline
   policy; in rollout mode it returns the best candidate found by the
   inner simulations. The function `base_policy()`
   returns an action for a given system state (`base_policy` is a
   Python function and `state` is a user-defined object that represents
   the system state, maintained by the user). The policy should not
   return the value `None`, which NestedSimPy reserves to stand for the
   baseline policy's own decision. Note that each `decide` call marks a
   decision epoch.
2. **Registering the actions.** `set_inner_actions(ACTIONS, metric="cost", ...)`
   declares the alternatives to the baseline policy. These are the
   values that `env.decide` returns in the inner simulations. At each decision epoch NestedSimPy creates
   copies of the outer simulation — one per action and inner
   replication — and each copy evaluates the policy that first applies
   its assigned action and thereafter follows the baseline policy. The
   parameter `metric` names the user-defined key under which the model
   records values; each inner simulation's recorded total is its score,
   and the scores determine the best action.
3. **Setting the running mode.** The parameter `outer_run_mode`
   determines whether the outer simulation acts on the best action
   (`outer_run_mode="rollout"`) or follows the baseline policy
   (`outer_run_mode="base_policy"`), in which case NestedSimPy only
   collects the evaluation of the lookahead policy at each decision
   epoch.

## An example

The example below implements rollout for a periodic-review inventory
model — a multi-period newsvendor problem with lost sales and one
period of lead time. An order placed this period is still in transit
when this period's demand arrives and is on hand for the next
period's demand, so each order is chosen one period before the demand
it can serve. For this problem no closed-form optimal policy is
known; the standard rule brings the inventory position (on hand plus
in the pipeline) up to a fixed level, and that rule is the baseline
policy here.

- Plain SimPy: [`simpy_examples/inventory_lookahead_plain.py`](https://github.com/NestedSimPy/nestedsimpy.github.io/blob/main/simpy_examples/inventory_lookahead_plain.py)
- NestedSimPy: [`simpy_examples/inventory_lookahead_nested.py`](https://github.com/NestedSimPy/nestedsimpy.github.io/blob/main/simpy_examples/inventory_lookahead_nested.py)

### No rollout

Assume that in each period the user first makes a decision about the
order quantity, and then random demand, modeled with a Poisson
distribution, is realized. The baseline policy we wish to improve is the
order-up-to rule that considers the inventory position (on hand plus
in the pipeline) and orders up to a prespecified level. For
simplicity, we assume orders arrive one period later: each period
opens with the new order decision, then the previous period's order
arrives, demand realizes, and holding and shortage costs are
incurred. The code below implements this model and runs it for eight
periods:

```{literalinclude} ../../simpy_examples/inventory_lookahead_plain.py
:language: python
:caption: simpy_examples/inventory_lookahead_plain.py
```

### Rollout

```{tip}
**Run it live:** [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/NestedSimPy/nestedsimpy.github.io/blob/main/notebooks/NestedSimPy_inventory_lookahead.ipynb)
— installs NestedSimPy and runs this example in your browser.
```

The nested file has each order chosen by lookahead instead. Every
change against the plain version is highlighted:

```{codeannotate} ../../simpy_examples/inventory_lookahead_plain.py ../../simpy_examples/inventory_lookahead_nested.py
:title: simpy_examples/inventory_lookahead_nested.py
```

The three modifications, as they appear in the code:

**1. The decision.** `base_policy` itself is unchanged; the call to it
becomes the decision line:

```python
order = yield from env.decide(base_policy, state)
```

```{tip}
`yield from` is required — on `env.decide` and on any of your own
functions on the way to a decision. A bare call raises no error and
silently makes no decisions.
```

**2. The actions and the score.** Declare the candidate order
quantities, and record the cost wherever it arises — `metric="cost"`
in the configuration sums these records into each branch's score:

```python
ACTIONS = list(range(21))  # 0..20
```

```python
env.record("cost", period_cost)
```

NestedSimPy adds the baseline policy's own decision to the comparison
automatically; the output tables show it as `base_policy`.

**3. The running mode.** The configuration block at the end of the
file:

```python
env.set_outer_stopping_condition(timeout=PERIODS + 0.5)
env.set_inner_stopping_condition(relative_time=float(INNER_HORIZON))
env.set_inner_repetitions(INNER_REPS)
env.set_rng("CRN")
env.set_outer_seed(RANDOM_SEED)
env.set_inner_actions(ACTIONS, metric="cost", outer_run_mode="rollout")
env.set_output_options(out_dir=NESTED_OUTPUT_FOLDER, gzip_trace=False)
env.nested_run()
```

### The output

Running the nested file prints the total cost (50.0 for this seed) and
writes four CSV tables to a timestamped run folder — in the Colab
notebook, `simpy_examples/inventory_lookahead/<run>/rollout/`. The
first rows of each table, from this run:

**`outer_decisions.csv`** — one row per decision epoch (`trigger` is
the epoch index). `picked_action` names the winner of the comparison,
`decision_taken` is the order quantity the outer simulation actually
placed, and `mean` is the winner's score. The two columns differ only
when the winner is the baseline: `picked_action` then reads
`base_policy` and `decision_taken` holds the quantity the rule
ordered:

| `trigger` | `time` | `picked_action` | `decision_taken` | `mean` |
|---|---|---|---|---|
| 0 | 1.0 | 4 | 4.0 | 30.125 |
| 1 | 2.0 | 10 | 10.0 | 33.1875 |
| 2 | 3.0 | `base_policy` | 0.0 | 36.6875 |
| … | | | | |

(Third row: no candidate beat the rule, and the rule ordered 0.)

**`inner_trajectories_aggregated.csv`** — every candidate's score at
every decision epoch:

| `trigger` | `time` | `action` | `mean` | `std` | `n` | `picked` |
|---|---|---|---|---|---|---|
| 0 | 1.0 | 0 | 34.6875 | 21.27 | 16 | 0 |
| 0 | 1.0 | 1 | 31.6875 | 19.87 | 16 | 0 |
| 0 | 1.0 | 2 | 30.9375 | 18.20 | 16 | 0 |
| … | | | | | | |

(`std` shown to two decimals here; the file keeps full precision.)

**`inner_trajectories.csv`** — one row per inner simulation:

| `inner_id` | `trigger` | `fork_time` | `action` | `replication` | `value` | `seed` | `end_time` | `events` | `stop_reason` |
|---|---|---|---|---|---|---|---|---|---|
| j0-a0-k0 | 0 | 1.0 | 0 | 0 | 15.0 | 3534414860 | 5.0 | 55 | time_horizon |
| j0-a0-k1 | 0 | 1.0 | 0 | 1 | 42.0 | 3083054314 | 5.0 | 55 | time_horizon |
| j0-a0-k2 | 0 | 1.0 | 0 | 2 | 17.0 | 706492495 | 5.0 | 39 | time_horizon |
| … | | | | | | | | | |

**`inner_decisions.csv`** — every decision made *inside* each inner
simulation:

| `inner_id` | `trigger` | `action` | `replication` | `t` | `decision` |
|---|---|---|---|---|---|
| j0-a0-k0 | 0 | 0 | 0 | 1.0 | 0.0 |
| j0-a0-k0 | 0 | 0 | 0 | 2.0 | 1.0 |
| j0-a0-k0 | 0 | 0 | 0 | 3.0 | 4.0 |
| … | | | | | |

{doc}`Raw data files <../api/raw-data>` lists all columns. In code,
`env.print_rollout_summary()` shows the same numbers, one line per
decision with the pick starred:

```text
rollout summary (metric 'cost', 8 triggers, 22 actions)
  trigger  0 (t=1): 0:34.7  1:31.7  2:30.9  3:30.2  4:30.1*  5:30.9  6:30.9  7:31.7  8:31.9  9:31.8  10:30.4  11:31.1  12:32.6  13:34.7  14:36.9  15:39.9  16:42.8  17:45.8  18:48.7  19:51.1  20:53.4  base_policy:34.7
  ...
```

`env.get_inner_results_by_action(metric="cost")` returns the scores as
a dict; plot and load helpers live in `nestedsimpy.reporting`.

## The configuration calls

| Call or argument | What it does |
| --- | --- |
| `set_inner_actions(ACTIONS, metric="cost", outer_run_mode="rollout")` | declare the candidates, score branches by their summed `"cost"` records, execute the best at each decision |
| `set_inner_actions(..., outer_run_mode="base_policy")` | score every decision but keep the outer run on its baseline policy |
| `set_inner_actions(..., include_baseline=False)` | evaluate only the listed actions; by default the baseline's own decision competes as one more candidate |
| `set_inner_stopping_condition(relative_time=H)` | each branch runs `H` time units past the trigger point — the lookahead window. Branches do not stop when the outer run's horizon is reached: in this example the branches of the last decision run to time 12 while the outer run ends at 8.5 |
| `set_inner_stopping_condition(relative_time=H, absolute_time=T)` | a branch stops at whichever comes first; `absolute_time=PERIODS + 0.5` would keep every branch inside the outer run's own horizon, for a problem that really ends there |
| `set_inner_repetitions(K)` | `K` branches per action; the score is their mean |
| `set_rng("CRN")` | common random numbers: the k-th replication uses the same random draws under every candidate, so candidates are compared on the same simulated futures; `"independent"` gives every branch its own draws |
| `set_inner_actions(..., minimize=False)` | pick the highest-scoring action instead — for reward metrics |

To score branches by something other than a recorded sum, register a
metric of the same name with `env.register_metric`
({doc}`API reference <../api/simpy-core>`) before the run.

```{tip}
Expect gains where the baseline has mistakes to correct: this
example's simple rule is overridden at seven of its eight decisions,
while a well-tuned rule keeps most of its picks. Each candidate's score is the
average over its inner simulations, so raising the replications makes
the comparison steadier, at the cost of more computation; a
longer lookahead window sees more of each action's consequences but
adds noise. When tuning, keep the window short and raise the
replications first.
```

## A larger example

For a larger model —
the dual-sourcing inventory model of Song, Xiao, Zhang and Zipkin
(2017), with endogenous lead times and the paper's own Dual-Index
policy as the baseline — see {doc}`Dual Sourcing with Lookahead
Expediting <../official-parity/dual-sourcing>`.
