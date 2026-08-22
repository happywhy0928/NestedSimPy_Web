# Raw data

Every run records raw **JSONL traces** and **manifests** first, then packages
them into the `exports/` CSVs that {doc}`OutputManager <../topical-guides/visualization>`
reads. This page documents that raw layer — useful when debugging behavior or
building a custom reader.

```text
nested_output/<experiment>/<outer_id>/
  raw/
    outer/
      trace.jsonl      # the outer event stream
      manifest.json
    j=0001/            # one directory per trigger event (j = trigger index)
      k=00/            # one directory per branch
        trace.jsonl    # an inner event stream
        manifest.json
  exports/             # CSVs packaged from raw/
  rollout/             # lookahead runs only: manifest.json + 4 CSVs
```

## Trace events

Each line of `trace.jsonl` is one JSON event. Common keys:

`t`
: Simulation time of the event.

`type`
: Event type — e.g. `branch_started`, `request_submitted`, `request_granted`,
  `request_released`, `snapshot`, `checkpoint_reached`, `queue_length`.

`run_kind`, `j`, `k`, `anchor_cust_id`
: `run_kind` is `"outer"` or `"inner"`; `j`/`k` identify the trigger event and
  branch (both `null` on the outer path); `anchor_cust_id` is the triggering
  customer.

`state`
: The recorded state at the event — `current_time`, `queue_len`,
  `in_service_customers`, `customers_in_queue` (a list of `[cust_id, arrival_time]`),
  and the in-service customer's ids and times.

Derived quantities such as the number in system are **not** stored on the raw
event; they are computed during export (number in system = queue length +
in-service count), which is why the packaged CSVs carry extra `state_*` columns.

## Manifests

`manifest.json` summarizes a run: `outer_id`, `seed`, `end_time`, `stop_reason`,
and `event_count`. A branch's manifest additionally describes the trigger event it came
from — `boundary_event`, `anchor_arrival_time`, `trigger_resource`, and the
captured state it resumed from (`checkpoint_time`, `checkpoint_states`,
`anchor_cust_id`).

## Per-branch metrics

Packaging also writes a metrics JSON per branch, with the triggering customer's
outcome in that branch — `anchor_cust_id`, `k`, `anchor_arrival_time`,
`service_start_time`, `service_end_time`, `waiting_time`, and
`service_completion_time` — plus an `[all]` file per trigger event holding the
means and standard deviations across its branches (the source of
`OutputManager.export_outer_case_table()`).

## Lookahead CSVs

A run with declared actions also writes a `rollout/` folder: a
`manifest.json` describing what produced the files (`actions`,
`metric`, `minimize`, `outer_run_mode`, `picks_executed`, `k`,
`replications_per_action`, `decision_count`) and four CSV files, from
the pick down to every decision inside every branch:

- `outer_decisions.csv` — one row per decision epoch: `trigger`,
  `time`, `picked_action`, `decision_taken`, `mean`. A `base_policy`
  cell in `picked_action` means no override: the outer run executed
  the baseline policy's own choice. `decision_taken` is the value the
  outer simulation actually executed; on a `base_policy` row, the
  concrete value the baseline policy chose.
- `inner_trajectories_aggregated.csv` — one row per (decision,
  action): `trigger`, `time`, `action`, `mean`, `std` (population
  standard deviation of the branch scores), `n` (replications),
  `picked`. As everywhere in these files,
  `base_policy` in the `action` cell is the baseline policy's own
  decision.
- `inner_trajectories.csv` — one row per inner simulation: `inner_id`
  (`j<decision>-a<action>-k<replication>`), `trigger`, `fork_time`,
  `action`, `replication`, `value` (the branch's score), `seed`,
  `end_time`, `events`, `stop_reason`.
- `inner_decisions.csv` — one row per decision made *inside* a branch:
  `inner_id`, `trigger`, `action`, `replication`, `t`, `decision`,
  plus one `state_<key>` column per feature when `set_state_features`
  is on. Each branch's first decision is its candidate action; the
  rest come from the baseline policy.

## Reading it back

You rarely need to parse `raw/` by hand: `package_run_outputs(...)` builds the
`exports/` CSVs, and {doc}`OutputManager <../topical-guides/visualization>`
reads those. Reach for the raw traces mainly when debugging a single branch's
behavior.
