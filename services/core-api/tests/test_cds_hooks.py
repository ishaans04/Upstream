"""The CDS Hooks service (Task 7.4).

The three-condition rule is the whole service, so most of this file is that
rule: a card appears only when the area, the window and the reason for the visit
all line up. A card that fires on any one of them alone teaches clinicians to
dismiss it, which is worse than no card at all.
"""
import datetime as dt
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from upstream_api.fhir import audit, cds_hooks

UTC = dt.UTC

EXPOSURE_START = dt.datetime(2026, 9, 20, 7, 20, tzinfo=UTC)
EXPOSURE_END = dt.datetime(2026, 9, 20, 13, 20, tzinfo=UTC)
WINDOW_END = dt.datetime(2026, 10, 6, 7, 20, tzinfo=UTC)

INSIDE_WINDOW = dt.datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
AFTER_WINDOW = dt.datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
BEFORE_EXPOSURE = dt.datetime(2026, 9, 19, 10, 0, tzinfo=UTC)


def _episode(episode_id="EE-2841", areas=("zoneb",)) -> dict:
    return {
        "episode_id": episode_id,
        "opened_at": EXPOSURE_START,
        "exposure_start": EXPOSURE_START,
        "exposure_end": EXPOSURE_END,
        "clinical_window_end": WINDOW_END,
        "zone_areas": set(areas),
    }


@pytest.fixture
def recorded_audits(monkeypatch):
    """Capture audit records instead of writing them to HAPI.

    The real sink runs on a worker thread, which a test cannot join; replacing
    it also keeps these tests from needing a FHIR server.
    """
    written = []
    monkeypatch.setattr(audit, "sink", written.append)
    monkeypatch.setattr(audit._executor, "submit", lambda fn, *a: fn(*a))
    return written


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(cds_hooks, "active_episodes", lambda **_: [_episode()])
    api = FastAPI()
    api.include_router(cds_hooks.router)
    return TestClient(api)


def _request(area="ZONE_B", when=INSIDE_WINDOW, reason=("acute_gastroenteritis",)) -> dict:
    return {
        "hook": "patient-view",
        "hookInstance": "d1577c69-dfbe-44ad-ba6d-3e05e953b2ea",
        "context": {
            "patientId": "example",
            "encounterTime": when.isoformat(),
            "reasonCodes": list(reason),
        },
        "prefetch": {"patient": {"resourceType": "Patient", "address": [{"district": area}]}},
    }


def _hook(app, **over) -> dict:
    response = app.post(f"/cds-services/{cds_hooks.SERVICE_ID}", json=_request(**over))
    assert response.status_code == 200, response.text
    return response.json()


# --- Discovery --------------------------------------------------------------


def test_discovery_lists_both_hooks(app):
    services = app.get("/cds-services").json()["services"]
    assert {s["hook"] for s in services} == {"patient-view", "encounter-start"}


def test_each_discovered_service_has_its_own_id(app):
    services = app.get("/cds-services").json()["services"]
    assert len({s["id"] for s in services}) == len(services)


# --- The three conditions ---------------------------------------------------


def test_card_returned_when_area_window_and_syndrome_all_match(app, recorded_audits):
    cards = _hook(app)["cards"]
    assert len(cards) == 1
    assert "EE-2841" in cards[0]["summary"]


def test_no_card_when_the_area_does_not_overlap(app, recorded_audits):
    assert _hook(app, area="ZONE_FAR")["cards"] == []


def test_no_card_outside_the_clinical_relevance_window(app, recorded_audits):
    assert _hook(app, when=AFTER_WINDOW)["cards"] == []


def test_no_card_before_the_exposure_happened(app, recorded_audits):
    """A visit that predates the contamination cannot have been caused by it."""
    assert _hook(app, when=BEFORE_EXPOSURE)["cards"] == []


def test_no_card_for_an_unrelated_reason_for_visit(app, recorded_audits):
    assert _hook(app, reason=("ankle_sprain",))["cards"] == []


def test_no_card_when_the_ehr_sends_no_reason_at_all(app, recorded_audits):
    """An empty reason is not a match. Absence of evidence is not evidence."""
    assert _hook(app, reason=())["cards"] == []


def test_no_card_when_the_patient_has_no_address(app, recorded_audits):
    body = _request()
    body["prefetch"]["patient"]["address"] = []
    response = app.post(f"/cds-services/{cds_hooks.SERVICE_ID}", json=body)
    assert response.json()["cards"] == []


def test_the_area_match_ignores_case_and_punctuation(app, recorded_audits):
    """An EHR sends 'Zone B' or 'zone-b'; the zone is ZONE_B."""
    assert len(_hook(app, area="Zone B")["cards"]) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    ("state", "visible"),
    [("SUSPECTED", False), ("PROBABLE", True), ("CONFIRMED", True), ("RESOLVED", False)],
)
def test_only_actionable_episodes_reach_the_card_rule(
    state, visible, db_conn, episodes, _pool
):
    """One unconfirmed citizen report is not grounds for prompting a test.

    SUSPECTED is excluded, and so is an episode whose clinical window has
    closed -- a clinician can no longer act on either.
    """
    from upstream_api.config import settings

    episode_id = f"EE-CDS-{state}"
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO episodes (episode_id, catchment_id, stream, state, opened_at, "
            "state_changed_at, est_start_lo, est_start_hi, clinical_window_end, summary) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                episode_id,
                settings.catchment_id,
                "sim",
                state,
                EXPOSURE_START,
                EXPOSURE_START,
                EXPOSURE_START,
                EXPOSURE_END,
                dt.datetime.now(UTC) + dt.timedelta(days=5),
                Jsonb({"zone_windows": {"ZONE_A": {}}}),
            ),
        )

    cds_hooks.invalidate_cache()
    found = {e["episode_id"] for e in cds_hooks.active_episodes(force=True)}
    assert (episode_id in found) is visible


@pytest.mark.integration
def test_an_episode_whose_window_has_closed_reaches_nobody(db_conn, episodes, _pool):
    from upstream_api.config import settings

    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO episodes (episode_id, catchment_id, stream, state, opened_at, "
            "state_changed_at, clinical_window_end, summary) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                "EE-CDS-EXPIRED",
                settings.catchment_id,
                "sim",
                "CONFIRMED",
                EXPOSURE_START,
                EXPOSURE_START,
                dt.datetime.now(UTC) - dt.timedelta(days=1),
                Jsonb({"zone_windows": {"ZONE_A": {}}}),
            ),
        )

    cds_hooks.invalidate_cache()
    found = {e["episode_id"] for e in cds_hooks.active_episodes(force=True)}
    assert "EE-CDS-EXPIRED" not in found


# --- What the card says -----------------------------------------------------


def test_card_suggests_pathogen_specific_testing(app, recorded_audits):
    """PRD 7.6: the card's value is prompting a test routine panels may omit."""
    card = _hook(app)["cards"][0]
    assert "cryptosporidium" in card["detail"].lower()


def test_card_says_it_is_not_a_diagnosis(app, recorded_audits):
    """GC-12, on every health-facing output without exception."""
    card = _hook(app)["cards"][0]
    assert "not a diagnosis" in card["detail"].lower()


def test_card_names_no_polluter(app, recorded_audits):
    """GC-12: a source ranking is not an accusation and never reaches a clinician."""
    card = _hook(app)["cards"][0]
    assert "outfall" not in json.dumps(card).lower()


def test_card_is_informational_not_a_warning(app, recorded_audits):
    """Upstream does not issue advisories (GC-12)."""
    assert _hook(app)["cards"][0]["indicator"] == "info"


# --- What is and is not recorded --------------------------------------------


def test_every_call_writes_an_audit_record(app, recorded_audits):
    _hook(app)
    _hook(app, area="ZONE_FAR")
    assert len(recorded_audits) == 2
    assert all(a["resourceType"] == "AuditEvent" for a in recorded_audits)


def test_the_audit_record_carries_no_clinical_content(app, recorded_audits):
    """FR-30 records that a decision was made, never what the patient came in with."""
    _hook(app)
    recorded = json.dumps(recorded_audits[0]).lower()
    assert "acute_gastroenteritis" not in recorded
    assert "zone_b" not in recorded and "zoneb" not in recorded
    assert "example" not in recorded  # the patient id


def test_the_audit_record_says_which_episode_matched(app, recorded_audits):
    _hook(app)
    assert "EE-2841" in json.dumps(recorded_audits[0])


def test_a_miss_is_audited_as_a_miss(app, recorded_audits):
    _hook(app, area="ZONE_FAR")
    details = recorded_audits[0]["entity"][0]["detail"]
    assert {"type": "matched", "valueString": "False"} in details


def test_audit_drops_anything_the_caller_should_not_have_passed():
    """The caller is holding a request with a patient in it. Trust nothing."""
    event = audit.audit_event(
        "cds-card-served",
        outcome="0",
        detail={"episode_id": "EE-1", "patient_id": "abc", "reason": "gastro"},
    )
    recorded = json.dumps(event)
    assert "abc" not in recorded and "gastro" not in recorded


def test_the_service_never_persists_anything_about_the_patient(app, recorded_audits, count_events):
    """GC-7: the request is read, matched, answered and forgotten."""
    before = count_events()
    _hook(app)
    assert count_events() == before


# --- Latency ----------------------------------------------------------------


def test_response_is_under_the_latency_budget(app, recorded_audits):
    """GC-9 and NFR-2: a clinician is waiting, so 500 ms is the ceiling."""
    _hook(app)  # warm the client
    elapsed = []
    for _ in range(20):
        started = time.perf_counter()
        _hook(app)
        elapsed.append(time.perf_counter() - started)
    assert max(elapsed) < 0.5, f"slowest call {max(elapsed):.3f}s"


# --- Reading the request ----------------------------------------------------


def test_coarse_area_prefers_district_and_never_reads_a_street():
    """PRD 14.2: area, never a location."""
    body = {
        "prefetch": {
            "patient": {
                "address": [
                    {
                        "line": ["14 Rua das Flores"],
                        "district": "Coselhas",
                        "postalCode": "3000-123",
                    }
                ]
            }
        }
    }
    assert cds_hooks.coarse_area(body) == "Coselhas"
    assert "Flores" not in str(cds_hooks.coarse_area(body))


def test_encounter_time_defaults_to_now_when_the_ehr_sends_none():
    body = {"context": {}}
    assert (
        dt.datetime.now(UTC) - cds_hooks.encounter_time(body)
    ).total_seconds() < 5


def test_reason_codes_are_read_from_a_prefetched_encounter_too():
    body = {
        "context": {},
        "prefetch": {
            "encounter": {
                "reasonCode": [{"coding": [{"code": "acute_gastroenteritis"}]}]
            }
        },
    }
    assert cds_hooks.reason_codes(body) == ["acute_gastroenteritis"]
