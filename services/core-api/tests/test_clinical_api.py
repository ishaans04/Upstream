"""The environmental side of the health boundary (FR-34, FR-35, GC-7, GC-12).

The clinical service reads exposure curves and writes back results. These tests
pin what each direction may carry: no candidate source going out, no count
coming in -- the latter refused outright rather than silently dropped.
"""
from __future__ import annotations

import datetime as dt

import pytest
from conftest import STREAM
from fastapi.testclient import TestClient
from upstream_api.fhir.mapper import zone_group_id
from upstream_api.main import app

pytestmark = pytest.mark.integration

client = TestClient(app)


@pytest.fixture(autouse=True)
def _needs_pool(_pool):
    """Routes use the module-level pool; TestClient only runs the lifespan as a CM."""


@pytest.fixture
def curved_episode(an_episode, emit_posterior, seed_snapshot, _network):
    zone_id = _network.zone_ids[0]
    now = dt.datetime.now(dt.UTC).timestamp()
    grid = [now + 300 * i for i in range(48)]
    windows = {zone_id: {"zone_id": zone_id, "window_lo": now, "window_hi": now + 3600,
                         "p_peak": 0.9, "pathways": ["recreation"],
                         "t_grid": grid, "p_exposed": [0.4] * len(grid)}}
    emit_posterior(p_event=0.95, zone_windows=windows)
    seed_snapshot({"__none__": 0.05, _network.entry_nodes[0]: 0.95}, as_of_seq=10**9,
                  zone_windows=windows)
    return an_episode, zone_id


def _result(episode_id: str, **over) -> dict:
    body = {"episode_id": episode_id, "area_code": "zone-000-population",
            "syndrome": "acute_gastroenteritis", "method": "matched-filter-nb-score",
            "p_value": 0.003, "effect_size": 1.1, "n_days": 12,
            "computed_at": dt.datetime.now(dt.UTC).isoformat()}
    body.update(over)
    return body


# --- What goes out to the health zone ----------------------------------------


def test_the_clinical_feed_lists_active_episodes_with_their_curves(curved_episode):
    episode_id, zone_id = curved_episode
    body = client.get("/clinical/episodes", params={"stream": STREAM}).json()
    ep = next(e for e in body["episodes"] if e["episode_id"] == episode_id)
    zone = ep["zones"][zone_id]
    assert zone["area_code"] == zone_group_id(zone_id)
    assert len(zone["t_grid"]) == len(zone["p_exposed"]) == 48
    assert zone["population"] is not None


def test_the_clinical_feed_names_no_source(curved_episode):
    """GC-12: the health zone tests a curve; it has no need to know what is suspected."""
    episode_id, _ = curved_episode
    body = client.get("/clinical/episodes", params={"stream": STREAM}).json()
    ep = next(e for e in body["episodes"] if e["episode_id"] == episode_id)
    text = str(ep)
    for forbidden in ("top_sources", "source_marginals", "probe_candidates", "evidence",
                      "explanation", "outfall"):
        assert forbidden not in text


def test_a_suspected_episode_is_not_in_the_clinical_feed(emit_posterior, episode_row):
    """One unconfirmed report is not a reason to test hospital data."""
    emit_posterior(p_event=0.6)
    episode_id = episode_row()["episode_id"]
    body = client.get("/clinical/episodes", params={"stream": STREAM}).json()
    assert episode_id not in {e["episode_id"] for e in body["episodes"]}


# --- What comes back ---------------------------------------------------------


def test_a_test_result_is_appended_as_a_clinical_test_result_event(curved_episode,
                                                                   events_since):
    episode_id, _ = curved_episode
    response = client.post("/clinical/test-result", params={"stream": STREAM},
                           json=_result(episode_id))
    assert response.status_code == 201
    (event,) = events_since("ClinicalTestResult")
    assert event["episode_id"] == episode_id
    assert event["p_value"] == pytest.approx(0.003)


def test_the_logged_result_carries_no_count(curved_episode, events_since):
    """Phase 8 exit criterion: ClinicalTestResult events carry no counts."""
    episode_id, _ = curved_episode
    client.post("/clinical/test-result", params={"stream": STREAM}, json=_result(episode_id))
    (event,) = events_since("ClinicalTestResult")
    assert set(event) == {"episode_id", "area_code", "syndrome", "method",
                                     "p_value", "effect_size", "n_days", "computed_at"}


@pytest.mark.parametrize("smuggled", [{"count": 7}, {"counts": [5, 9, 12]},
                                      {"observed": 31}, {"patient_id": "123"}])
def test_a_result_carrying_anything_else_is_refused_not_trimmed(curved_episode, count_events,
                                                               smuggled):
    """A caller who sends a count learns it was refused; nothing reaches the log."""
    episode_id, _ = curved_episode
    before = count_events()
    response = client.post("/clinical/test-result", params={"stream": STREAM},
                           json=_result(episode_id, **smuggled))
    assert response.status_code == 422
    assert count_events() == before


def test_a_result_for_an_unknown_episode_is_a_404(curved_episode):
    response = client.post("/clinical/test-result", params={"stream": STREAM},
                           json=_result("EE-no-such-episode"))
    assert response.status_code == 404


def test_an_impossible_p_value_is_refused(curved_episode):
    episode_id, _ = curved_episode
    response = client.post("/clinical/test-result", params={"stream": STREAM},
                           json=_result(episode_id, p_value=1.5))
    assert response.status_code == 422


def test_an_upstream_search_request_names_where_to_search_from(_network, events_since,
                                                               seq0):
    zone_id = _network.zone_ids[0]
    response = client.post("/clinical/upstream-search", params={"stream": STREAM}, json={
        "area_code": zone_group_id(zone_id), "syndrome": "acute_gastroenteritis",
        "day": "2026-09-20", "p_value": 0.004, "method": "blind-temporal-scan-nb"})
    assert response.status_code == 201
    (event,) = events_since("UpstreamSearchRequested")
    assert event["zone_id"] == zone_id
    node = _network.node_ids[int(_network.zone_node_idx[0])]
    assert event["search_from_node"] == node


def test_an_upstream_search_for_an_unknown_area_is_refused(count_events):
    before = count_events()
    response = client.post("/clinical/upstream-search", params={"stream": STREAM}, json={
        "area_code": "nowhere-population", "syndrome": "acute_gastroenteritis",
        "day": "2026-09-20", "p_value": 0.004, "method": "blind-temporal-scan-nb"})
    assert response.status_code == 404
    assert count_events() == before


def test_an_upstream_search_carrying_a_count_is_refused(_network):
    response = client.post("/clinical/upstream-search", params={"stream": STREAM}, json={
        "area_code": zone_group_id(_network.zone_ids[0]), "syndrome": "acute_gastroenteritis",
        "day": "2026-09-20", "p_value": 0.004, "method": "blind-temporal-scan-nb",
        "count": 41})
    assert response.status_code == 422
