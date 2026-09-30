"""Task 11.2: role-based access (PRD 14.3) and what public reads may show (PRD 14.2)."""
from __future__ import annotations

import datetime as dt
import json

import jwt
import pytest
from conftest import STREAM
from fastapi.testclient import TestClient
from upstream_api.main import app

pytestmark = pytest.mark.integration

client = TestClient(app)
KEY = "test-signing-key-" + "x" * 32


@pytest.fixture(autouse=True)
def real_auth(_pool, monkeypatch):
    """Every other test file runs as an admin (conftest); these run with real tokens."""
    from upstream_api.config import settings

    monkeypatch.setattr(settings, "jwt_signing_key", KEY)


def bearer(*roles: str, sub: str = "someone", key: str = KEY, ttl_s: int = 600) -> dict:
    from upstream_api.security import mint

    return {"Authorization": "Bearer " + mint(sub, list(roles), key=key,
                                               ttl=dt.timedelta(seconds=ttl_s))}


SIGNOFF = ("/episodes/EE-NOPE/signoff", {"officer_id": "off-1"})


def test_officer_endpoints_reject_an_unauthenticated_caller():
    r = client.post(SIGNOFF[0], json=SIGNOFF[1])
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_citizen_role_cannot_sign_off_an_episode():
    assert client.post(SIGNOFF[0], json=SIGNOFF[1], headers=bearer("citizen")).status_code == 403


def test_an_officer_gets_past_the_door():
    """404 (no such episode) proves authorisation passed and the route ran."""
    assert client.post(SIGNOFF[0], json=SIGNOFF[1], headers=bearer("officer")).status_code == 404


def test_admin_may_do_what_an_officer_may():
    assert client.post(SIGNOFF[0], json=SIGNOFF[1], headers=bearer("admin")).status_code == 404


@pytest.mark.parametrize("headers", [
    {"Authorization": "Bearer not-a-jwt"},
    {"Authorization": "Basic b2ZmOnB3"},
])
def test_a_malformed_credential_is_refused(headers):
    assert client.post(SIGNOFF[0], json=SIGNOFF[1], headers=headers).status_code == 401


def test_an_expired_or_foreign_token_is_refused():
    assert client.post(SIGNOFF[0], json=SIGNOFF[1],
                       headers=bearer("officer", ttl_s=-10)).status_code == 401
    assert client.post(SIGNOFF[0], json=SIGNOFF[1],
                       headers=bearer("officer", key="another-key-" + "y" * 32)).status_code == 401


def test_a_token_is_refused_when_no_key_is_configured(monkeypatch):
    """Fail closed: an unconfigured server must not wave tokens through."""
    from upstream_api.config import settings

    headers = bearer("officer")
    monkeypatch.setattr(settings, "jwt_signing_key", "")
    assert client.post(SIGNOFF[0], json=SIGNOFF[1], headers=headers).status_code == 503


def test_a_token_cannot_invent_a_role():
    from upstream_api.config import settings

    token = jwt.encode({"sub": "x", "roles": ["superuser"],
                        "exp": dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)},
                       settings.jwt_signing_key, algorithm="HS256")
    r = client.post(SIGNOFF[0], json=SIGNOFF[1], headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.parametrize(("method", "path", "role"), [
    ("post", "/ingest/retract", "officer"),
    ("post", "/ingest/lab", "officer"),
    ("post", "/ingest/sensor", "agency"),
    ("post", "/ingest/rainfall", "agency"),
    ("post", "/ingest/overflow", "agency"),
    ("post", "/episodes/EE-NOPE/signoff/request", "officer"),
    ("get", "/reports/recurring-sources", "agency"),
    ("get", "/clinical/episodes", "public_health"),
    ("post", "/clinical/test-result", "public_health"),
    ("post", "/clinical/upstream-search", "public_health"),
    ("get", "/exports/evidence.parquet", "agency"),
    ("get", "/exports/episodes.parquet", "agency"),
])
def test_each_protected_route_names_its_role(method, path, role):
    call = getattr(client, method)
    kw = {"json": {}} if method == "post" else {}
    assert call(path, **kw).status_code == 401
    assert call(path, headers=bearer("citizen"), **kw).status_code == 403
    assert call(path, headers=bearer(role), **kw).status_code not in (401, 403)


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/episodes"), ("get", "/replay/timeline"), ("get", "/network/geojson"),
    ("get", "/public-health/episodes"), ("get", "/missions/mine?volunteer_id=v"),
])
def test_public_reads_stay_public(method, path):
    """The MVP web app has no login; what it reads must not need one."""
    assert getattr(client, method)(path).status_code == 200


def test_no_route_lets_a_caller_choose_enforce_mode():
    """PRD open question 7, decided: enforce mode is off. An enforce-mode recommendation
    names an outfall to inspect, and PRD 14.4 routes enforcement through an officer. If a
    route ever takes a PROBE mode, it must require the agency role - and this test
    fails until someone decides that deliberately."""
    spec = json.dumps(app.openapi()).lower()
    assert '"enforce"' not in spec


def test_no_endpoint_returns_patient_level_data():
    """GC-7: outside the CDS Hooks surface, nothing in the API speaks of patients."""
    for path, item in app.openapi()["paths"].items():
        if path.startswith("/cds-services"):
            continue
        assert "patient" not in json.dumps(item).lower(), path


# ------------------------------------------------------------ what public reads show


@pytest.fixture
def citizen_report_with_photo(an_episode, _network):
    body = {"node_id": _network.entry_nodes[0], "observed_at": dt.datetime.now(dt.UTC).isoformat(),
            "method": "citizen_visual_olfactory", "result": "positive",
            "observer_id": "vol-private-7", "observer_type": "citizen",
            "snap_distance_m": 3.0, "confirmed_by_observer": True,
            "photo_uri": "s3://media/photo-with-a-face.jpg"}
    r = client.post("/ingest/report/confirm", json=body)
    assert r.status_code in (200, 201), r.text
    # Mission-less citizen evidence goes to the live stream; read it back from there.
    return an_episode, r.json()["event_id"]


def test_public_reads_hide_the_observer_and_the_photo(citizen_report_with_photo):
    """PRD 14.2: photos are withheld until screened for faces and number plates, and a
    volunteer is not named to the public."""
    from upstream_api.security import redact_evidence

    payload = {"observer_id": "vol-private-7", "photo_uri": "s3://x.jpg", "node_id": "N1"}
    assert redact_evidence(payload, None) == {"node_id": "N1"}
    _, event_id = citizen_report_with_photo
    text = client.get(f"/evidence/{event_id}").text
    assert "vol-private-7" not in text and "photo-with-a-face" not in text


def test_an_officer_sees_who_reported_and_the_photo(citizen_report_with_photo):
    _, event_id = citizen_report_with_photo
    body = client.get(f"/evidence/{event_id}", headers=bearer("officer")).json()
    assert body["payload"]["observer_id"] == "vol-private-7"
    assert body["payload"]["photo_uri"].endswith("photo-with-a-face.jpg")


def test_episode_detail_carries_no_observer_ids_publicly(an_episode, post_evidence):
    post_evidence("positive")                               # observer "off-1"
    text = client.get(f"/episodes/{an_episode}", params={"stream": STREAM}).text
    assert '"observer_id"' not in text
    officer = client.get(f"/episodes/{an_episode}", params={"stream": STREAM},
                         headers=bearer("officer")).text
    assert '"observer_id"' in officer
