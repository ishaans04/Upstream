"""PRD 15.1: inject events on the REAL network with realistic noise.

A scenario is everything the world decided and the kernel must work out: which
entry point, when, for how long, how much, and under what weather. It is sampled
the way reality would produce it -- a CSO spills far more often in a storm than
on a dry day -- so the benchmark tests the kernel against the base rates it
claims to know, not against a uniform draw that flatters nothing.

The transport that turns a scenario into concentrations lives in
`transport_truth.py` and deliberately shares no code with the kernel's.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

CONTAMINANTS = ("sewage", "industrial", "runoff")
# (flow condition, rainfall mm/h, probability)
WEATHER = (("dry", 0.0, 0.5), ("wet", 3.0, 0.3), ("storm", 25.0, 0.2))
DURATIONS_S = (900, 3600, 10800)

# How reality weights each source type under each weather. The simulator's own
# numbers -- if they matched the kernel's prior exactly, a benchmark would only
# confirm that the prior agrees with itself.
_SPILL_RATE = {
    "cso":           {"dry": 0.02, "wet": 1.0, "storm": 10.0},
    "storm_outfall": {"dry": 0.4, "wet": 1.5, "storm": 3.0},
    "misconnection": {"dry": 1.0, "wet": 1.0, "storm": 1.0},
    "industrial":    {"dry": 1.0, "wet": 1.0, "storm": 1.0},
}


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    entry_node: str
    start: dt.datetime
    duration_s: int
    mass: float
    contaminant: str
    flow_condition: str
    rainfall_mm_h: float
    seed: int


def sample_scenario(net, rng: np.random.Generator, *, now: dt.datetime | None = None,
                    earliest_h: float = 12.0, latest_h: float = 1.0) -> Scenario:
    """One incident, starting between `earliest_h` and `latest_h` hours before `now`."""
    now = now or dt.datetime.now(dt.UTC)
    w_idx = int(rng.choice(len(WEATHER), p=[w[2] for w in WEATHER]))
    cond, mm, _ = WEATHER[w_idx]
    weights = np.asarray(net.entry_base_rate, dtype=float) * np.array(
        [_SPILL_RATE.get(t, _SPILL_RATE["industrial"])[cond] for t in net.entry_source_type])
    k = int(rng.choice(len(net.entry_nodes), p=weights / weights.sum()))
    start = now - dt.timedelta(hours=float(rng.uniform(latest_h, earliest_h)))
    duration = int(rng.choice(DURATIONS_S))
    # The kernel assumes mass ~ sqrt(duration / 15 min); reality scatters around
    # that by a factor of about 1.6 either way.
    mass = float(np.sqrt(duration / DURATIONS_S[0]) * rng.lognormal(0.0, 0.5))
    seed = int(rng.integers(0, 2**31 - 1))
    return Scenario(scenario_id=f"S{seed:010d}", entry_node=net.entry_nodes[k],
                    start=start.replace(second=0, microsecond=0), duration_s=duration,
                    mass=mass, contaminant=str(rng.choice(CONTAMINANTS)),
                    flow_condition=cond, rainfall_mm_h=mm, seed=seed)
