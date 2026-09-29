"""FR-35 and the G5 comparison: a blind scan for clusters nobody predicted.

This is what surveillance does when it has no episode to listen for. Every window
of one to `max_window` consecutive days is a candidate cluster; the statistic is
the largest standardised excess over the baseline among all of them, and its
p-value comes from the same statistic on counts drawn from the baseline, which
pays for every window it looked at.

It is the time half of a space-time scan. The health zone holds no geometry -- an
area is a label, which is the point of the boundary -- so areas are scanned
independently and the service corrects for how many it scanned. A deployment
with an area adjacency table would pool neighbouring areas here.

Two jobs use it. The service runs it to find clusters with no matching episode
(the reverse direction of PRD 7.6); the tests run it as the baseline the matched
filter has to beat (G5).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .baselines import Baseline, nb_draw

METHOD = "blind-temporal-scan-nb"
MAX_WINDOW_DAYS = 7


@dataclass(frozen=True)
class Cluster:
    area_code: str
    syndrome: str
    start_day: int
    end_day: int
    p_value: float
    excess: float                       # observed minus expected over the window


def _window_z(counts: np.ndarray, mu0: np.ndarray, var: np.ndarray, max_window: int):
    """Max over windows of (S - M) / sqrt(V), and where it was. `counts` may be a batch."""
    n = counts.shape[-1]
    c = np.concatenate([np.zeros((*counts.shape[:-1], 1)), np.cumsum(counts, -1)], -1)
    m = np.concatenate([[0.0], np.cumsum(mu0)])
    v = np.concatenate([[0.0], np.cumsum(var)])
    best = np.full(counts.shape[:-1], -np.inf)
    where = np.zeros((*counts.shape[:-1], 2), dtype=int)
    for w in range(1, min(max_window, n) + 1):
        s = c[..., w:] - c[..., :-w]
        z = (s - (m[w:] - m[:-w])) / np.sqrt(v[w:] - v[:-w])
        i = np.argmax(z, axis=-1)
        zi = np.take_along_axis(z, i[..., None], -1)[..., 0]
        better = zi > best
        best = np.where(better, zi, best)
        where[..., 0] = np.where(better, i, where[..., 0])
        where[..., 1] = np.where(better, i + w - 1, where[..., 1])
    return best, where


def blind_scan(counts, baseline: Baseline, *, days=None, area_code: str = "",
               syndrome: str = "", max_window: int = MAX_WINDOW_DAYS, n_sim: int = 999,
               seed: int = 0) -> Cluster:
    """The most surprising window in `counts`, with a multiplicity-honest p-value.

    Missing days (NaN) are dropped, which joins the days either side; for a scan
    over at most a week that is the lesser distortion.
    """
    counts = np.asarray(counts, dtype=float)
    days = np.arange(len(counts)) if days is None else np.asarray(days, dtype=np.int64)
    keep = ~np.isnan(counts)
    counts, days = counts[keep], days[keep]
    if len(counts) == 0:
        return Cluster(area_code, syndrome, 0, 0, 1.0, 0.0)

    mu0 = np.maximum(baseline.predict(days), 1e-6)
    var = mu0 + baseline.alpha * mu0 ** 2
    z, where = _window_z(counts, mu0, var, max_window)
    rng = np.random.default_rng(seed)
    z_null, _ = _window_z(nb_draw(mu0, baseline.alpha, rng, size=n_sim), mu0, var, max_window)
    p_value = (1 + np.count_nonzero(z_null >= z)) / (n_sim + 1)
    lo, hi = int(where[0]), int(where[1])
    excess = float(counts[lo:hi + 1].sum() - mu0[lo:hi + 1].sum())
    return Cluster(area_code, syndrome, int(days[lo]), int(days[hi]), float(p_value), excess)
