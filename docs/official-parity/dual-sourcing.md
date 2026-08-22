---
orphan: true
---

# Dual Sourcing with Lookahead Expediting

## Scenario

An example for using NestedSimPy for optimization (not from the SimPy
documentation). We simulate the dual-sourcing inventory model of Song,
Xiao, Zhang and Zipkin (2017), "Optimal Policies for a Dual-Sourcing
Inventory Problem with Endogenous Stochastic Leadtimes", *Operations
Research* 65(2):379–395.

A single product faces unit Poisson demand
with full backlogging; normal orders ride a two-stage tandem production
line, so lead times are endogenous (ordering more congests the line),
and an expedited order — the paper's emergency source — skips stage 1
at a higher per-unit cost. At each
decision epoch the decision-maker decides whether to place a normal or
an expedited order.

The example illustrates how NestedSimPy applies
rollout (policy lookahead) of an existing baseline policy: both files
run the paper's Table 5 instance (h=1, b=60, h2=2), whose best
Dual-Index policy (s1=30, s2=12) has an exact cost rate of 99.89 in the
paper. The plain version follows Dual-Index policies as written — its
driver sweeps s1 around the best one to validate the simulator against
the paper's exact values. The nested version runs the best policy with
demand raised from 6 to 6.5 per unit time, so that stage 2 (rate 7,
and every order passes through it) runs at 93% utilization, congested
enough for lead times to depend on the queue. It hands each decision
to `env.decide`, trying each candidate order in inner simulations
launched from the live production line.

```{tip}
**Run it live:** [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/NestedSimPy/nestedsimpy.github.io/blob/main/notebooks/NestedSimPy_dual_sourcing.ipynb)
— installs NestedSimPy and runs this example in your browser.
```

## Files

- Plain SimPy: [`simpy_examples/dual_sourcing_plain.py`](https://github.com/NestedSimPy/nestedsimpy.github.io/blob/main/simpy_examples/dual_sourcing_plain.py)
- NestedSimPy: [`simpy_examples/dual_sourcing_nested.py`](https://github.com/NestedSimPy/nestedsimpy.github.io/blob/main/simpy_examples/dual_sourcing_nested.py)

## Code

### Plain SimPy

```{literalinclude} ../../simpy_examples/dual_sourcing_plain.py
:language: python
:caption: simpy_examples/dual_sourcing_plain.py
```

### NestedSimPy

```{codeannotate} ../../simpy_examples/dual_sourcing_plain.py ../../simpy_examples/dual_sourcing_nested.py
:title: simpy_examples/dual_sourcing_nested.py
```

## Discussion

The baseline policy — the rule the rollout starts from and tries to
improve — is the paper's `DualIndexPolicy`, the same object in both
files. It goes into the decision line as is:

```python
ACTIONS = [(0, 0), (1, 0), (0, 1), (1, 1)]

normal, emergency = yield from env.decide(policy, state)
```

Each action is a complete `(normal, emergency)` order — how many units
to order normally, and how many to expedite. Five candidates compete
at every review (each `env.decide` call); when the baseline's decision
coincides with a listed action the two are still scored separately,
and an exact tie goes to the baseline:

| candidate | meaning |
|---|---|
| the baseline's own decision (evaluated by default) | whatever Dual-Index says — usually `(0, 0)` or `(1, 0)`, since reviews follow each demand and each delivery; occasionally larger, e.g. the opening order that raises the inventory position to `s1` |
| `(0, 0)` | order nothing at this review |
| `(1, 0)` | order one unit normally |
| `(0, 1)` | expedite one unit rather than ordering it normally |
| `(1, 1)` | order one unit normally and expedite another |

Each inner simulation tries its candidate once and then hands control
back to the Dual-Index rule, so the only thing the simulations disagree
on is that first decision. Two lines carry the rollout logic:
`set_inner_actions(ACTIONS, metric="cost", outer_run_mode="rollout")`
declares the candidates, and `env.record("cost", ...)` tells NestedSimPy
what to add up when comparing them; the window, replication and seed
settings around them are the standard configuration shown in the code
above. No trigger configuration is needed — `env.decide` marks the
decision points by itself.

Why does this model need nested simulation at all? Because lead times
are endogenous: how long an order takes depends on how busy the
production line is at that moment, so there is no lead-time
distribution to plug into a formula. A forked inner simulation
sidesteps the problem — it carries the whole production line with it,
including the units halfway through service, and every pending delay
is redrawn from its conditional distribution (that is what declaring
the three exponential delays as `nested_timeout` buys).

See {doc}`Implementing lookahead policies
<../topical-guides/lookahead-actions>` for the full contract; the
two-argument decision form `fn(state, action)`, for models whose
decision variables are coupled, is covered in
{doc}`the API reference <../api/simpy-core>`.

