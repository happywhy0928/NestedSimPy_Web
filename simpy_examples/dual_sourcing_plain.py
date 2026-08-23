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
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import simpy


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
# One replication
# ---------------------------------------------------------------------------

def simulate(params: Params, policy, seed: int) -> dict:
    """Simulate one run; return costs and order counts (post-warm-up)."""
    p = params
    np.random.seed(seed)
    env = simpy.Environment()
    server1 = simpy.Resource(env, capacity=1)
    server2 = simpy.Resource(env, capacity=1)
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
        costs["holding"] += p.holding_cost * max(state.net, 0) * dt
        costs["backorder"] += p.backorder_cost * max(-state.net, 0) * dt
        costs["pipeline"] += (p.stage1_holding * state.stage1
                              + p.stage2_holding * state.stage2) * dt
        last_accrual[0] = env.now

    def produced_unit(emergency: bool):
        """Lifecycle of one ordered unit until it reaches inventory."""
        if not emergency:
            with server1.request() as turn:
                yield turn
                yield env.timeout(np.random.exponential(1 / p.stage1_rate))
            accrue()
            state.stage1 -= 1
            state.stage2 += 1
        with server2.request() as turn:
            yield turn
            yield env.timeout(np.random.exponential(1 / p.stage2_rate))
        accrue()
        state.stage2 -= 1
        state.net += 1          # delivery to stock
        review()

    def review():
        """Ask the policy for orders and launch them into the supply system."""
        normal, emergency = policy(state)
        counts["normal"] += normal
        counts["emergency"] += emergency
        costs["ordering"] += (normal * p.normal_cost
                              + emergency * p.emergency_cost)
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
            yield env.timeout(np.random.exponential(1 / p.demand_rate))
            accrue()
            state.net -= 1      # unmet demand is backlogged (net < 0)
            review()

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
    review()                    # initial ordering decision at time 0
    env.run(until=p.horizon)
    accrue()                    # charge costs for the final interval

    return {"costs": costs, "counts": counts,
            "total_cost": sum(costs.values())}


# ---------------------------------------------------------------------------
# Policy evaluation over many replications
# ---------------------------------------------------------------------------

def evaluate(params: Params, policy, num_replications: int,
             base_seed: int = 0) -> dict:
    """Estimate the long-run average cost rate of a policy.

    Replication i uses seed base_seed + i, so different policies are
    compared on common random numbers.  Returns the mean cost per unit
    time (measured after warm-up), its 95% confidence interval, and a
    cost breakdown.
    """
    time = params.horizon - params.warmup
    runs = [simulate(params, policy, seed=base_seed + i)
            for i in range(num_replications)]
    rates = np.array([r["total_cost"] for r in runs]) / time
    mean, sem = rates.mean(), rates.std(ddof=1) / np.sqrt(len(rates))
    total_units = sum(r["counts"]["normal"] + r["counts"]["emergency"]
                      for r in runs)
    emergency_units = sum(r["counts"]["emergency"] for r in runs)
    breakdown = {key: np.mean([r["costs"][key] for r in runs]) / time
                 for key in runs[0]["costs"]}
    return {
        "mean_cost_rate": mean,
        "ci95": (mean - 1.96 * sem, mean + 1.96 * sem),
        "breakdown": breakdown,
        "pct_emergency": 100.0 * emergency_units / max(total_units, 1),
    }


# ---------------------------------------------------------------------------
# Main: evaluate a few policies on the Table 5 instance at twice the speed
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    params = Params()
    # Sweep s1 around the paper's best DI policy (s1=30, s2=12).  Exact
    # average costs from the paper's eq. (26), times two for the doubled
    # speed:
    #   s1=24: 207.14, s1=27: 201.44, s1=30: 199.78 (best, as reported),
    #   s1=33: 200.80, s1=36: 203.60.
    policies = [DualIndexPolicy(s1=s1, s2=12) for s1 in (24, 27, 30, 33, 36)]

    print(f"Song et al. (2017), Table 5 instance at twice the speed: "
          f"lambda={params.demand_rate}, mu1={params.stage1_rate}, "
          f"mu2={params.stage2_rate}, c1={params.normal_cost}, "
          f"c2={params.emergency_cost}, h={params.holding_cost}, "
          f"b={params.backorder_cost}, h2={params.stage2_holding}")
    print(f"Paper's exact values, doubled: optimal 193.03 | TC 193.07 | "
          f"best DI (s1=30, s2=12) 199.78")
    print(f"{'policy':<28}{'cost/time':>10}{'95% CI':>18}"
          f"{'hold':>7}{'back':>7}{'pipe':>7}{'order':>7}{'%emg':>6}")
    for policy in policies:
        r = evaluate(params, policy, num_replications=100)
        lo, hi = r["ci95"]
        bd = r["breakdown"]
        print(f"{policy!r:<28}{r['mean_cost_rate']:>10.2f}"
              f"{f'[{lo:.2f}, {hi:.2f}]':>18}"
              f"{bd['holding']:>7.2f}{bd['backorder']:>7.2f}"
              f"{bd['pipeline']:>7.2f}{bd['ordering']:>7.2f}"
              f"{r['pct_emergency']:>6.1f}")
