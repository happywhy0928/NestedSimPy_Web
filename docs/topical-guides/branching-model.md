# From SimPy to NestedSimPy

We transform a given SimPy simulation code to NestedSimPy by following three
steps:

1. **Replacing SimPy objects** with corresponding NestedSimPy objects,
2. **Replacing the timeout function call**, and
3. **Configuring the nested simulation parameters**.

The process logic itself often stays very close to the original SimPy model — we
keep the SimPy process functions and change the infrastructure around them.

## 1. Replacing SimPy objects with corresponding NestedSimPy objects

Swap the SimPy environment, its primitives, and the run call for the
equivalents that support nested simulation:

| Plain SimPy | NestedSimPy |
| --- | --- |
| `simpy.Environment()` | `NestedEnvironment()` |
| `simpy.Resource(...)` | `NestedResource(...)` |
| `simpy.PreemptiveResource(...)` | `NestedPreemptiveResource(...)` |
| `simpy.Store(...)` | `NestedStore(...)` |
| `simpy.Container(...)` | `NestedContainer(...)` |
| `env.run()` | `env.nested_run()` |

There is not currently a separate `NestedPriorityResource` class. The
functionality of SimPy's `PriorityResource` can be worked around using
`NestedPreemptiveResource`. Pass `preempt=False` on each request to reproduce
`PriorityResource`'s non-preemptive behaviour — the default `preempt=True`
will interrupt an in-service customer.

The wrapped objects take the same constructor arguments as their SimPy
counterparts, plus one keyword argument: **`nested_id`**, a string naming the
object —

```python
server = NestedResource(env, capacity=1, nested_id="srv")
```

The `nested_id` is the object's identity throughout NestedSimPy: it is how you
refer to the object in the configuration calls of step 3 (e.g.
`set_triggering_objects(nested_id="srv")`), and it labels the object's columns
in the exported data (e.g. `(srv)state_num_customers_in_queue` — see
{doc}`Exporting data <traces-and-outputs>`). Each object registers itself with
the environment under this id when constructed, so ids must be unique within a
run. If omitted, ids are assigned automatically with running numbers: the
first unnamed resource is `srv`, later ones `srv2`, `srv3`, ...; stores count
`store`, `store2`, ... and containers `container`, `container2`, .... The
automatic ids are distinct, but named configuration and readable outputs are
easier with explicit ids, so name every object once a model has more than
one.

The wrapped objects play the same roles as before:

`NestedEnvironment`
: Stores branching configuration and provides nested simulation support —
  entry points such as
  `nested_run()` and `run_single_path(...)`.

`NestedResource`, `NestedPreemptiveResource`, `NestedStore`, `NestedContainer`
: Wrapped SimPy classes to support branching to inner simulation and
  recording their execution.

## 2. Replacing the timeout function call

In SimPy, timeouts use deterministic values:

```python
yield env.timeout(random.expovariate(rate))   # the value is fixed right here
```

In contrast, NestedSimPy uses stochastic values using an alternative timeout
call:

```python
yield env.nested_timeout({"distribution": "exponential", "lambda": rate})
```

Whenever an inner simulation is invoked, NestedSimPy dynamically resamples the
remaining timeout according to the specified distribution. This is critical
for preventing bias in the inner simulation runs which would propagate to the
estimation of system performance metrics.

NestedSimPy supports the following probability distributions:

| Distribution | Spec |
| --- | --- |
| Exponential | `{"distribution": "exponential", "lambda": rate}` |
| Uniform | `{"distribution": "uniform", "low": a, "high": b}` |
| Normal (truncated at 0) | `{"distribution": "normal", "mean": mu, "std": sigma}` |
| Log-normal | `{"distribution": "log-normal", "mu": mu, "sigma": sigma}` |
| Deterministic | `{"distribution": "deterministic", "value": d}` |
| Discrete | `{"distribution": "discrete", "support": [...], "probabilities": [...]}` |

In particular, the `discrete` parameter allows the user to define arbitrary
discrete probability distributions: when a delay takes one of a few known
values, enter the support and the matching probabilities — NestedSimPy takes
care of the rest (validation, sampling, and the correct residual at a
trigger point):

```python
yield env.nested_timeout(
    {
        "distribution": "discrete",
        "support": [0.5, 1.0, 2.0],          # the possible durations
        "probabilities": [0.25, 0.5, 0.25],  # must sum to 1
    }
)
```

The two lists must have the same length, the probabilities must be
non-negative and sum to 1 (tiny floating-point slack is normalised away;
anything else raises a clear `ValueError`). When an inner simulation resumes
such a delay mid-flight, the residual is drawn from the support values still
reachable — those greater than the time already elapsed — with their
probabilities renormalised.

Capped (truncated) exponential and integer-uniform variants are also
available; see `nestedsimpy.sleep.resolve_distribution` for the full set.

## 3. Configuring the nested simulation parameters

Finally, declare how the nested simulation runs — what triggers branching, how
many inner simulations to launch, and when the inner and outer runs stop. (Your own
SimPy processes — the arrival generator and the customer logic — are omitted
here; the {doc}`Simple example <../simple-example>` is the full runnable file.)

```python
env = NestedEnvironment()
server = NestedResource(env, capacity=1, nested_id="srv")
env.process(arrivals(env, server))             # your model's processes

env.set_output_options(out_dir="out/mm1_simpy", gzip_trace=False)
env.set_rng("independent")                     # each branch draws its own future
env.set_triggering_objects(nested_id="srv")
env.set_triggering_conditions({"on": "arrival", "frequency": 1})
env.set_inner_repetitions(3)
env.set_inner_stopping_condition(relative_time=5.0, triggering_customer_departs=True)
env.set_outer_stopping_condition(timeout=10.0)
env.nested_run()
```

Line by line, each call configures one aspect of the run:

| Call | What it configures | Details |
| --- | --- | --- |
| `set_output_options(out_dir=..., gzip_trace=...)` | Where the run's outputs are written (`out_dir`, a directory path — each run creates a fresh subdirectory inside it) and whether the raw trace files are gzip-compressed (`gzip_trace`, default `True`; `False` keeps them human-readable). | {doc}`Exporting data <traces-and-outputs>` |
| `set_rng(mode)` | How the inner branches draw randomness: `"independent"` or `"CRN"` — see below. | — |
| `set_triggering_objects(nested_id=...)` | Which object(s) — by their `nested_id` — are watched for trigger events. Pass a list for several. | {doc}`Triggering events <branch-triggers>` |
| `set_triggering_conditions(spec)` | *When* to branch: a dict such as `{"on": "arrival", "frequency": 1}` (branch at every arrival), or a list of such dicts to arm several conditions at once. `frequency=n` branches at every *n*-th occurrence. | {doc}`Triggering events <branch-triggers>` |
| `set_inner_repetitions(count)` | How many inner simulations to launch at each trigger event (a positive `int`). | — |
| `set_inner_stopping_condition(...)` | When each inner branch stops — here after 5 time units past the trigger point, or as soon as the triggering customer finishes, whichever comes first. At least one inner rule is required. | {doc}`Stopping conditions <stop-rules-replay>` |
| `set_outer_stopping_condition(timeout=...)` | When the outer simulation stops — here at time 10. | {doc}`Stopping conditions <stop-rules-replay>` |
| `nested_run()` | Executes the configured run: the outer simulation advances, launches the inner simulations at every trigger event, and writes all outputs under `out_dir`. | — |

Two of the calls are strictly required before `nested_run()` —
`set_inner_repetitions` and `set_inner_stopping_condition` (the run raises a
clear error otherwise). The others have working defaults, but a real model
sets them all explicitly. To make the run reproducible, also fix the seed with
`env.set_outer_seed(42)` (any `int`; the default seed is `2025`).

`set_rng` chooses how the branches sample: `"independent"` gives each inner its
own random stream (so they explore different futures), while `"CRN"` shares one
stream across branches (useful when comparing policies on the same randomness).

## 4. When the model also makes decisions

Steps 1-3 cover models without decision points. If your model must
also *choose* at certain moments (how much to order, whether to admit),
three more changes convert the decision itself — everything else
above stays as it is.

**4a. Declare the candidates.** Give one entry per candidate decision, in
the shape your policy returns; the baseline policy's own decision is
evaluated alongside them by default:

```python
ACTIONS = list(range(11))  # 0..10
```

**4b. Replace the policy call with the decision line.** The policy
object itself goes in, unchanged, and `yield from` is required (every
caller on the path to a decision needs it too):

```python
order = base_policy(state)                        # before
order = yield from env.decide(base_policy, state) # after
```

**4c. Record the cost and declare the actions in the configuration.**
One `env.record("cost", ...)` line wherever cost arises, and one extra
configuration call. No triggering configuration is needed (see
{doc}`Triggering events <branch-triggers>`) — if decisions are your
only branch points, drop the `set_triggering_objects` /
`set_triggering_conditions` lines from step 3:

```python
env.record("cost", period_cost)
env.set_inner_actions(ACTIONS, metric="cost", outer_run_mode="rollout")
```

See {doc}`Implementing lookahead policies <lookahead-actions>` for the
full contract and its worked example.
