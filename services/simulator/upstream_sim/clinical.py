"""Synthetic syndrome counts: a seasonal baseline plus the cases an episode caused.

Nothing here reuses the clinical service's code. Its matched filter predicts a
case curve by convolving an exposure curve with incubation densities; the
simulator instead makes people ill one at a time -- when each was exposed, which
pathogen, how long it incubated, how long they waited before presenting -- and
counts them. If the two agree, it is because the method works, not because both
sides ran the same function.

The counts belong to a health area, which is larger than the exposure zone: the
people who swim at one spot are a small part of the population whose GI
presentations a surgery sees. So the baseline is the area's and the excess comes
from the zone's population.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
from upstream_shared.ids import zone_group_id

SUPPRESSION_THRESHOLD = 5

# Among people who had contact with the water while it was contaminated. Reported
# attack rates for recreational exposure to sewage-contaminated water run from a
# few percent to over twenty; ten is a middle value, not a flattering one.
ATTACK_RATE = 0.10
# The share of a zone's population that has water contact per hour of exposure,
# capped at half: most people never touch the stream at all.
CONTACT_PER_HOUR = 0.04
MAX_CONTACT = 0.5

# The world's incubation periods (PRD 7.6), as lognormal (median days, log sd),
# fitted to the ranges in the PRD table rather than to the clinical service's gammas.
INCUBATION = {
    "norovirus":       (1.2, 0.35),
    "campylobacter":   (3.0, 0.35),
    "stec":            (3.5, 0.40),
    "cryptosporidium": (7.0, 0.30),
    "giardia":         (10.0, 0.30),
    "leptospira":      (9.0, 0.45),
}
PATHOGEN_MIX = {"acute_gastroenteritis": {"norovirus": 0.4, "campylobacter": 0.25, "stec": 0.1,
                                          "cryptosporidium": 0.15, "giardia": 0.1}}
PRESENTATION_DELAY = (1.2, 0.6)        # lognormal (median days, log sd)

AREA_BASELINE_PER_DAY = 9.0
WEEKEND_FACTOR = 0.75                  # surgeries see fewer walk-ins at the weekend
SEASONAL_AMPLITUDE = 0.2               # winter norovirus season
DISPERSION = 0.04                      # NB2 alpha


def baseline_mean(days: np.ndarray) -> np.ndarray:
    """Expected presentations per day for an area, on the `date.toordinal()` scale."""
    days = np.asarray(days)
    weekday = (days - 1) % 7                        # ordinal 1 is a Monday
    season = 1 + SEASONAL_AMPLITUDE * np.cos(2 * np.pi * (days % 365.25) / 365.25)
    return AREA_BASELINE_PER_DAY * season * np.where(weekday >= 5, WEEKEND_FACTOR, 1.0)


def excess_cases(exposure: tuple[float, float] | None, population: int,
                 rng: np.random.Generator, *, syndrome: str = "acute_gastroenteritis",
                 n_cases: int | None = None) -> list[dt.date]:
    """The day each extra person presented, for one zone's true exposure interval.

    `n_cases` fixes the outbreak's size instead of deriving it from the zone's
    population, for evaluating detection at a size where detection is possible.
    """
    if exposure is None:
        return []
    first, last = exposure
    hours = max(last - first, 60.0) / 3600.0
    contact = min(MAX_CONTACT, CONTACT_PER_HOUR * hours)
    n = int(rng.poisson(ATTACK_RATE * contact * population)) if n_cases is None else n_cases
    mix = PATHOGEN_MIX[syndrome]
    names = list(mix)
    probs = np.array([mix[k] for k in names])
    out = []
    for _ in range(n):
        exposed = rng.uniform(first, last)
        median, sd = INCUBATION[names[int(rng.choice(len(names), p=probs / probs.sum()))]]
        onset = exposed + rng.lognormal(np.log(median), sd) * 86400
        presented = onset + rng.lognormal(np.log(PRESENTATION_DELAY[0]), PRESENTATION_DELAY[1]) \
            * 86400
        out.append(dt.datetime.fromtimestamp(presented, dt.UTC).date())
    return out


def area_counts(first: dt.date, last: dt.date, rng: np.random.Generator, *,
                excess: list[dt.date] = ()) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(days, baseline draws, excess) for every day from first to last."""
    days = np.arange(first.toordinal(), last.toordinal() + 1)
    mu = baseline_mean(days)
    n = 1 / DISPERSION
    base = rng.negative_binomial(n, n / (n + mu)).astype(int)
    extra = np.zeros(len(days), dtype=int)
    for d in excess:
        i = d.toordinal() - first.toordinal()
        if 0 <= i < len(days):
            extra[i] += 1
    return days, base, extra


def measure_report(zone_id: str, day: dt.date, count: int, *,
                   syndrome: str = "acute_gastroenteritis") -> dict:
    """What a health system would send for one area and day (FR-32).

    A small count is sent without a score, as the publisher's own suppression
    would; the clinical service would refuse to store it anyway.
    """
    group = {"code": {"coding": [{"system": "https://upstream-onehealth.example/CodeSystem/"
                                            "syndrome", "code": syndrome}]}}
    if count >= SUPPRESSION_THRESHOLD:
        group["measureScore"] = {"value": int(count), "unit": "presentations",
                                 "system": "http://unitsofmeasure.org", "code": "1"}
    return {"resourceType": "MeasureReport", "status": "complete", "type": "summary",
            "measure": "https://upstream-onehealth.example/Measure/gi-presentations-by-area-day",
            "subject": {"reference": f"Group/{zone_group_id(zone_id)}"},
            "period": {"start": day.isoformat(), "end": day.isoformat()},
            "group": [group]}


def zone_measure_reports(zone_id: str, population: int, exposure, first: dt.date,
                         last: dt.date, rng: np.random.Generator) -> tuple[list[dict], dict]:
    """Every daily report for one zone's area, and the truth behind them."""
    excess = excess_cases(exposure, population, rng)
    days, base, extra = area_counts(first, last, rng, excess=excess)
    reports = [measure_report(zone_id, dt.date.fromordinal(int(d)), int(b + e))
               for d, b, e in zip(days, base, extra, strict=True)]
    truth = {"zone_id": zone_id, "area_code": zone_group_id(zone_id),
             "excess_total": int(extra.sum()),
             "excess_by_day": {dt.date.fromordinal(int(d)).isoformat(): int(e)
                               for d, e in zip(days, extra, strict=True) if e}}
    return reports, truth
