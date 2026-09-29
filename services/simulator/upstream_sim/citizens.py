"""Citizen observations: sparse, irregular, noisy, and biased to where people walk.

People report from where they are, and they are at parks, paths and swimming
spots far more than at an anonymous bend of a culverted stream (PRD 15.1). The
receptor zones are exactly those places, so a node's chance of being reported
from rises steeply within walking distance of one.

Detection is the simulator's own model of people, not the kernel's: each
volunteer has their own reliability, and the curve's numbers are close to the
kernel's but deliberately not equal to them -- a benchmark in which the kernel's
likelihood is exactly the world's would be measuring nothing.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

NEAR_ZONE_M = 150.0
NEAR_ZONE_WEIGHT = 12.0


@dataclass(frozen=True)
class TrueDetection:
    c50: float
    slope: float                   # in log10 units
    false_positive: float

    def p_positive(self, c, reliability: float = 1.0):
        z = (np.log10(np.maximum(c, 1e-12)) - np.log10(self.c50)) / self.slope
        p = self.false_positive + (1 - self.false_positive) / (1 + np.exp(-z))
        return self.false_positive + reliability * (p - self.false_positive)


DETECTION = {
    "citizen_visual_olfactory": TrueDetection(c50=0.33, slope=0.60, false_positive=0.05),
    "test_strip":               TrueDetection(c50=0.13, slope=0.45, false_positive=0.03),
    "sensor_turbidity":         TrueDetection(c50=0.09, slope=0.40, false_positive=0.02),
    "field_test":               TrueDetection(c50=0.05, slope=0.30, false_positive=0.01),
}


def _haversine_m(lonlat_a: np.ndarray, lonlat_b: np.ndarray) -> np.ndarray:
    lon1, lat1 = np.radians(lonlat_a[..., 0]), np.radians(lonlat_a[..., 1])
    lon2, lat2 = np.radians(lonlat_b[..., 0]), np.radians(lonlat_b[..., 1])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * np.arcsin(np.sqrt(a))


def distance_to_nearest_zone_m(net) -> np.ndarray:
    lonlat = np.asarray(net.lonlat, dtype=float)
    zones = lonlat[np.asarray(net.zone_node_idx, dtype=int)]
    d = _haversine_m(lonlat[:, None, :], zones[None, :, :])
    return d.min(axis=1)


def report_weights(net) -> np.ndarray:
    """Where a report comes from: mostly near places people reach the water."""
    near = distance_to_nearest_zone_m(net) <= NEAR_ZONE_M
    w = np.where(near, NEAR_ZONE_WEIGHT, 1.0)
    return w / w.sum()


def generate_citizen_reports(net, plume, scenario, rng: np.random.Generator, *, n: int,
                             now: dt.datetime, lead_s: float = 7200.0) -> list[dict]:
    """`n` reports at random moments from `lead_s` before the release until `now`.

    Returned in time order. Each carries `true_concentration` so the benchmark can
    check the detection model; `to_evidence` strips it before anything is written.
    """
    weights = report_weights(net)
    t_lo = scenario.start.timestamp() - lead_s
    t_hi = now.timestamp()
    nodes = rng.choice(len(net.node_ids), size=n, p=weights)
    times = np.sort(rng.uniform(t_lo, t_hi, size=n))
    curve = DETECTION["citizen_visual_olfactory"]
    reports = []
    for node, t in zip(nodes, times, strict=True):
        c = float(plume.concentration(int(node), float(t)))
        reliability = float(rng.beta(7, 3))              # each volunteer is different
        positive = bool(rng.random() < curve.p_positive(c, reliability))
        reports.append({
            "node_id": net.node_ids[int(node)],
            "observed_at": dt.datetime.fromtimestamp(float(t), dt.UTC),
            "method": "citizen_visual_olfactory",
            "result": "positive" if positive else "negative",
            "observer_id": f"sim-vol-{int(rng.integers(1, 200)):03d}",
            "observer_type": "citizen",
            "snap_distance_m": float(rng.uniform(0, 30)),
            "confirmed_by_observer": True,
            "true_concentration": c,
        })
    return reports


def sample_at(net, plume, node_idx: int, t: float, rng: np.random.Generator, *,
              method: str = "citizen_visual_olfactory", observer_id: str = "sim-mission"
              ) -> dict:
    """One targeted observation -- a mission, or a baseline's chosen sample."""
    c = float(plume.concentration(int(node_idx), float(t)))
    positive = bool(rng.random() < DETECTION[method].p_positive(c, 0.8))
    return {"node_id": net.node_ids[int(node_idx)],
            "observed_at": dt.datetime.fromtimestamp(float(t), dt.UTC), "method": method,
            "result": "positive" if positive else "negative", "observer_id": observer_id,
            "observer_type": "citizen", "snap_distance_m": 5.0,
            "confirmed_by_observer": True, "true_concentration": c}


def to_evidence(report: dict) -> dict:
    """The part of a report the kernel may see: the truth stays behind (GC-10)."""
    return {k: v for k, v in report.items() if k != "true_concentration"}
