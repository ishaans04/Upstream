"""The hypothesis grid.

A hypothesis is (entry node, start bin, duration class), plus two that are not point
sources at all: diffuse runoff across the whole catchment, and nothing happened.

"Nothing happened" has to be in the grid as a real, evaluable hypothesis. Without it
the posterior is conditioned on an event having occurred and can only ever argue about
*which* source - it could never conclude that the reports are noise, and REFUTED would
be unreachable (PRD 7.2, 6.3).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

KIND_POINT, KIND_DIFFUSE, KIND_NONE = 0, 1, 2
DURATION_CLASSES_S: tuple[int, ...] = (900, 3600, 10800)


@dataclass(frozen=True)
class HypothesisGrid:
    H: int
    entry_k: np.ndarray
    t0: np.ndarray
    duration_s: np.ndarray
    kind: np.ndarray
    mass: np.ndarray
    bin_s: int
    horizon_start: float
    horizon_end: float


def build_grid(net, *, horizon_start: dt.datetime, horizon_end: dt.datetime,
               bin_s: int = 900, durations: tuple[int, ...] = DURATION_CLASSES_S
               ) -> HypothesisGrid:
    """A hypothesis is (entry node, start bin, duration class), plus 'diffuse' and 'none'."""
    t_start, t_end = horizon_start.timestamp(), horizon_end.timestamp()
    bins = np.arange(t_start, t_end, bin_s, dtype=np.float64)
    K, B, D = len(net.entry_idx), len(bins), len(durations)

    entry_k = np.repeat(np.arange(K, dtype=np.int32), B * D)
    t0 = np.tile(np.repeat(bins, D), K)
    duration_s = np.tile(np.asarray(durations, dtype=np.float64), K * B)
    kind = np.full(K * B * D, KIND_POINT, dtype=np.int8)
    # Mass grows sub-linearly with duration: a longer spill releases more, but the rate falls.
    mass = np.sqrt(duration_s / durations[0])

    # Two special hypotheses (PRD 7.2).
    entry_k = np.concatenate([entry_k, [-1, -1]]).astype(np.int32)
    t0 = np.concatenate([t0, [t_start, np.nan]])
    duration_s = np.concatenate([duration_s, [float(t_end - t_start), 0.0]])
    kind = np.concatenate([kind, [KIND_DIFFUSE, KIND_NONE]]).astype(np.int8)
    mass = np.concatenate([mass, [0.25, 0.0]])          # diffuse runoff is weak but everywhere

    return HypothesisGrid(H=len(kind), entry_k=entry_k, t0=t0, duration_s=duration_s,
                          kind=kind, mass=mass, bin_s=bin_s,
                          horizon_start=t_start, horizon_end=t_end)
