import datetime as dt
import uuid

import pytest
from upstream_api.routing import assign_missions, geodesic_seconds, walking_time_s

pytestmark = pytest.mark.integration

NOW = dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _needs_pool(_pool):
    """routing.py goes through the module-level connection pool."""


@pytest.fixture
def near_far(_network):
    """Two real network points: one close to the first entry node, one far downstream."""
    i = int(_network.entry_idx[0])
    a = (float(_network.lonlat[i][0]), float(_network.lonlat[i][1]))
    path = _network.downstream_path[i]
    j = int(_network.edges[path[-1]][1]) if len(path) else i
    b = (float(_network.lonlat[j][0]), float(_network.lonlat[j][1]))
    return a, b


@pytest.fixture
def make_volunteer(db_conn):
    made = []

    def _make(lonlat, *, half_width=0.05, available=True):
        vid = f"vol-{uuid.uuid4().hex[:10]}"
        lon, lat = lonlat
        d = half_width
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO volunteers (volunteer_id, display_name, coarse_area,
                                        available_from, available_to, reliability)
                VALUES (%s,%s, ST_SetSRID(ST_MakeEnvelope(%s,%s,%s,%s),4326), %s,%s,0.8)
            """, (vid, "test volunteer", lon - d, lat - d, lon + d, lat + d,
                  NOW - dt.timedelta(hours=2) if available else NOW + dt.timedelta(hours=5),
                  NOW + dt.timedelta(hours=2) if available else NOW + dt.timedelta(hours=8)))
        made.append(vid)
        return {"volunteer_id": vid, "lonlat": lonlat,
                "available_from": NOW - dt.timedelta(hours=2) if available
                else NOW + dt.timedelta(hours=5),
                "available_to": NOW + dt.timedelta(hours=2) if available
                else NOW + dt.timedelta(hours=8)}

    yield _make
    if made:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM volunteers WHERE volunteer_id = ANY(%s)", (made,))


def _cand(cid, lonlat, gain, *, closes_in_s=3600):
    return {"candidate_id": cid, "node_id": cid, "lonlat": lonlat, "ec2_gain": gain,
            "window_start": NOW.timestamp(),
            "window_end": NOW.timestamp() + closes_in_s}


def test_volunteer_is_not_assigned_a_window_they_cannot_reach_in_time(near_far,
                                                                      make_volunteer):
    a, b = near_far
    v = make_volunteer(a)
    # A candidate far away whose window shuts in 30 seconds.
    assert assign_missions([_cand("far", b, 1.0, closes_in_s=30)], [v], now=NOW) == []


def test_higher_gain_candidate_wins_when_a_volunteer_can_only_do_one(near_far,
                                                                     make_volunteer):
    a, _ = near_far
    v = make_volunteer(a)
    low = _cand("low", a, 0.001)
    high = _cand("high", a, 0.900)
    assigned = assign_missions([low, high], [v], now=NOW)
    assert len(assigned) == 1
    assert assigned[0][0] == "high"


def test_each_volunteer_gets_at_most_one_concurrent_mission(near_far, make_volunteer):
    a, _ = near_far
    v = make_volunteer(a)
    assigned = assign_missions([_cand("c1", a, 0.5), _cand("c2", a, 0.4)], [v], now=NOW)
    assert len({vid for _, vid in assigned}) == len(assigned)
    assert len(assigned) == 1


def test_two_volunteers_can_cover_two_candidates(near_far, make_volunteer):
    a, _ = near_far
    v1, v2 = make_volunteer(a), make_volunteer(a)
    assigned = assign_missions([_cand("c1", a, 0.5), _cand("c2", a, 0.4)], [v1, v2],
                               now=NOW)
    assert len(assigned) == 2
    assert len({vid for _, vid in assigned}) == 2


def test_volunteer_outside_their_coarse_area_is_not_offered_the_mission(near_far,
                                                                        make_volunteer):
    a, _ = near_far
    # A tiny area around a point far from the candidate (PRD 14.2).
    v = make_volunteer((a[0] + 5.0, a[1] + 3.0), half_width=0.01)
    assert assign_missions([_cand("c1", a, 1.0)], [v], now=NOW) == []


def test_unavailable_volunteer_is_not_offered_the_mission(near_far, make_volunteer):
    a, _ = near_far
    v = make_volunteer(a, available=False)
    assert assign_missions([_cand("c1", a, 1.0)], [v], now=NOW) == []


def test_pgrouting_walking_time_is_at_least_the_straight_line(near_far):
    """A real path cannot be shorter than the geodesic between its endpoints."""
    a, b = near_far
    assert walking_time_s(a, b) >= geodesic_seconds(a, b) * 0.999


def test_walking_time_falls_back_rather_than_returning_infinity(near_far):
    """A point with no footpath route must still be routable, or it silently vanishes."""
    a, _ = near_far
    unreachable = (a[0] + 40.0, a[1] + 20.0)      # far outside the footpath graph
    t = walking_time_s(a, unreachable)
    assert t > 0 and t != float("inf")
