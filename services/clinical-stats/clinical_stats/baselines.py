"""FR-33: seasonal and day-of-week baselines per area and syndrome.

A negative-binomial GLM in the Noufaily tradition: log-linear trend, annual
harmonics and a day-of-week effect, with the overdispersion estimated from the
data. Days are integers on one absolute scale (`date.toordinal()` in the
service), so the day-of-week term means the same weekday for every fit and every
prediction.

Terms are added only when the history can support them. A seasonal harmonic fitted
to six weeks of data is not a season, it is whatever those six weeks happened to
do, and it would extrapolate that into the test window.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import statsmodels.api as sm

MIN_OBSERVED_DAYS = 28        # four of each weekday: the least a day-of-week effect needs
_DAYS_FOR_TREND = 56
_DAYS_FOR_ONE_HARMONIC = 365
_DAYS_FOR_TWO_HARMONICS = 730
TREND_P_VALUE = 0.05


@dataclass(frozen=True)
class Baseline:
    area_code: str
    syndrome: str
    alpha: float                       # NB2 overdispersion: Var = mu + alpha * mu^2
    coefficients: tuple[float, ...]
    origin: int                        # the day the trend term is measured from
    harmonics: int
    trend: bool
    n_obs: int

    def predict(self, days) -> np.ndarray:
        """Expected count on each day, on the same absolute day scale as the fit."""
        X = _design(np.asarray(days), self.origin, self.harmonics, self.trend)
        return np.exp(X @ np.asarray(self.coefficients))

    def to_row(self) -> dict:
        return {"coefficients": list(self.coefficients), "origin": self.origin,
                "harmonics": self.harmonics, "trend": self.trend}

    @classmethod
    def from_row(cls, area_code: str, syndrome: str, alpha: float, row: dict,
                 n_obs: int) -> Baseline:
        return cls(area_code=area_code, syndrome=syndrome, alpha=float(alpha),
                   coefficients=tuple(row["coefficients"]), origin=int(row["origin"]),
                   harmonics=int(row["harmonics"]), trend=bool(row["trend"]), n_obs=n_obs)


def _design(days: np.ndarray, origin: int, harmonics: int, trend: bool) -> np.ndarray:
    days = days.astype(np.int64)
    columns = [np.ones(len(days), dtype=float)]
    if trend:
        columns.append((days - origin) / 365.25)
    for k in range(1, harmonics + 1):
        angle = 2 * np.pi * k * days / 365.25
        columns += [np.sin(angle), np.cos(angle)]
    weekday = days % 7
    columns += [(weekday == d).astype(float) for d in range(1, 7)]   # level 0 is the base
    return np.column_stack(columns)


def fit_baseline(days, counts, *, area_code: str, syndrome: str) -> Baseline:
    """Fit a baseline to the days that were observed.

    Missing days are left out rather than filled. A day with no row is either a
    count the publisher suppressed or a day it did not report, and neither is zero.
    Leaving them out biases the baseline slightly upward, which makes the tests
    built on it conservative -- the direction to err in when the output is a
    reason to investigate.
    """
    days = np.asarray(days, dtype=np.int64)
    counts = np.asarray(counts, dtype=float)
    keep = ~np.isnan(counts)
    days, counts = days[keep], counts[keep]
    if len(days) < MIN_OBSERVED_DAYS:
        raise ValueError(f"{len(days)} observed days; a baseline needs {MIN_OBSERVED_DAYS}")

    span = int(days.max() - days.min()) + 1
    harmonics = 2 if span >= _DAYS_FOR_TWO_HARMONICS else 1 if span >= _DAYS_FOR_ONE_HARMONIC \
        else 0
    trend = span >= _DAYS_FOR_TREND
    origin = int(days.max())
    X = _design(days, origin, harmonics, trend)

    poisson = sm.GLM(counts, X, family=sm.families.Poisson()).fit()
    mu = poisson.mu
    # Method-of-moments NB2 dispersion. Floored rather than zero: a Poisson baseline
    # would make every test anti-conservative the moment the data are overdispersed.
    alpha = float(max(np.sum((counts - mu) ** 2 - mu) / np.sum(mu ** 2), 1e-3))
    nb = sm.GLM(counts, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
    if trend and nb.pvalues[1] >= TREND_P_VALUE:
        # Farrington's rule, kept by Noufaily: a trend is extrapolated into the test
        # window, so one that is not clearly there is dropped rather than projected.
        # A spurious slope of a few percent a year is enough to bias every test
        # built on this baseline.
        trend = False
        X = _design(days, origin, harmonics, trend)
        nb = sm.GLM(counts, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
    return Baseline(area_code=area_code, syndrome=syndrome, alpha=alpha,
                    coefficients=tuple(float(b) for b in nb.params), origin=origin,
                    harmonics=harmonics, trend=trend, n_obs=int(len(days)))


def simulate(baseline: Baseline, days, rng: np.random.Generator, *, extra=None,
             size: int | None = None) -> np.ndarray:
    """Draw counts from the baseline's NB2 distribution, plus an optional excess.

    Used for Monte Carlo p-values and by the tests; it lives here because it is
    the baseline's own definition of "what an ordinary day looks like".
    """
    mu = baseline.predict(days)
    if extra is not None:
        mu = mu + np.asarray(extra, dtype=float)
    return nb_draw(mu, baseline.alpha, rng, size=size)


def nb_draw(mu, alpha: float, rng: np.random.Generator, *, size: int | None = None):
    mu = np.asarray(mu, dtype=float)
    n = 1.0 / alpha
    p = n / (n + mu)
    shape = mu.shape if size is None else (size, *mu.shape)
    return rng.negative_binomial(n, np.broadcast_to(p, shape)).astype(float)
