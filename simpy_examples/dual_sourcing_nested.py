"""
SimPy simulation of the dual-sourcing inventory model of

    Song, J.-S., Xiao, L., Zhang, H., & Zipkin, P. (2017).
    "Optimal Policies for a Dual-Sourcing Inventory Problem with
    Endogenous Stochastic Leadtimes." Operations Research 65(2):379-395.

Model (paper, Section 3)
------------------------
* Single product, unit-sized Poisson demand (rate lambda), full
  backlogging, continuous review, no fixed order cost.
* The normal source is a two-stage tandem queue: a normal order joins
  server 1 (exp. rate mu1), then server 2 (exp. rate mu2), then reaches
  stock.  An emergency order skips server 1 and joins server 2 directly.
  Both servers are FIFO and work-conserving.  Lead times are therefore
  ENDOGENOUS: ordering more congests the queues and lengthens lead times.
* Costs -- all six components of the paper:
    c1  per unit ordered from the normal source (charged at placement)
    c2  per unit ordered from the emergency source, c2 > c1
    h1  holding per unit per unit time at server 1
    h2  holding per unit per unit time at server 2
    h   holding per unit per unit time on finished goods on hand
    b   backorder per unit per unit time
  The paper normalizes h1 to 0 by folding it into c1 (Section 3); the
  default below follows that convention, but h1 is a parameter, so a
  nonzero value is also handled.

Default parameter values are the instance of Table 5 (Section 6) with
h=1, b=60, h2=2 (lambda=6, mu1=8, mu2=7, c1=10, c2=30), run with the
clock twice as fast: demand 12 per unit time, production rates 16 and
14, the time-proportional cost rates doubled (h=2, b=120, h2=4), and
the per-unit costs c1, c2 as they were.  The same sample paths then
play out in half the time at the same total cost, so the utilizations
are unchanged, the paper's best Dual-Index (DI) policy, s1=30, s2=12,
is still the best DI policy, and every long-run average cost per unit
time doubles:
    optimal policy 193.03 | TC policy 193.07 | best DI policy 199.78
(the paper: 96.5149 | 96.5349 | 99.8904).  The DualIndexPolicy below
with those parameters is exactly the paper's DI benchmark, so the
simulation can be validated against 199.78.

Policies
--------
A policy is a callable ``policy(state) -> (normal, emergency)`` giving
the number of units to order from each source now; it is consulted after
every demand and every state change of the supply system.  The paper's
DI policy (Section 6.2) maintains IP1 = IN + N2 + N1 at s1 and
IP2 = IN + N2 at or above s2.

This is the rollout version: the same policy object goes into
env.decide, which tries each candidate order in inner simulations at
every review and executes the best-scoring one.
"""

from __future__ import annotations

from _imports import *  # NestedSimPy names + shared example helpers

from dataclasses import dataclass

import numpy as np

# One entry per candidate decision, in the shape the policy returns:
# (normal, emergency) -- order nothing, one normal unit, one emergency
# unit, or both.  The baseline policy's own decision competes
# automatically -- it can be a larger order than any of these, e.g.
# the opening order that fills the position up to s1.
ACTIONS = [(0, 0), (1, 0), (0, 1), (1, 1)]
INNER_HORIZON = 1.5      # lookahead window, in time units
INNER_REPS = 12          # replications per action

NESTED_OUTPUT_FOLDER = set_nested_output_folder("simpy_examples",
                                                "dual_sourcing")


# ---------------------------------------------------------------------------
# Parameters (problem data only -- no logic).  Values: paper's Table 5,
# row h=1, b=60, h2=2, at twice the speed (rates and time-proportional
# costs doubled).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Params:
    demand_rate: float = 12.0      # lambda: Poisson demand rate
    stage1_rate: float = 16.0      # mu1: exponential rate of server 1
    stage2_rate: float = 14.0      # mu2: exponential rate of server 2
    normal_cost: float = 10.0      # c1: $ per unit, normal source
    emergency_cost: float = 30.0   # c2: $ per unit, emergency source
    stage1_holding: float = 0.0    # h1: $/unit/time at server 1 (paper
    #                                normalizes h1 = 0, folding it into c1)
    stage2_holding: float = 4.0    # h2: $/unit/time at server 2
    holding_cost: float = 2.0      # h:  $/unit/time on hand
    backorder_cost: float = 120.0  # b:  $/unit/time backlogged
    horizon: float = 2000.0        # length of one simulation run
    warmup: float = 200.0          # costs before this time are discarded
    initial_net: int = 12          # on-hand stock at time 0, empty pipeline


# ---------------------------------------------------------------------------
# Observable system state and policies
# ---------------------------------------------------------------------------

@dataclass
class State:
    net: int      # IN: on-hand minus backlog (negative = backlogged)
    stage1: int   # N1: units waiting at or being processed by server 1
    stage2: int   # N2: units waiting at or being processed by server 2

    @property
    def ip1(self) -> int:
        """IP1 = IN + N2 + N1: position including both sources (eq. 24)."""
        return self.net + self.stage1 + self.stage2

    @property
    def ip2(self) -> int:
        """IP2 = IN + N2: position past server 1 (eq. 25)."""
        return self.net + self.stage2


class DualIndexPolicy:
    """The paper's Dual-Index (DI) policy, Section 6.2 (Song-Zipkin 2009).

    Maintain IP2 >= s2 with emergency orders, then IP1 = s1 with normal
    orders.  Set s2 = None to never use the emergency source.
    """

    def __init__(self, s1: int, s2: int | None = None):
        self.s1, self.s2 = s1, s2

    def __call__(self, state: State) -> tuple[int, int]:
        emergency = 0 if self.s2 is None else max(0, self.s2 - state.ip2)
        normal = max(0, self.s1 - state.ip1 - emergency)
        return normal, emergency

    def __repr__(self):
        return f"DualIndex(s1={self.s1}, s2={self.s2})"


# ---------------------------------------------------------------------------
# One replication, with the emergency decision handed to NestedSimPy
# ---------------------------------------------------------------------------

def simulate(params: Params, policy, seed: int, *,
             inner_horizon=INNER_HORIZON, inner_reps=INNER_REPS,
             out_dir=None) -> dict:
    """One rollout run; returns costs, counts and the environment."""
    p = params
    np.random.seed(seed)
    env = NestedEnvironment()
    server1 = NestedResource(env, capacity=1, nested_id="server1")
    server2 = NestedResource(env, capacity=1, nested_id="server2")
    state = State(net=p.initial_net, stage1=0, stage2=0)
    costs = {"holding": 0.0, "backorder": 0.0, "pipeline": 0.0,
             "ordering": 0.0}
    counts = {"normal": 0, "emergency": 0}
    last_accrual = [0.0]

    def accrue():
        """Charge all time-proportional costs since the last state change.

        Must be called BEFORE any change to net, stage1, or stage2.
        """
        dt = env.now - last_accrual[0]
        increment = (p.holding_cost * max(state.net, 0)
                     + p.backorder_cost * max(-state.net, 0)
                     + p.stage1_holding * state.stage1
                     + p.stage2_holding * state.stage2) * dt
        costs["holding"] += p.holding_cost * max(state.net, 0) * dt
        costs["backorder"] += p.backorder_cost * max(-state.net, 0) * dt
        costs["pipeline"] += (p.stage1_holding * state.stage1
                              + p.stage2_holding * state.stage2) * dt
        env.record("cost", increment)               # expose to the branches
        last_accrual[0] = env.now

    def produced_unit(emergency: bool):
        """Lifecycle of one ordered unit until it reaches inventory."""
        if not emergency:
            with server1.request() as turn:
                yield turn
                yield env.nested_timeout(
                    {"distribution": "exponential", "rate": p.stage1_rate})
            accrue()
            state.stage1 -= 1
            state.stage2 += 1
        with server2.request() as turn:
            yield turn
            yield env.nested_timeout(
                {"distribution": "exponential", "rate": p.stage2_rate})
        accrue()
        state.stage2 -= 1
        state.net += 1          # delivery to stock
        yield from review()

    def review():
        """Ask NestedSimPy for orders and launch them into the supply system."""
        # decide publishes its event ("review" by default) and that event is
        # the branch trigger: NestedSimPy launches one inner simulation per
        # (action, replication) here before this line returns.
        normal, emergency = yield from env.decide(policy, state)
        counts["normal"] += normal
        counts["emergency"] += emergency
        spend = normal * p.normal_cost + emergency * p.emergency_cost
        costs["ordering"] += spend
        env.record("cost", spend)                   # branches pay for orders
        # Pipeline counts are updated here, at order time, so that any
        # later review at the same instant already sees these orders.
        accrue()
        state.stage2 += emergency
        state.stage1 += normal
        for _ in range(emergency):
            env.process(produced_unit(emergency=True))
        for _ in range(normal):
            env.process(produced_unit(emergency=False))

    def demand_process():
        while True:
            yield env.nested_timeout(
                {"distribution": "exponential", "rate": p.demand_rate})
            accrue()
            state.net -= 1      # unmet demand is backlogged (net < 0)
            yield from review()

    def warmup_reset():
        """Discard costs incurred during the warm-up transient."""
        yield env.timeout(p.warmup)
        accrue()
        for key in costs:
            costs[key] = 0.0
        for key in counts:
            counts[key] = 0

    env.process(demand_process())
    if p.warmup > 0:        # a zero warm-up discards nothing
        env.process(warmup_reset())
    env.process(review())               # initial decision at time 0

    # No trigger configuration here: with actions declared and none given,
    # NestedSimPy branches on the event decide publishes.  Set it explicitly
    # -- set_triggering_conditions({"on": "event", "name": ...}) -- for a
    # custom event name, or to branch on something besides the decisions.
    env.set_outer_stopping_condition(timeout=p.horizon)     # end of the run
    env.set_inner_stopping_condition(relative_time=float(inner_horizon))
    env.set_inner_repetitions(inner_reps)                   # branches/action
    env.set_rng("CRN")
    env.set_outer_seed(seed)
    env.set_inner_actions(ACTIONS, metric="cost",
                          outer_run_mode="rollout")
    env.set_output_options(out_dir=out_dir, gzip_trace=False)
    env.nested_run()
    accrue()                    # charge costs for the final interval

    return {"costs": costs, "counts": counts,
            "total_cost": sum(costs.values()), "env": env}


# ---------------------------------------------------------------------------
# Main: one short transient-start demo run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # One short run from the initial state, no warm-up: about 150
    # demands and about as many deliveries, each one a review.
    params = Params(horizon=12.5, warmup=0.0)
    policy = DualIndexPolicy(s1=30, s2=12)      # the paper's best DI baseline
    r = simulate(params, policy, seed=1, out_dir=NESTED_OUTPUT_FOLDER)
    print(f"rollout over {len(ACTIONS) + 1} candidates on {policy!r}: "
          f"total cost {r['total_cost']:.1f} over {params.horizon:g} "
          f"({r['total_cost'] / params.horizon:.2f} per unit time)")
    print(f"  ordered {r['counts']['normal']} normal, "
          f"{r['counts']['emergency']} emergency")
