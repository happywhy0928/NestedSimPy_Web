# Stopping conditions

NestedSimPy controls both when the outer trajectory stops and when each inner
simulation stops after the trigger point.

## Outer stop rules

Use `set_outer_stopping_condition(...)` to bound the outer simulation by time or
by an arrival count:

```python
env.set_outer_stopping_condition(timeout=10.0, max_arrivals=8)
```

The outer trajectory ends when one of the configured conditions fires.

Both arguments are keyword-only arguments of
`NestedEnvironment.set_outer_stopping_condition`, and both are optional — set
one or both:

| Argument | Type | Meaning | When it fires |
| --- | --- | --- | --- |
| `timeout` | `float` | Stop the outer run at this simulation time. | The moment the outer clock reaches the value. The outer run starts at time 0, so this is an absolute stop time. |
| `max_arrivals` | `int` | Stop the outer run after this many arrivals. | An arrival is a request submitted to a triggering object; with several triggering objects one shared counter sums the arrivals across all of them. Fires as soon as the count reaches the threshold. |

When both are given, whichever fires first ends the run. If neither is given,
the outer run only ends when the model runs out of scheduled events — a model
with an endless arrival generator would then never stop, so in practice always
set at least one bound. The reason the outer run ended (`time_limit`,
`arrival_limit`, or `no_events`) is recorded as the `stop_reason` in the
outer run's summary file, `manifest.json`, next to the outer trace under
`raw/` (see {doc}`Raw data <../api/raw-data>`).

Note the asymmetry with the inner rules below: the outer stop accepts only
these two bounds. `StartStopSpec` and custom stop events (next section) apply
to **inner** stopping conditions only.

## Inner stop rules

Use `set_inner_stopping_condition(...)` to control how long each branch keeps
running after a trigger event. Typical options:

- `relative_time=...` — run for this many time units past the trigger point,
- `absolute_time=...` — run until this absolute simulation time,
- `stop_at_outer_horizon=True` — never run past the outer run's own `timeout`,
- `triggering_customer_departs=True` — stop once the triggering customer finishes.

```python
env.set_inner_stopping_condition(
    relative_time=5.0,
    triggering_customer_departs=True,
)
```

That configuration keeps each branch alive for up to five simulated time units,
but also stops as soon as the triggering customer finishes — whichever comes first.

All arguments are keyword-only arguments of
`NestedEnvironment.set_inner_stopping_condition`:

| Argument | Type | Default | Meaning | When it fires |
| --- | --- | --- | --- | --- |
| `relative_time` | `float` | `None` | Time budget per branch. | Exactly `relative_time` time units after the trigger point. |
| `absolute_time` | `float` | `None` | Absolute deadline. Inner branches continue the outer clock (a branch launched at `t = 3.2` starts at `3.2`), so this is a time on that shared clock. | Exactly at that time; a branch launched after the deadline stops immediately. |
| `stop_at_outer_horizon` | `bool` | `False` | Cap every branch at the outer run's horizon, the `timeout` of `set_outer_stopping_condition`. By default a branch runs its full `relative_time` even past that horizon. | At the outer horizon (or at `absolute_time`, whichever is earlier); recorded as `absolute_time`. Requires an outer `timeout`, otherwise `nested_run` raises `ValueError`. |
| `triggering_customer_departs` | `bool` | `False` | Stop when the triggering customer is done. | The moment the triggering customer releases the triggering resource, i.e. its service completes. |
| `event` | `StartStopSpec`, a SimPy event, or a callable returning one | `None` | Stop on the system state or on your own event — see {ref}`custom-and-composed-conditions` below. | Depends on the spec — see below. |

Three behaviours are worth knowing before composing rules:

- **One call, not several.** Calling `set_inner_stopping_condition` again
  *replaces* the previous configuration rather than adding to it — pass
  everything you need in a single call.
- **First one wins.** All configured rules are combined with OR: the branch
  stops at whichever fires first. Each branch records which rule ended it as a
  structured `stop_reason` in its manifest — `time_horizon` (from
  `relative_time`), `absolute_time`, `triggering_customer_departed` (from
  `triggering_customer_departs`), or `state_spec` (from `event=`).
- **At least one rule is required.** A run with no inner stopping condition
  fails at the first trigger event with
  `RuntimeError: Configure at least one inner stopping condition`.

**Who is the triggering customer?** For an arrival trigger it is the
customer whose arrival fired the trigger. For state-predicate and event
triggers no single customer caused the firing, so the triggering customer falls back to the
customer at the head of the queue of the triggering object, or — if the queue
is empty — the customer in service. If the system is empty at the trigger point there
is no triggering customer, and `triggering_customer_departs` is inactive for that branch —
pair it with a time rule, as in the example above.

**What "stop" does.** Stopping is per branch: the inner simulation simply
halts at that moment, no later events happen on that branch, and its trace and
manifest are finalised with the stop time and the `stop_reason`. It has no
effect on the outer run or on the sibling branches launched at the same trigger.

(custom-and-composed-conditions)=
### Custom and composed conditions

The stop rule is not limited to those flags. Pass `event=` a `StartStopSpec` to
stop on the system state or on your own predicate — and compose several with
`any_of` / `all_of`:

```python
from nestedsimpy import StartStopSpec

env.set_inner_stopping_condition(
    event=StartStopSpec(
        any_of=[
            StartStopSpec(queue_ge=10),         # the queue reaches 10, or
            StartStopSpec(system_empty=True),   # the system empties, or
            StartStopSpec(custom=my_predicate),  # a custom predicate returns True
        ]
    ),
)
```

`StartStopSpec` (imported from `nestedsimpy`) is a small immutable dataclass:
each instance declares *one* state-based stop rule, possibly composed of
children. You build it once, pass it to `set_inner_stopping_condition(event=...)`,
and NestedSimPy compiles it into a live predicate separately for every branch
when that branch starts.

#### Field reference

All fields are optional keyword arguments of the `StartStopSpec` constructor,
but at least one must be set (an empty spec raises
`ValueError: StartStopSpec must contain at least one condition`).

| Field | Type | Default | The condition holds when ... |
| --- | --- | --- | --- |
| `time_ge` | `float` | `None` | The simulation time is at or past the value. This is the shared outer/inner clock (the same one `absolute_time` uses), **not** time since the trigger. Mind the evaluation-moment note below. |
| `queue_ge` | `int` | `None` | The number of customers **waiting** at the triggering object is at least the value. In-service customers are not counted. |
| `system_empty` | `bool` | `False` | The triggering object has an empty queue **and** nobody in service. |
| `custom` | callable `() -> bool` | `None` | Your zero-argument callable returns a truthy value. Keep it cheap and side-effect-free — it runs at every check. |
| `any_of` | sequence of `StartStopSpec` | `None` | **Any** child spec holds (logical OR). |
| `all_of` | sequence of `StartStopSpec` | `None` | **All** child specs hold at the same moment (logical AND). |

Two composition rules govern how the fields combine:

- **Fields inside one spec are ANDed.** `StartStopSpec(time_ge=5.0,
  system_empty=True)` fires only at a moment when the time is ≥ 5 *and* the
  system is empty.
- **`any_of` is OR, `all_of` is AND — and they nest.** A child spec can itself
  contain `any_of`/`all_of`, so arbitrary logical trees are possible. The
  flat form and the nested form are equivalent:
  `StartStopSpec(time_ge=5.0, system_empty=True)` is the same rule as
  `StartStopSpec(all_of=[StartStopSpec(time_ge=5.0), StartStopSpec(system_empty=True)])`.

#### When the rule is checked

The compiled predicate is evaluated:

1. **once at the trigger point** — if the condition already holds there, the
   branch stops immediately with a zero-length path (its `end_time` equals the
   trigger time). For example, `system_empty=True` can already hold at the trigger point
   of an arrival trigger, because the snapshot is taken at the instant of the
   arrival, before the arriving customer is granted service;
2. **after every state transition of the triggering object** — every arrival,
   service start, and departure at that object.

Because checks happen only at those moments, `queue_ge` and `system_empty` are
exact (the queue only changes at such events), but a **`time_ge` used on its
own fires late**: the branch stops at the *first event at or after* the
threshold, not at the threshold itself. For an exact-time stop use
`relative_time=` or `absolute_time=` instead; `time_ge` is meant for
compositions such as "empty, but not before time 5" (below).

#### Which object the state refers to

`queue_ge` and `system_empty` are evaluated against the **triggering object of
that branch** — the object whose trigger fired and launched the branch (see
{doc}`Triggering events <branch-triggers>`). In a model with several
triggering objects, each branch therefore watches the object that caused *its
own* trigger event, not a global system count. The two fields assume that object is a
`NestedResource` or `NestedPreemptiveResource`; when the trigger is a
`NestedStore` or `NestedContainer`, express the condition with `custom`
instead — the callable can capture the object in a closure:

```python
tank = NestedContainer(env, capacity=100.0, init=50.0, nested_id="tank")
...
env.set_inner_stopping_condition(
    relative_time=20.0,
    event=StartStopSpec(custom=lambda: tank.level <= 5.0),
)
```

#### A complete example

A runnable M/M/1 model whose branches stop when the queue reaches 10 **or**
the system empties — with a five-unit time budget as a safety net (the
processes are the same as in the {doc}`Simple example <../simple-example>`):

```python
import nestedsimpy
from nestedsimpy import StartStopSpec


def customer(env, server):
    with server.request() as request:
        yield request
        yield env.nested_timeout({"distribution": "exponential", "lambda": 4.0})


def arrivals(env, server):
    while True:
        yield env.nested_timeout({"distribution": "exponential", "lambda": 3.0})
        env.process(customer(env, server))


env = nestedsimpy.NestedEnvironment()
server = nestedsimpy.NestedResource(env, capacity=1, nested_id="srv")
env.process(arrivals(env, server))

env.set_output_options(out_dir="nested_output/mm1_spec", gzip_trace=False)
env.set_rng("independent")
env.set_outer_seed(42)
env.set_triggering_objects(nested_id="srv")
env.set_triggering_conditions({"on": "arrival", "frequency": 1})
env.set_inner_repetitions(3)
env.set_inner_stopping_condition(
    relative_time=5.0,                          # safety net: 5 time units, OR
    event=StartStopSpec(
        any_of=[
            StartStopSpec(queue_ge=10),         # the queue reaches 10, OR
            StartStopSpec(system_empty=True),   # the system empties
        ]
    ),
)
env.set_outer_stopping_condition(timeout=10.0)
env.nested_run()
```

Each branch stops at whichever rule fires first; branches ended by the spec
record `stop_reason = state_spec` in their manifest, branches that used up the
five units record `time_horizon`.

#### Composing with `all_of`

"Stop once the system is empty — but not before time 5" needs both conditions
to hold *at the same moment*, which is what `all_of` (or, equivalently,
several fields in one spec) expresses:

```python
env.set_inner_stopping_condition(
    event=StartStopSpec(
        all_of=[
            StartStopSpec(time_ge=5.0),         # at or past time 5, AND
            StartStopSpec(system_empty=True),   # the system is empty
        ]
    ),
)
```

The branch keeps running through any early idle periods and stops at the first
moment after time 5 at which the system is empty. Since fields inside one spec
are ANDed anyway, `StartStopSpec(time_ge=5.0, system_empty=True)` is the same
rule; `all_of` earns its keep when the children are themselves compositions —
for example `all_of=[StartStopSpec(time_ge=5.0), StartStopSpec(any_of=[...])]`.

#### Stopping on your own SimPy event

You can also hand `event=` a raw SimPy event, or a callable that builds one.
The callable is invoked once per branch, right after the trigger point, and may accept
`(env)`, `(env, resource)`, or `(env, resource, triggering_customer_id)` —
where `resource` is the triggering object and `triggering_customer_id` the
triggering customer's id. It must return a SimPy event; the branch stops when
that event fires:

```python
def branch_deadline(env, resource, triggering_customer_id):
    # Any SimPy event works; here: 1.5 time units after the trigger point.
    return env.timeout(1.5)

env.set_inner_stopping_condition(event=branch_deadline)
```

A *raw* event (rather than a callable) is only useful for events created
inside the running branch — anything constructed before `nested_run()` belongs
to the pre-branch environment — so in practice prefer the callable form.

## Practical rule

Keep the outer stop rules simple, then make the inner stop rules express the
counterfactual horizon you actually care about.

Replaying a single branch has its own page: {doc}`replay`.
