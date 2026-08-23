"""
Periodic-review inventory example.

Covers:

- A periodic process with an order decision each period
- Containers: Container

Scenario:
  A single item faces Poisson demand each period. Each period opens
  with the order decision: the order-up-to rule looks at the inventory
  position (on hand plus in the pipeline) and orders the shortfall.
  The order placed one period earlier then arrives, demand realizes,
  and holding and shortage costs accrue. An order placed this period
  is on hand for the next period's demand (one period of lead time).
  This is the lookahead version: env.decide tries each candidate
  order quantity in inner simulations and executes the one with the
  lowest average cost.
"""

from _imports import *  # NestedSimPy names + shared example helpers

import numpy as np

RANDOM_SEED = 12
PERIODS = 8                # review periods
MEAN_DEMAND = 5.0          # Poisson demand per period
HOLD_COST = 1.0            # per unit on hand per period
SHORTAGE_COST = 9.0        # per unit short per period (lost sales)
ORDER_UP_TO = 10           # the rule's target position
ACTIONS = list(range(21))  # 0..20; the baseline's own order also competes
INNER_HORIZON = 4          # the lookahead window, in periods
INNER_REPS = 16            # inner branches per candidate

NESTED_OUTPUT_FOLDER = set_nested_output_folder("simpy_examples",
                                                "inventory_lookahead")


def base_policy(state):
    """Order up to ORDER_UP_TO on the inventory position."""
    position = int(state["stock"].level) + int(state["pipeline"].level)
    return max(0, ORDER_UP_TO - position)


def periods(env, state):
    while True:
        yield env.timeout(1.0)
        landing = int(state["pipeline"].level)      # last period's order, due now
        order = yield from env.decide(base_policy, state)   # this period's order
        if order > 0:
            state["pipeline"].put(order)            # arrives next period
        if landing:
            state["pipeline"].get(landing)
            state["stock"].put(landing)
        demand = int(np.random.poisson(MEAN_DEMAND))
        sales = min(int(state["stock"].level), demand)
        if sales:
            state["stock"].get(sales)
        on_hand = int(state["stock"].level)
        short = demand - sales                      # lost sales

        period_cost = HOLD_COST * on_hand + SHORTAGE_COST * short
        env.record("cost", period_cost)             # scores the branches
        state["cumulative_cost"] += period_cost


def run():
    np.random.seed(RANDOM_SEED)
    env = NestedEnvironment()
    state = {
        "stock": NestedContainer(env, capacity=float("inf"), init=10,
                                 nested_id="stock"),
        "pipeline": NestedContainer(env, capacity=float("inf"), init=0,
                                    nested_id="pipeline"),
        "cumulative_cost": 0.0,
    }
    env.process(periods(env, state))

    # No trigger configuration: NestedSimPy branches on decide's event.
    env.set_outer_stopping_condition(timeout=PERIODS + 0.5)
    env.set_inner_stopping_condition(relative_time=float(INNER_HORIZON))
    env.set_inner_repetitions(INNER_REPS)
    env.set_rng("CRN")
    env.set_outer_seed(RANDOM_SEED)
    env.set_inner_actions(ACTIONS, metric="cost", outer_run_mode="rollout")
    env.set_output_options(out_dir=NESTED_OUTPUT_FOLDER, gzip_trace=False)
    env.nested_run()
    return state["cumulative_cost"], env


if __name__ == "__main__":
    total, env = run()
    by_action = env.get_inner_results_by_action(metric="cost")
    print(f"total cost {total:.1f} over {PERIODS} periods "
          f"({len(by_action)} decisions)")
    first = min(by_action)
    for action, values in sorted(by_action[first].items(), key=lambda i: str(i[0])):
        valid = [v for v in values if v is not None]
        mean = sum(valid) / len(valid) if valid else float("nan")
        pick = " <- executed" if action == env.best_inner_action(
            trigger=first, metric="cost") else ""
        label = "base_policy" if action is None else repr(action)
        print(f"  first decision, {label:11}: mean {mean:6.1f}{pick}")
