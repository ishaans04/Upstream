"""Sensors and labs: regular where citizens are irregular, and late where they are quick.

A turbidity sensor reports every 15 minutes from one place, drops out now and
then, and has its own noise. A lab result is quantitative and definitive, and it
arrives a day or more after the water was sampled (PRD 15.1): the benchmark and
belief replay both need evidence whose `event_time` is long before the moment the
system learned of it (GC-4).
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from .citizens import DETECTION

SENSOR_STEP_S = 900
DROPOUT_P = 0.08
LAB_CFU_AT_UNIT_C = 5.0e4             # CFU/100 mL at relative concentration 1.0
LAB_LOG_SD = 0.6
LAB_DELAY_H = (20.0, 72.0)            # uniform: overnight culture up to a weekend


def generate_sensor_readings(net, plume, rng: np.random.Generator, *, n_sensors: int,
                             start: dt.datetime, end: dt.datetime) -> list[dict]:
    if n_sensors <= 0:
        return []
    nodes = rng.choice(len(net.node_ids), size=n_sensors, replace=False)
    curve = DETECTION["sensor_turbidity"]
    t0 = (start.timestamp() // SENSOR_STEP_S) * SENSOR_STEP_S
    times = np.arange(t0, end.timestamp(), SENSOR_STEP_S)
    out = []
    for i, node in enumerate(nodes):
        for t in times:
            if rng.random() < DROPOUT_P:
                continue                                  # the sensor said nothing
            c = float(plume.concentration(int(node), float(t)))
            positive = bool(rng.random() < curve.p_positive(c))
            out.append({"node_id": net.node_ids[int(node)],
                        "observed_at": dt.datetime.fromtimestamp(float(t), dt.UTC),
                        "method": "sensor_turbidity",
                        "result": "positive" if positive else "negative",
                        "observer_id": f"sim-sensor-{i:02d}", "observer_type": "sensor",
                        "snap_distance_m": 0.0, "confirmed_by_observer": True,
                        "true_concentration": c})
    return sorted(out, key=lambda r: r["observed_at"])


def generate_lab_results(net, plume, rng: np.random.Generator, *, n: int,
                         sampled_between: tuple[dt.datetime, dt.datetime]) -> list[dict]:
    """Grab samples downstream of the release, cultured, reported a day or more later.

    Each result carries `reported_at`: when the lab's result would reach the system.
    """
    reachable = np.flatnonzero(np.isfinite(plume.arrival_s))
    if n <= 0 or len(reachable) == 0:
        return []
    lo, hi = (d.timestamp() for d in sampled_between)
    out = []
    for _ in range(n):
        node = int(rng.choice(reachable))
        t = float(rng.uniform(lo, hi))
        c = float(plume.concentration(node, t))
        cfu = float(max(c * LAB_CFU_AT_UNIT_C, 1.0) * rng.lognormal(0.0, LAB_LOG_SD))
        sampled = dt.datetime.fromtimestamp(t, dt.UTC)
        out.append({"node_id": net.node_ids[node], "observed_at": sampled,
                    "method": "lab_ecoli", "result": "quantitative",
                    "value": round(cfu, 1), "unit": "{CFU}/(100.mL)",
                    "observer_id": "sim-lab", "observer_type": "lab",
                    "snap_distance_m": 0.0, "confirmed_by_observer": True,
                    "reported_at": sampled + dt.timedelta(hours=float(rng.uniform(*LAB_DELAY_H))),
                    "true_concentration": c})
    return sorted(out, key=lambda r: r["reported_at"])
