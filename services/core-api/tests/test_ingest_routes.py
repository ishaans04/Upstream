import datetime as dt

import pytest
from fastapi.testclient import TestClient
from upstream_api.main import app

pytestmark = pytest.mark.integration
client = TestClient(app)


@pytest.fixture(autouse=True)
def _needs_pool(_pool):
    """Routes use the module-level connection pool, which nothing else opens here.

    TestClient only runs the app lifespan when used as a context manager, and doing
    that per test would close the pool other tests still hold.
    """


def test_propose_does_not_append_anything(count_events, on_network_point):
    before = count_events()
    lon, lat = on_network_point
    r = client.post("/ingest/report/propose", json={
        "lon": lon, "lat": lat, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "free_text": "strong sewage smell"})
    assert r.status_code == 200
    assert r.json()["proposal"]["result"] == "positive"
    assert r.json()["snapped_node_id"]
    assert count_events() == before, "GC-8: a proposal must not enter the log"


def test_confirm_appends_evidence_with_both_times(store, a_node):
    observed = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=20)
    r = client.post("/ingest/report/confirm", json={
        "node_id": a_node, "observed_at": observed.isoformat(),
        "method": "citizen_visual_olfactory", "result": "positive",
        "observer_id": "vol-1", "observer_type": "citizen", "snap_distance_m": 12.0,
        "ai_assisted": True, "confirmed_by_observer": True, "oah_codes": []})
    assert r.status_code == 201
    ev = _fetch(store, r.json()["seq"])
    assert ev.event_time == observed and ev.recorded_at > observed


def test_negative_report_is_recorded_not_discarded(store, a_node):
    r = client.post("/ingest/report/confirm", json={
        "node_id": a_node, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "method": "citizen_visual_olfactory", "result": "negative",
        "observer_id": "vol-2", "observer_type": "citizen", "snap_distance_m": 4.0,
        "confirmed_by_observer": True})
    assert r.status_code == 201
    assert _fetch(store, r.json()["seq"]).payload["result"] == "negative"


def test_unconfirmed_ai_evidence_is_rejected(a_node):
    r = client.post("/ingest/report/confirm", json={
        "node_id": a_node, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "method": "citizen_freetext", "result": "positive", "observer_id": "v",
        "observer_type": "citizen", "snap_distance_m": 1.0,
        "ai_assisted": True, "confirmed_by_observer": False})
    assert r.status_code == 422


def test_observation_too_far_from_network_is_rejected():
    r = client.post("/ingest/report/propose", json={
        "lon": 5.0, "lat": 45.0, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "free_text": "foam"})
    assert r.status_code == 422 and "too far" in r.text


def test_future_event_time_is_rejected(a_node):
    r = client.post("/ingest/report/confirm", json={
        "node_id": a_node,
        "observed_at": (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat(),
        "method": "citizen_visual_olfactory", "result": "negative",
        "observer_id": "v", "observer_type": "citizen", "snap_distance_m": 1.0})
    assert r.status_code == 422


def test_retraction_is_a_new_event_not_a_delete(store, count_events, a_node):
    seq = client.post("/ingest/report/confirm", json={
        "node_id": a_node, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "method": "citizen_visual_olfactory", "result": "positive",
        "observer_id": "v", "observer_type": "citizen", "snap_distance_m": 1.0}).json()["seq"]
    before = count_events()
    ev = _fetch(store, seq)
    r = client.post("/ingest/retract", json={"event_id": str(ev.event_id),
                                             "reason": "wrong location",
                                             "retracted_by": "officer-1"})
    assert r.status_code == 201
    assert count_events() == before + 1
    assert _fetch(store, seq) is not None, "the original event must still exist"


def test_late_lab_result_keeps_its_original_event_time(store, a_node):
    three_days_ago = dt.datetime.now(dt.UTC) - dt.timedelta(days=3)
    r = client.post("/ingest/lab", json={
        "node_id": a_node, "observed_at": three_days_ago.isoformat(),
        "method": "lab_ecoli", "value": 2400.0, "unit": "{CFU}/100mL",
        "observer_id": "lab-a", "observer_type": "lab"})
    assert r.status_code == 201
    assert _fetch(store, r.json()["seq"]).event_time == three_days_ago


def test_rainfall_derives_a_flow_condition(store):
    now = dt.datetime.now(dt.UTC)
    for mm, expected in ((0.0, "dry"), (3.0, "wet"), (12.0, "storm")):
        r = client.post("/ingest/rainfall", json={"ts": now.isoformat(), "mm_per_h": mm})
        assert r.status_code == 201
        assert r.json()["flow_condition"] == expected


def test_overflow_records_both_an_activation_and_evidence(store, count_events, a_node):
    before = count_events()
    r = client.post("/ingest/overflow", json={
        "outfall_id": "O02", "node_id": a_node,
        "ts": dt.datetime.now(dt.UTC).isoformat(), "active": True})
    assert r.status_code == 201
    assert count_events() == before + 2, "an activation is both a signal and evidence"


def test_sensor_reading_lands_in_the_hypertable(db_conn, a_node):
    ts = dt.datetime.now(dt.UTC)
    r = client.post("/ingest/sensor", json={
        "sensor_id": "s-test-1", "node_id": a_node, "ts": ts.isoformat(),
        "parameter": "turbidity", "value": 42.0, "unit": "[NTU]"})
    assert r.status_code == 201
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sensor_readings WHERE sensor_id='s-test-1'")
        assert cur.fetchone()[0] >= 1


def _fetch(store, seq):
    from upstream_api.config import settings
    evs = store.read_from(seq - 1, catchment_id=settings.catchment_id, stream="live", limit=5)
    return next((e for e in evs if e.seq == seq), None)
