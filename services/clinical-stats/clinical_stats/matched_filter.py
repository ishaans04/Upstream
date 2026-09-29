"""PRD 7.6: look for the SHAPE the case curve should have, not for any cluster.

The expected shape is the zone's exposure curve, blurred by the incubation period
of each pathogen class plausible for the syndrome and then by the delay between
falling ill and presenting to care. Testing for that specific shape above a
negative-binomial baseline is far more sensitive than a blind scan -- like
listening for a known voice in a noisy room.

The test is the matched filter in its textbook form: the efficient score for an
additive excess `beta * shape` on top of the baseline, each day weighted by the
shape over that day's NB variance. Its reference distribution comes from the
baseline itself by parametric bootstrap, not from a normal approximation, because
the counts it runs on are small and skewed and a normal tail would call too much
significant. The bootstrap is seeded, so the same counts give the same p-value
(GC-6).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import gamma
from upstream_shared.codes import INCUBATION_DAYS, PathogenClass

from .baselines import Baseline, nb_draw

METHOD = "matched-filter-nb-score"

# Onset to presentation. Case counts are presentations, not onsets, and people
# rarely present on the day they fall ill; ignoring this puts the predicted peak a
# day or two early and the filter listens at the wrong moment. Gamma, mean and sd
# in days -- a pilot would refit it from its own syndromic feed.
PRESENTATION_DELAY_DAYS = (1.5, 1.0)

_STEP_DAYS = 1.0 / 24.0           # the convolution runs hourly, then bins into days
_SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class TestResult:
    __test__ = False               # a result type, not a pytest class

    episode_id: str
    area_code: str
    syndrome: str
    method: str
    p_value: float
    effect_size: float
    n_days: int
    computed_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def to_wire(self) -> dict:
        """Everything that leaves the health zone about a test, and nothing else (GC-7)."""
        return {"episode_id": self.episode_id, "area_code": self.area_code,
                "syndrome": self.syndrome, "method": self.method,
                "p_value": self.p_value, "effect_size": self.effect_size,
                "n_days": self.n_days, "computed_at": self.computed_at.isoformat()}


def _gamma_pdf(mean_sd: tuple[float, float], t: np.ndarray) -> np.ndarray:
    mean, sd = mean_sd
    return gamma.pdf(t, a=(mean / sd) ** 2, scale=sd ** 2 / mean)


def delay_kernel(pathogen_mix: dict[PathogenClass, float], horizon_days: float) -> np.ndarray:
    """Exposure-to-presentation delay on the hourly grid, as probability per step."""
    t = np.arange(0.0, horizon_days, _STEP_DAYS)
    total = sum(pathogen_mix.values())
    incubation = sum(w / total * _gamma_pdf(INCUBATION_DAYS[pc], t)
                     for pc, w in pathogen_mix.items())
    presentation = _gamma_pdf(PRESENTATION_DELAY_DAYS, t)
    k = np.convolve(incubation, presentation)[: len(t)] * _STEP_DAYS
    return k / max(k.sum(), 1e-12)


def expected_curve(zone_exposure: dict, pathogen_mix: dict[PathogenClass, float],
                   days, *, attack_rate: float = 0.02) -> np.ndarray:
    """Expected excess presentations on each day, if the episode made people ill.

    `days` are whole days counted from the calendar day (UTC) on which the exposure
    curve begins. The curve is `attack_rate * population` in total over an unlimited
    horizon; any part of it that falls after the last requested day is simply not
    returned, so a short window sums to less.
    """
    days = np.asarray(days, dtype=int)
    t = np.asarray(zone_exposure["t_grid"], dtype=float) / _SECONDS_PER_DAY
    p = np.clip(np.asarray(zone_exposure["p_exposed"], dtype=float), 0.0, None)
    day0 = np.floor(t.min())
    n_days = int(days.max()) + 1 if len(days) else 0
    if n_days == 0 or p.sum() <= 0:
        return np.zeros(len(days))

    steps = int(round(n_days / _STEP_DAYS))
    exposure = np.zeros(steps)
    idx = np.floor((t - day0) / _STEP_DAYS).astype(int)
    inside = (idx >= 0) & (idx < steps)
    np.add.at(exposure, idx[inside], p[inside])
    # Normalised against the whole curve, not the part inside the window: exposure
    # the window cannot see still happened.
    exposure /= p.sum()

    presentations = np.convolve(exposure, delay_kernel(pathogen_mix, n_days))[:steps]
    per_day = presentations.reshape(n_days, -1).sum(axis=1)
    population = float(zone_exposure.get("population") or 1000)
    return per_day[days] * attack_rate * population


def score_statistic(counts: np.ndarray, mu0: np.ndarray, alpha: float,
                    shape: np.ndarray) -> tuple[np.ndarray, float]:
    """Standardised efficient score for an excess of the given shape.

    `counts` may be a batch (rows are replicates). Returns (z, information).
    """
    variance = mu0 + alpha * mu0 ** 2
    information = float(np.sum(shape ** 2 / variance))
    if information <= 0:
        return np.zeros(np.shape(counts)[:-1]), 0.0
    score = np.sum(shape * (counts - mu0) / variance, axis=-1)
    return score / np.sqrt(information), information


def matched_filter_test(counts, baseline: Baseline, shape, *, episode_id: str,
                        area_code: str, syndrome: str, days=None, n_sim: int = 4999,
                        seed: int = 0) -> TestResult:
    """One-sided test for an excess with the predicted shape above the baseline.

    `days` are the absolute day numbers of `counts` on the baseline's scale; by
    default 0..n-1. Days with no count (NaN: suppressed or unreported) drop out of
    the test rather than being read as zero.

    `effect_size` is the estimated excess as a multiple of the predicted one: 1.0
    means "about as many extra presentations as the episode predicts", 0 means none.
    The p-value answers exactly the question a public-health officer asks -- is
    there an excess shaped like this episode? -- and nothing more (GC-12).
    """
    counts = np.asarray(counts, dtype=float)
    n = len(counts)
    days = np.arange(n) if days is None else np.asarray(days, dtype=np.int64)
    shape = np.asarray(shape, dtype=float)[:n]
    keep = ~np.isnan(counts)
    counts, days, shape = counts[keep], days[keep], shape[keep]

    def result(p_value: float, effect: float) -> TestResult:
        return TestResult(episode_id=episode_id, area_code=area_code, syndrome=syndrome,
                          method=METHOD, p_value=float(p_value), effect_size=float(effect),
                          n_days=int(keep.sum()))

    if len(counts) == 0 or not np.any(shape > 0):
        return result(1.0, 0.0)      # nothing observed where the shape says to look

    mu0 = np.maximum(baseline.predict(days), 1e-6)
    z, information = score_statistic(counts, mu0, baseline.alpha, shape)
    rng = np.random.default_rng(seed)
    null = nb_draw(mu0, baseline.alpha, rng, size=n_sim)
    z_null, _ = score_statistic(null, mu0, baseline.alpha, shape)
    p_value = (1 + np.count_nonzero(z_null >= z)) / (n_sim + 1)
    effect = float(z) / np.sqrt(information)     # score / information = beta-hat
    return result(p_value, effect)
