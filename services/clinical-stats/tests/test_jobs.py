"""FR-34 and FR-35 end to end, against the clinical database and a stand-in Core API.

What these tests care about most is what *leaves*: every request the service
makes is recorded, and the assertions are about all of them, not only the ones
the test expected to see.
"""
import datetime as dt

import numpy as np
import pytest
from clinical_stats.baselines import Baseline, simulate
from clinical_stats.jobs import run_daily, scan_clusters
from clinical_stats.matched_filter import expected_curve
from conftest import AREA
from upstream_shared.codes import SEWAGE_PATHOGEN_MIX

pytestmark = pytest.mark.integration

TODAY = dt.date(2026, 9, 20)
EXPOSURE_DAY = TODAY - dt.timedelta(days=12)
SYNDROME = "acute_gastroenteritis"
RESULT_FIELDS = {"episode_id", "area_code", "syndrome", "method", "p_value", "effect_size",
                 "n_days", "computed_at"}
SEARCH_FIELDS = {"area_code", "syndrome", "day", "p_value", "method"}

# Twelve a day and a quieter weekend, so nearly every day clears the suppression threshold.
TRUTH = Baseline(area_code=AREA, syndrome=SYNDROME, alpha=0.03,
                 coefficients=(np.log(12.0), 0, 0, 0, 0, -0.2, -0.3), origin=0, harmonics=0,
                 trend=False, n_obs=0)


def _zone(area: str, *, pathways=("recreation",), population=3000) -> dict:
    start = dt.datetime.combine(EXPOSURE_DAY, dt.time(8), dt.UTC).timestamp()
    return {"area_code": area, "population": population,
            "t_grid": list(np.arange(start, start + 6 * 3600, 300.0)),
            "p_exposed": [0.5] * 72, "window_lo": start, "window_hi": start + 6 * 3600,
            "pathways": list(pathways)}


def _episode(*zones: dict, episode_id="EE-test") -> dict:
    return {"episode_id": episode_id, "state": "PROBABLE",
            "opened_at": dt.datetime.combine(EXPOSURE_DAY, dt.time(9), dt.UTC).isoformat(),
            "clinical_window_end": (TODAY + dt.timedelta(days=4)).isoformat(),
            "zones": {f"Z{i}": z for i, z in enumerate(zones)}}


def _seed(conn, area: str, first: dt.date, last: dt.date, *, extra=None, seed=0) -> None:
    """Counts as the ingest route would have stored them: below five, not at all."""
    days = np.arange(first.toordinal(), last.toordinal() + 1)
    counts = simulate(TRUTH, days, np.random.default_rng(seed), extra=extra)
    rows = [(dt.date.fromordinal(int(d)), area, SYNDROME, int(c), "test")
            for d, c in zip(days, counts, strict=False) if c >= 5]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO syndromic_counts (day, area_code, syndrome, count, source) "
                        "VALUES (%s, %s, %s, %s, %s)", rows)


def _seed_history(conn, area: str, *, seed=0) -> None:
    _seed(conn, area, EXPOSURE_DAY - dt.timedelta(days=400),
          EXPOSURE_DAY - dt.timedelta(days=1), seed=seed)


def _predicted_excess(zone: dict, n_days: int) -> np.ndarray:
    return expected_curve(zone, SEWAGE_PATHOGEN_MIX, days=np.arange(n_days))


@pytest.fixture
def outbreak(clinical_conn, clinical_counts, core_api):
    """An episode whose predicted excess really happened."""
    zone = _zone(AREA)
    _seed_history(clinical_conn, AREA)
    window = (TODAY - EXPOSURE_DAY).days + 1
    _seed(clinical_conn, AREA, EXPOSURE_DAY, TODAY, extra=_predicted_excess(zone, window), seed=1)
    core_api.episodes = [_episode(zone)]
    return core_api


# --- FR-34 -------------------------------------------------------------------


def test_the_daily_job_finds_the_excess_the_episode_predicted(outbreak):
    summary = run_daily(today=TODAY)
    assert summary["published"] == 1
    (result,) = outbreak.posted("/clinical/test-result")
    assert result["episode_id"] == "EE-test" and result["area_code"] == AREA
    assert result["p_value"] < 0.01 and result["effect_size"] > 0


def test_only_test_results_leave_the_service(outbreak):
    """GC-7. Every POST the service made, to anywhere, is a test result and only that."""
    run_daily(today=TODAY)
    posts = [c for c in outbreak.calls if c.method == "POST"]
    assert posts, "the job published nothing, so this test would pass vacuously"
    assert {c.path for c in posts} == {"/clinical/test-result"}
    for body in outbreak.posted("/clinical/test-result"):
        assert set(body) == RESULT_FIELDS
        assert not any("count" in key for key in body)


def test_no_count_crosses_even_as_a_number_it_could_be_read_back_from(outbreak, clinical_conn):
    """n_days is how many days were tested, never how many people presented."""
    run_daily(today=TODAY)
    (result,) = outbreak.posted("/clinical/test-result")
    with clinical_conn.cursor() as cur:
        cur.execute("SELECT count(*), sum(count) FROM syndromic_counts WHERE area_code=%s "
                    "AND day >= %s", (AREA, EXPOSURE_DAY))
        stored_days, stored_total = cur.fetchone()
    assert result["n_days"] == stored_days
    assert stored_total not in result.values()


def test_a_published_result_is_kept_and_marked_published(outbreak, clinical_conn):
    run_daily(today=TODAY)
    with clinical_conn.cursor() as cur:
        cur.execute("SELECT method, p_value, published_at FROM test_results WHERE area_code=%s",
                    (AREA,))
        rows = cur.fetchall()
    assert len(rows) == 1 and rows[0][2] is not None


def test_no_excess_is_published_as_no_excess(clinical_conn, clinical_counts, core_api):
    """A quiet area still gets its result: "we looked, and nothing matched" is an answer."""
    _seed_history(clinical_conn, AREA)
    _seed(clinical_conn, AREA, EXPOSURE_DAY, TODAY, seed=2)
    core_api.episodes = [_episode(_zone(AREA))]
    run_daily(today=TODAY)
    (result,) = core_api.posted("/clinical/test-result")
    assert result["p_value"] > 0.01


def test_a_floodwater_syndrome_is_not_tested_where_there_is_no_floodwater(outbreak):
    run_daily(today=TODAY)
    syndromes = {r["syndrome"] for r in outbreak.posted("/clinical/test-result")}
    assert syndromes == {SYNDROME}


def test_an_area_with_no_history_is_skipped_not_guessed(clinical_conn, clinical_counts,
                                                        core_api):
    """Without a baseline there is no "excess", so there is no result to publish."""
    _seed(clinical_conn, AREA, EXPOSURE_DAY, TODAY, seed=3)
    core_api.episodes = [_episode(_zone(AREA))]
    assert run_daily(today=TODAY)["published"] == 0
    assert core_api.posted("/clinical/test-result") == []


def test_an_area_with_no_counts_in_the_window_is_skipped(clinical_conn, clinical_counts,
                                                         core_api):
    _seed_history(clinical_conn, AREA)
    core_api.episodes = [_episode(_zone(AREA))]
    assert run_daily(today=TODAY)["published"] == 0


# --- FR-35 -------------------------------------------------------------------


def _sharp_cluster(conn, area: str, seed: int) -> None:
    first = TODAY - dt.timedelta(days=13)
    extra = np.zeros(14)
    extra[9:12] = 25.0
    _seed(conn, area, first - dt.timedelta(days=400), first - dt.timedelta(days=1), seed=seed)
    _seed(conn, area, first, TODAY, extra=extra, seed=seed + 1)


def test_an_unexplained_cluster_asks_for_an_upstream_search(clinical_conn, clinical_counts,
                                                           core_api):
    _sharp_cluster(clinical_conn, AREA, seed=10)
    summary = scan_clusters(today=TODAY)
    assert summary["requested"] >= 1
    requests = [r for r in core_api.posted("/clinical/upstream-search") if r["area_code"] == AREA]
    assert len(requests) == 1
    assert set(requests[0]) == SEARCH_FIELDS
    assert requests[0]["p_value"] < 0.01


def test_a_cluster_an_episode_already_explains_asks_for_nothing(clinical_conn, clinical_counts,
                                                                core_api):
    """The episode is the explanation; searching upstream for it again would be noise."""
    _sharp_cluster(clinical_conn, AREA, seed=10)
    core_api.episodes = [_episode(_zone(AREA))]
    scan_clusters(today=TODAY)
    assert [r for r in core_api.posted("/clinical/upstream-search")
            if r["area_code"] == AREA] == []


def test_a_quiet_area_asks_for_nothing(clinical_conn, clinical_counts, core_api):
    _seed(clinical_conn, AREA, TODAY - dt.timedelta(days=420), TODAY, seed=20)
    scan_clusters(today=TODAY)
    assert [r for r in core_api.posted("/clinical/upstream-search")
            if r["area_code"] == AREA] == []


# --- GC-10 -------------------------------------------------------------------


def test_simulated_counts_never_reach_a_live_test(outbreak, clinical_conn):
    """The simulator files counts for the same areas; the stream keeps them apart."""
    with clinical_conn.cursor() as cur:
        cur.execute("UPDATE syndromic_counts SET stream='sim' WHERE area_code=%s", (AREA,))
    assert run_daily(today=TODAY, stream="live")["published"] == 0
    assert run_daily(today=TODAY, stream="sim")["published"] == 1
