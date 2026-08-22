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

The example below illustrates a rollout implementation in the context
of a periodic-review inventory model — a multi-period newsvendor
problem with lost sales and one period of lead time: an order placed
at the end of a period arrives at the start of the next. In each
period the sequence of events is: the previous period's order arrives,
demand realizes, holding and shortage costs are incurred, and an order
decision is made. Since each order arrives before the next demand, the
classic newsvendor result applies: ordering up to the critical-fractile
level every period is optimal — 8 units here, for Poisson demand with
mean 5, a holding cost of 1 and a shortage cost of 9. The baseline rule
below orders up to 10 instead, and the rollout's picks move the order
level back toward the optimum.

- Plain SimPy: [`simpy_examples/inventory_lookahead_plain.py`](https://github.com/NestedSimPy/nestedsimpy.github.io/blob/main/simpy_examples/inventory_lookahead_plain.py)
- NestedSimPy: [`simpy_examples/inventory_lookahead_nested.py`](https://github.com/NestedSimPy/nestedsimpy.github.io/blob/main/simpy_examples/inventory_lookahead_nested.py)

### No rollout

Assume that in each period random demand, modeled with a Poisson
distribution, is realized. The user then makes a decision about the
order quantity. The baseline policy we wish to improve is the
order-up-to rule that considers the inventory position (on hand plus
in the pipeline) and orders up to a prespecified level. For
simplicity, we assume orders arrive one period later: each period
opens with the arrival of the previous period's order, then demand
realizes, holding and shortage costs are incurred, and the period
ends with the new order decision. The code below implements this
model and runs it for eight periods:

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
ACTIONS = list(range(11))  # 0..10
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

Running the nested file prints the total cost (27.0 for this seed) and
writes four CSV tables to a timestamped run folder — here
`simpy_examples/inventory_lookahead/<run>/rollout/`. The first rows of
each table, from this run:

**`outer_decisions.csv`** — one row per decision epoch (`trigger` is
the epoch index): the picked action (`picked_action`), the order the
outer simulation actually placed (`decision_taken`), and the pick's
score (`mean`). When the pick is `base_policy` (no override),
`decision_taken` records the quantity the rule ordered, 6.0 in the
`trigger` 2 row:

| `trigger` | `time` | `picked_action` | `decision_taken` | `mean` |
|---|---|---|---|---|
| 0 | 1.0 | 0 | 0.0 | 11.75 |
| 1 | 2.0 | 7 | 7.0 | 14.25 |
| 2 | 3.0 | `base_policy` | 6.0 | 19.0 |
| … | | | | |

**`inner_trajectories_aggregated.csv`** — every candidate's score at
every decision epoch:

| `trigger` | `time` | `action` | `mean` | `std` | `n` | `picked` |
|---|---|---|---|---|---|---|
| 0 | 1.0 | 0 | 11.75 | 1.92 | 4 | 1 |
| 0 | 1.0 | 1 | 12.75 | 1.92 | 4 | 0 |
| 0 | 1.0 | 2 | 13.75 | 1.92 | 4 | 0 |
| … | | | | | | |

(`std` shown to two decimals here; the file keeps full precision.)

**`inner_trajectories.csv`** — one row per inner simulation:

| `inner_id` | `trigger` | `fork_time` | `action` | `replication` | `value` | `seed` | `end_time` | `events` | `stop_reason` |
|---|---|---|---|---|---|---|---|---|---|
| j0-a0-k0 | 0 | 1.0 | 0 | 0 | 13.0 | 2169841265 | 5.0 | 50 | time_horizon |
| j0-a0-k1 | 0 | 1.0 | 0 | 1 | 14.0 | 3982384359 | 5.0 | 50 | time_horizon |
| j0-a0-k2 | 0 | 1.0 | 0 | 2 | 11.0 | 3036140064 | 5.0 | 50 | time_horizon |
| … | | | | | | | | | |

**`inner_decisions.csv`** — every decision made *inside* each inner
simulation:

| `inner_id` | `trigger` | `action` | `replication` | `t` | `decision` |
|---|---|---|---|---|---|
| j0-a0-k0 | 0 | 0 | 0 | 1.0 | 0.0 |
| j0-a0-k0 | 0 | 0 | 0 | 2.0 | 8.0 |
| j0-a0-k0 | 0 | 0 | 0 | 3.0 | 2.0 |
| … | | | | | |

{doc}`Raw data files <../api/raw-data>` lists all columns. In code,
`env.print_rollout_summary()` shows the same numbers, one line per
decision with the pick starred:

```text
rollout summary (metric 'cost', 8 triggers, 12 actions)
  trigger  0 (t=1): 0:11.8*  1:12.8  2:13.8  3:14.8  4:15.8  5:16.8  6:17.8  7:18.8  8:19.8  9:21.0  10:22.8  base_policy:16.8
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
| `set_inner_stopping_condition(relative_time=H)` | each branch runs `H` time units past the trigger point — the lookahead window |
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
