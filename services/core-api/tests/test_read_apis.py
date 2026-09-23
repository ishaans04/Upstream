"""Task 6.3: the read APIs (FR-36, FR-37, FR-38, FR-39, GC-12).

Belief replay is the one that has to be exactly right: a slider that quietly shows a
later belief than the moment it names would make every claim about what the system knew
untestable.
"""
from __future__ import annotations

import datetime as dt

import pytest
from conftest import STREAM
from fastapi.testclient import TestClient
from upstream_api.main import app

pytestmark = pytest.mark.integration

client = TestClient(app)


@pytest.fixture(autouse=True)
def _needs_pool(_pool):
    """Routes use the module-level pool; TestClient only runs the lifespan as a CM."""


# --------------------------------------------------------------------------- replay


@pytest.fixture
def three_snapshots(seed_snapshot, _network):
    """Three beliefs, an hour apart, with different p_event."""
    now = dt.datetime.now(dt.UTC)
    entry = _network.entry_nodes[0]
    made = []
    for i, (hours_ago, none_p) in enumerate([(3, 0.9), (2, 0.4), (1, 0.05)]):
        ts = now - dt.timedelta(hours=hours_ago)
        seed_snapshot({"__none__": none_p, entry: 1.0 - none_p}, as_of_seq=i + 1, ts=ts)
        made.append({"ts": ts, "p_event": 1.0 - none_p})
    return made


def test_belief_replay_returns_the_snapshot_as_of_a_past_moment(three_snapshots):
    t_mid = three_snapshots[1]["ts"] + dt.timedelta(minutes=5)
    r = client.get("/replay", params={"at": t_mid.isoformat(), "stream": STREAM})
    assert r.status_code == 200
    assert r.json()["p_event"] == pytest.approx(three_snapshots[1]["p_event"])


def test_belief_replay_never_leaks_a_later_snapshot(three_snapshots):
    t_mid = three_snapshots[1]["ts"] + dt.timedelta(minutes=5)
    r = client.get("/replay", params={"at": t_mid.isoformat(), "stream": STREAM})
    assert dt.datetime.fromisoformat(r.json()["ts"]) <= t_mid


def test_belief_replay_before_any_snapshot_is_a_404_not_the_earliest(three_snapshots):
    """Saying "we believed nothing yet" is right; showing the first belief is a lie."""
    before_all = three_snapshots[0]["ts"] - dt.timedelta(hours=1)
    r = client.get("/replay", params={"at": before_all.isoformat(), "stream": STREAM})
    assert r.status_code == 404


def test_replay_timeline_is_ordered_and_matches_snapshot_count(three_snapshots):
    tl = client.get("/replay/timeline", params={"stream": STREAM}).json()
    assert [x["ts"] for x in tl] == sorted(x["ts"] for x in tl)
    assert len(tl) >= len(three_snapshots)


# --------------------------------------------------------------------------- episodes


def test_episode_list_reports_state_and_probability(an_episode):
    rows = client.get("/episodes", params={"stream": STREAM}).json()
    row = next(r for r in rows if r["episode_id"] == an_episode)
    assert row["state"] == "PROBABLE"
    assert 0.0 <= row["p_event"] <= 1.0


def test_episode_detail_includes_the_computed_explanation(an_episode, seed_snapshot,
                                                          _network):
    entry = _network.entry_nodes[0]
    seed_snapshot({"__none__": 0.1, entry: 0.9}, as_of_seq=10**9,
                  explanation={"candidates": [{"node_id": entry, "p": 0.9,
                                               "supported_by": ["a positive report at J4"]}]})
    d = client.get(f"/episodes/{an_episode}", params={"stream": STREAM}).json()
    assert d["explanation"]["candidates"][0]["supported_by"]


def test_episode_detail_lists_the_evidence_it_was_built_from(an_episode, post_evidence):
    eid = post_evidence("positive")
    d = client.get(f"/episodes/{an_episode}", params={"stream": STREAM}).json()
    assert eid in [e["event_id"] for e in d["evidence"]]


def test_an_unknown_episode_is_a_404(an_episode):
    assert client.get("/episodes/EE-NOPE").status_code == 404


def test_signoff_endpoint_confirms_with_a_positive_result(an_episode, post_evidence,
                                                          episode_row):
    eid = post_evidence("positive")
    r = client.post(f"/episodes/{an_episode}/signoff",
                    json={"officer_id": "off-1", "field_result_event_id": eid})
    assert r.status_code == 200
    assert episode_row(an_episode)["state"] == "CONFIRMED"


def test_signoff_without_a_result_is_rejected_by_the_api(an_episode, episode_row):
    """FR-21 has to hold at the edge, not only in the workflow."""
    r = client.post(f"/episodes/{an_episode}/signoff",
                    json={"officer_id": "off-1", "field_result_event_id": None})
    assert r.status_code == 422
    assert episode_row(an_episode)["state"] == "PROBABLE"


# --------------------------------------------------------------------------- missions


def test_missions_mine_returns_only_this_volunteers_open_missions(an_episode, candidates,
                                                                  a_volunteer):
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    spec = create_missions_from_probe(an_episode, candidates(1))[0]
    mine = client.get("/missions/mine", params={"volunteer_id": "vol-1"}).json()
    assert spec.mission_id in [m["mission_id"] for m in mine]
    assert client.get("/missions/mine",
                      params={"volunteer_id": "vol-someone-else"}).json() == []


def test_accepting_a_mission_through_the_api(an_episode, candidates, a_volunteer,
                                             mission_row):
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    spec = create_missions_from_probe(an_episode, candidates(1))[0]
    r = client.post(f"/missions/{spec.mission_id}/accept", json={"volunteer_id": "vol-1"})
    assert r.status_code == 200
    assert mission_row(spec.mission_id)["status"] == "accepted"


def test_completing_a_mission_through_the_api_returns_the_measured_effect(
        an_episode, candidates, a_volunteer, seed_snapshot, post_evidence, _network):
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    spec = create_missions_from_probe(an_episode, candidates(1))[0]
    client.post(f"/missions/{spec.mission_id}/accept", json={"volunteer_id": "vol-1"})
    entries = _network.entry_nodes[:3]
    seed_snapshot({"__none__": 0.25, **{e: 0.25 for e in entries}}, as_of_seq=1)
    eid = post_evidence("negative", node_id=spec.node_id)
    seed_snapshot({"__none__": 0.05, entries[0]: 0.95}, as_of_seq=10**9)
    r = client.post(f"/missions/{spec.mission_id}/complete", json={"evidence_event_id": eid})
    assert r.status_code == 200
    assert "ruled out" in r.json()["effect"]


def test_accepting_an_expired_mission_through_the_api_is_a_409(an_episode, candidates,
                                                               a_volunteer, fast_clock):
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    spec = create_missions_from_probe(an_episode, candidates(1))[0]
    fast_clock.advance(minutes=90)
    r = client.post(f"/missions/{spec.mission_id}/accept", json={"volunteer_id": "vol-1"})
    assert r.status_code == 409


# --------------------------------------------------------------------------- network


def test_network_geojson_marks_synthetic_outfalls():
    """PRD R2: synthetic elements must be visibly labelled."""
    g = client.get("/network/geojson").json()
    assert any(f["properties"]["is_synthetic"] for f in g["outfalls"]["features"])


def test_network_geojson_carries_nodes_edges_and_zones():
    g = client.get("/network/geojson").json()
    for layer in ("nodes", "edges", "outfalls", "zones"):
        assert g[layer]["type"] == "FeatureCollection"
        assert g[layer]["features"], f"{layer} came back empty"


def test_network_geojson_geometry_is_real_coordinates():
    g = client.get("/network/geojson").json()
    lon, lat = g["nodes"]["features"][0]["geometry"]["coordinates"]
    assert -180 <= lon <= 180 and -90 <= lat <= 90


# --------------------------------------------------------------------------- GC-12


def test_public_health_view_carries_the_not_a_diagnosis_notice(an_episode):
    """GC-12."""
    assert "not a diagnosis" in client.get("/public-health/episodes", params={"stream": STREAM}).text.lower()


def test_public_health_view_names_no_person_and_no_polluter(an_episode, seed_snapshot,
                                                            _network):
    """GC-12: never name a polluter, and no patient-level data leaves the health zone."""
    entry = _network.entry_nodes[0]
    seed_snapshot({"__none__": 0.1, entry: 0.9}, as_of_seq=10**9)
    body = client.get("/public-health/episodes", params={"stream": STREAM}).json()
    for ep in body["episodes"]:
        assert "top_sources" not in ep and "source_marginals" not in ep
        assert set(ep) <= {"episode_id", "state", "opened_at", "clinical_window_end",
                           "zone_windows", "pathways", "notice"}


def test_public_health_view_reports_exposure_windows(an_episode, emit_posterior):
    now = dt.datetime.now(dt.UTC).timestamp()
    emit_posterior(p_event=0.95, zone_windows={
        "ZONE_000": {"zone_id": "ZONE_000", "window_lo": now, "window_hi": now + 9600,
                     "p_peak": 0.99, "pathways": ["recreation"]}})
    body = client.get("/public-health/episodes", params={"stream": STREAM}).json()
    ep = next(e for e in body["episodes"] if e["episode_id"] == an_episode)
    assert ep["zone_windows"]["ZONE_000"]["window_hi"] > ep["zone_windows"]["ZONE_000"][
        "window_lo"]


# ------------------------------------------------------- payload shape of list views


@pytest.fixture
def episode_with_curves(an_episode, emit_posterior, seed_snapshot, _network):
    """An episode whose belief carries PULSE's full exposure curve, as the kernel writes it.

    Both halves are seeded because they live in different places by design: the snapshot
    is the belief record and keeps the samples, while `episodes.summary` keeps only the
    window so the consumer can rewrite it every few seconds cheaply.
    """
    now = dt.datetime.now(dt.UTC).timestamp()
    grid = [now + 300 * i for i in range(432)]
    windows = {"ZONE_000": {"zone_id": "ZONE_000", "window_lo": now, "window_hi": now + 9600,
                            "p_peak": 0.99, "pathways": ["recreation"],
                            "t_grid": grid, "p_exposed": [0.5] * len(grid)}}
    emit_posterior(p_event=0.95, zone_windows=windows)
    seed_snapshot({"__none__": 0.05, _network.entry_nodes[0]: 0.95}, as_of_seq=10**9,
                  zone_windows=windows)
    return an_episode


def test_the_episode_list_summarises_zone_windows_instead_of_shipping_the_curves(
        episode_with_curves):
    """A list view carrying every PULSE time step is megabytes at a hundred episodes."""
    rows = client.get("/episodes", params={"stream": STREAM}).json()
    zw = next(r for r in rows if r["episode_id"] == episode_with_curves)["zone_windows"]
    assert "t_grid" not in zw["ZONE_000"] and "p_exposed" not in zw["ZONE_000"]
    assert zw["ZONE_000"]["window_hi"] > zw["ZONE_000"]["window_lo"]
    assert zw["ZONE_000"]["p_peak"] == pytest.approx(0.99)


def test_the_public_health_view_summarises_zone_windows_too(episode_with_curves):
    body = client.get("/public-health/episodes", params={"stream": STREAM}).json()
    ep = next(e for e in body["episodes"] if e["episode_id"] == episode_with_curves)
    assert "t_grid" not in ep["zone_windows"]["ZONE_000"]
    assert ep["zone_windows"]["ZONE_000"]["window_lo"] is not None


def test_the_episode_detail_still_carries_the_full_curve_for_plotting(episode_with_curves):
    """The console draws the curve, so the single-episode view keeps it."""
    d = client.get(f"/episodes/{episode_with_curves}", params={"stream": STREAM}).json()
    assert len(d["zone_windows"]["ZONE_000"]["t_grid"]) == 432


def test_confirmed_evidence_returns_an_id_that_names_the_stored_event(a_node, db_conn):
    """FR-21 is only reachable from the API if ingestion hands back the event's id.

    The ingest routes returned a sequence number, which sign-off cannot look an event
    up by, so the documented officer workflow could not be performed at all.

    Sign-off itself is exercised on the sim stream in test_read_apis and
    test_episode_workflow; it cannot be driven from this route, because
    /ingest/report/confirm always writes to `live` and the FR-21 gate refuses
    evidence from another stream.
    """
    r = client.post("/ingest/report/confirm", json={
        "node_id": a_node, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "method": "field_test", "result": "positive", "observer_id": "off-1",
        "observer_type": "officer", "snap_distance_m": 0.0, "oah_codes": []})
    assert r.status_code == 201
    body = r.json()
    with db_conn.cursor() as cur:
        cur.execute("SELECT seq, stream, payload->>'result' FROM events WHERE event_id=%s",
                    (body["event_id"],))
        row = cur.fetchone()
    assert row is not None, "the returned event_id does not name a stored event"
    assert row[0] == body["seq"] and row[1] == "live" and row[2] == "positive"
