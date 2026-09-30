"""Phase 10: what the console and the mission PWA need from the Core API.

The web app holds no business logic, so everything it shows has to come from here:
the evidence behind any past belief (FR-37), one mission with its expected effect
(FR-38), and a submission path an offline phone can retry without double-counting
(NFR-9).
"""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from upstream_api.main import app

pytestmark = pytest.mark.integration
client = TestClient(app)


@pytest.fixture(autouse=True)
def _needs_pool(_pool):
    """Routes use the module-level pool; see test_ingest_routes."""


def _report(node: str, **extra) -> dict:
    return {"node_id": node, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
            "method": "citizen_visual_olfactory", "result": "negative",
            "observer_id": "vol-web", "observer_type": "citizen", "snap_distance_m": 3.0,
            "confirmed_by_observer": True, **extra}


# --------------------------------------------------------------------------- NFR-9


def test_a_retried_submission_is_recorded_once(a_node, count_events):
    """The phone cannot tell a lost request from a lost response, so it retries.

    The key it generated when the observation was made becomes the event id, and a
    second arrival returns the first event instead of appending another.
    """
    key = str(uuid.uuid4())
    body = _report(a_node, idempotency_key=key)          # a retry resends the same body
    before = count_events()
    first = client.post("/ingest/report/confirm", json=body)
    again = client.post("/ingest/report/confirm", json=body)
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json() == first.json()
    assert first.json()["event_id"] == key
    assert count_events() == before + 1


def test_a_key_reused_for_different_content_is_refused(a_node):
    """Same key, different observation: a client bug, never a silent overwrite."""
    key = str(uuid.uuid4())
    assert client.post("/ingest/report/confirm",
                       json=_report(a_node, idempotency_key=key)).status_code == 201
    r = client.post("/ingest/report/confirm",
                    json=_report(a_node, idempotency_key=key, result="positive"))
    assert r.status_code == 409


def test_the_idempotency_key_must_be_a_uuid(a_node):
    r = client.post("/ingest/report/confirm", json=_report(a_node, idempotency_key="abc"))
    assert r.status_code == 422


# --------------------------------------------------------------------------- FR-38


def test_mission_evidence_lands_on_its_episodes_stream(an_episode, candidates, a_volunteer,
                                                       db_conn):
    """A simulated episode's mission must not write into the live log (GC-10)."""
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    spec = create_missions_from_probe(an_episode, candidates(1))[0]
    r = client.post("/ingest/report/confirm",
                    json=_report(spec.node_id, method="test_strip",
                                 mission_id=spec.mission_id))
    assert r.status_code == 201
    with db_conn.cursor() as cur:
        cur.execute("SELECT stream FROM events WHERE event_id=%s", (r.json()["event_id"],))
        assert cur.fetchone()[0] == "sim"


def test_evidence_for_an_unknown_mission_is_refused(a_node):
    r = client.post("/ingest/report/confirm", json=_report(a_node, mission_id="M-NOPE"))
    assert r.status_code == 404


def test_one_mission_carries_its_expected_effect_and_window(an_episode, candidates,
                                                            a_volunteer):
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    spec = create_missions_from_probe(an_episode, candidates(1))[0]
    r = client.get(f"/missions/{spec.mission_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["node_id"] == spec.node_id
    assert body["status"] == "created"
    assert "expected to rule out" in body["expected_effect"]
    assert body["lon"] is not None and body["lat"] is not None
    assert body["window_end"] > body["window_start"]


def test_an_unknown_mission_is_404():
    assert client.get("/missions/M-NOPE").status_code == 404


# --------------------------------------------------------------------------- FR-37


def test_episode_evidence_carries_its_sequence_number(an_episode, post_evidence):
    """The replay slider shows the evidence a past belief was built from: seq <= as_of_seq."""
    post_evidence("positive")
    body = client.get(f"/episodes/{an_episode}", params={"stream": "sim"}).json()
    assert body["evidence"], "the episode must list the evidence around it"
    assert all(isinstance(e["seq"], int) for e in body["evidence"])
    seqs = [e["seq"] for e in body["evidence"]]
    assert seqs == sorted(seqs)


# --------------------------------------------------------------------------- streams


def test_episode_streams_are_parsed_and_checked():
    from upstream_api.config import Settings

    assert Settings(database_url="x", episode_streams="live, sim").episode_stream_list == \
        ["live", "sim"]
    assert Settings(database_url="x", episode_streams="").episode_stream_list == ["live"]
    with pytest.raises(ValueError):
        _ = Settings(database_url="x", episode_streams="live,demo").episode_stream_list


def test_the_timeline_can_start_at_an_episode(seed_snapshot):
    """Oldest-first with a limit never reaches today's episode on a long-lived stream."""
    seed_snapshot({"N1": 1.0})
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1)
    assert client.get("/replay/timeline", params={"stream": "sim",
                                                  "since": later.isoformat()}).json() == []
    earlier = later - dt.timedelta(minutes=5)
    assert client.get("/replay/timeline", params={"stream": "sim",
                                                  "since": earlier.isoformat()}).json()


# --------------------------------------------------------------------------- FR-39


def test_public_health_view_carries_the_clinical_test_results(emit_posterior, episode_row):
    """The result that crossed the boundary, and nothing about who it came from."""
    emit_posterior(p_event=0.97)
    episode_id = episode_row()["episode_id"]
    assert episode_row(episode_id)["state"] == "PROBABLE"
    body = {"episode_id": episode_id, "area_code": "zone-000-population", "syndrome": "ag",
            "method": "matched_filter", "p_value": 0.004, "effect_size": 1.8, "n_days": 9,
            "computed_at": dt.datetime.now(dt.UTC).isoformat()}
    assert client.post("/clinical/test-result", params={"stream": "sim"},
                       json=body).status_code == 201
    view = client.get("/public-health/episodes", params={"stream": "sim"}).json()
    ep = next(e for e in view["episodes"] if e["episode_id"] == episode_id)
    assert [r["p_value"] for r in ep["clinical_results"]] == [0.004]
    assert set(ep["clinical_results"][0]) == {"area_code", "syndrome", "method", "p_value",
                                              "effect_size", "n_days", "computed_at"}


# --------------------------------------------------------------------------- the client


def test_the_web_clients_schema_is_current():
    """web/lib/openapi.json is what the typed client is generated from (Phase 10.1).

    Regenerate with `uv run python scripts/export_openapi.py && (cd web && npm run types)`.
    """
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("export_openapi", root / "scripts/export_openapi.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    committed = (root / "web/lib/openapi.json").read_text(encoding="utf-8")
    assert committed == mod.schema_text(), "the API changed: regenerate web/lib/openapi.json"
