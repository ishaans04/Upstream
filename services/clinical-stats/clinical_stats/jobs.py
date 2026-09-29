"""FR-34 and FR-35: the two jobs the health zone runs.

`run_daily` tests every active episode's predicted case curve against the counts
for its zones and publishes the result -- the result only. `scan_clusters` looks
for excesses no episode predicted and asks the environmental side to search
upstream of them.

Days are UTC calendar days throughout, on the `date.toordinal()` scale, which is
the scale the baselines are fitted on.
"""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np
from psycopg.types.json import Jsonb
from upstream_shared.codes import FLOODWATER_PATHOGEN_MIX, SEWAGE_PATHOGEN_MIX, SYNDROME_SET

from . import episode_client
from .baselines import MIN_OBSERVED_DAYS, Baseline, fit_baseline
from .cluster import METHOD as SCAN_METHOD
from .cluster import blind_scan
from .db import conn
from .matched_filter import TestResult, expected_curve, matched_filter_test

log = logging.getLogger(__name__)

BASELINE_HISTORY_DAYS = 730
CLUSTER_LOOKBACK_DAYS = 14
CLUSTER_ALPHA = 0.01

# Which pathogens a syndrome can be. The mix sets the shape of the predicted case
# curve; it is chosen by the syndrome, not by the suspected source, so nothing on
# this side needs to know what the environmental side suspects (GC-12).
SYNDROME_MIX = {
    "acute_gastroenteritis": SEWAGE_PATHOGEN_MIX,
    "fever_after_floodwater_contact": FLOODWATER_PATHOGEN_MIX,
}
# A syndrome that can only follow one pathway is not tested in a zone without it.
SYNDROME_NEEDS_PATHWAY = {"fever_after_floodwater_contact": "floodwater"}


def run_daily(*, stream: str = "live", today: dt.date | None = None) -> dict:
    today = today or dt.datetime.now(dt.UTC).date()
    published = skipped = 0
    for episode in episode_client.active_episodes(stream):
        for zone in episode["zones"].values():
            for syndrome in _syndromes_for(zone):
                result = test_episode_zone(episode, zone, syndrome, today=today)
                if result is None:
                    skipped += 1
                    continue
                result_id = _store(result)
                episode_client.post_test_result(result, stream)
                _mark_published(result_id)
                published += 1
    return {"published": published, "skipped": skipped}


def test_episode_zone(episode: dict, zone: dict, syndrome: str, *,
                      today: dt.date) -> TestResult | None:
    """The matched-filter test for one episode, zone and syndrome, or None if untestable."""
    first = _utc_day(min(zone["t_grid"]))
    end = episode.get("clinical_window_end")
    last = min(today, _as_date(end)) if end else today
    if last < first:
        return None
    area = zone["area_code"]
    days, counts = _counts(area, syndrome, first, last)
    if np.all(np.isnan(counts)):
        return None                     # nothing reported for this area in the window
    baseline = baseline_for(area, syndrome, before=first)
    if baseline is None:
        return None
    exposure = {"t_grid": zone["t_grid"], "p_exposed": zone["p_exposed"],
                "population": zone.get("population")}
    shape = expected_curve(exposure, SYNDROME_MIX[syndrome], days=np.arange(len(days)))
    return matched_filter_test(counts, baseline, shape, days=days,
                               episode_id=episode["episode_id"], area_code=area,
                               syndrome=syndrome)


def scan_clusters(*, stream: str = "live", today: dt.date | None = None) -> dict:
    """FR-35: excesses in areas no active episode explains -> ask for an upstream search."""
    today = today or dt.datetime.now(dt.UTC).date()
    first = today - dt.timedelta(days=CLUSTER_LOOKBACK_DAYS - 1)
    explained = {z["area_code"] for ep in episode_client.active_episodes(stream)
                 for z in ep["zones"].values()}
    with conn() as c, c.cursor() as cur:
        cur.execute("SELECT DISTINCT area_code, syndrome FROM syndromic_counts "
                    "WHERE day BETWEEN %s AND %s ORDER BY 1, 2", (first, today))
        series = cur.fetchall()

    found = []
    for area, syndrome in series:
        baseline = baseline_for(area, syndrome, before=first)
        if baseline is None:
            continue
        days, counts = _counts(area, syndrome, first, today)
        cluster = blind_scan(counts, baseline, days=days, area_code=area, syndrome=syndrome)
        # Bonferroni over every series scanned: the service looked in all of them.
        p_adjusted = min(1.0, cluster.p_value * len(series))
        if p_adjusted < CLUSTER_ALPHA and area not in explained:
            found.append((cluster, p_adjusted))

    for cluster, p_adjusted in found:
        episode_client.request_upstream_search(
            area_code=cluster.area_code, syndrome=cluster.syndrome,
            day=dt.date.fromordinal(cluster.end_day), p_value=p_adjusted,
            method=SCAN_METHOD, stream=stream)
    return {"scanned": len(series), "requested": len(found)}


def baseline_for(area: str, syndrome: str, *, before: dt.date) -> Baseline | None:
    """Fit on the history before `before`, store it, return it. None if too little history.

    The history stops the day before the window being tested. A baseline fitted on
    the window would learn the excess as normal and hide it.
    """
    start = before - dt.timedelta(days=BASELINE_HISTORY_DAYS)
    days, counts = _counts(area, syndrome, start, before - dt.timedelta(days=1))
    if np.count_nonzero(~np.isnan(counts)) < MIN_OBSERVED_DAYS:
        return None
    baseline = fit_baseline(days, counts, area_code=area, syndrome=syndrome)
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO baselines (area_code, syndrome, fitted_at, alpha, coefficients, n_obs) "
            "VALUES (%s, %s, now(), %s, %s, %s) ON CONFLICT (area_code, syndrome) DO UPDATE "
            "SET fitted_at = now(), alpha = EXCLUDED.alpha, "
            "coefficients = EXCLUDED.coefficients, n_obs = EXCLUDED.n_obs",
            (area, syndrome, baseline.alpha, Jsonb(baseline.to_row()), baseline.n_obs))
    return baseline


def _syndromes_for(zone: dict) -> list[str]:
    pathways = set(zone.get("pathways") or [])
    return [s for s in SYNDROME_SET if s in SYNDROME_MIX
            and (s not in SYNDROME_NEEDS_PATHWAY or SYNDROME_NEEDS_PATHWAY[s] in pathways)]


def _counts(area: str, syndrome: str, first: dt.date, last: dt.date):
    """Every day from first to last, with NaN where no count was stored."""
    days = np.arange(first.toordinal(), last.toordinal() + 1, dtype=np.int64)
    counts = np.full(len(days), np.nan)
    with conn() as c, c.cursor() as cur:
        cur.execute("SELECT day, count FROM syndromic_counts WHERE area_code=%s "
                    "AND syndrome=%s AND day BETWEEN %s AND %s", (area, syndrome, first, last))
        for day, count in cur.fetchall():
            counts[day.toordinal() - first.toordinal()] = count
    return days, counts


def _store(r: TestResult) -> int:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO test_results (episode_id, area_code, syndrome, method, p_value, "
            "effect_size, n_days, computed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING result_id",
            (r.episode_id, r.area_code, r.syndrome, r.method, r.p_value, r.effect_size,
             r.n_days, r.computed_at))
        return cur.fetchone()[0]


def _mark_published(result_id: int) -> None:
    with conn() as c, c.cursor() as cur:
        cur.execute("UPDATE test_results SET published_at = now() WHERE result_id=%s",
                    (result_id,))


def _utc_day(epoch_s: float) -> dt.date:
    return dt.datetime.fromtimestamp(float(epoch_s), dt.UTC).date()


def _as_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).date()
    if isinstance(value, dt.date):
        return value
    return dt.datetime.fromisoformat(str(value)).astimezone(dt.UTC).date()
