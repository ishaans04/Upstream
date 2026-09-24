"""Publishing an episode to HAPI, end to end (Task 7.3, Phase 7 exit criteria).

These tests need a running HAPI with Upstream's profiles loaded
(`make fhir-load`). They are the only place that proves the whole chain: an
episode and its evidence in Postgres, through the mapper, past HAPI's validator,
into resources a consumer can read back.

Everything is written on the `sim` stream and torn down afterwards, so nothing
here touches live belief (CLAUDE.md note 11).
"""
import datetime as dt
import os
import uuid

import pytest
from psycopg.types.json import Jsonb
from upstream_shared.codes import ObservationMethod
from upstream_shared.events import EventEnvelope, EventType

pytestmark = pytest.mark.integration

STREAM = "sim"
EPISODE_ID = "EE-PUB-TEST"
UTC = dt.UTC

HAPI = os.environ.get("HAPI_BASE_URL", "http://localhost:8080/fhir")


@pytest.fixture(scope="module")
def hapi_module():
    import httpx

    try:
        response = httpx.get(f"{HAPI}/metadata", timeout=10.0)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - environment, not behaviour
        pytest.skip(f"HAPI is not available at {HAPI}: {exc}")

    from upstream_api.fhir import client as client_module

    return client_module.FhirClient(HAPI)


@pytest.fixture
def hapi(hapi_module):
    return hapi_module


@pytest.fixture(scope="module")
def db_conn_module():
    import os

    import psycopg

    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def store_module(_pool):
    from upstream_api.eventlog import store as event_store

    return event_store


@pytest.fixture(scope="module")
def published(request, _pool, db_conn_module, store_module, hapi_module):
    """One episode with three observations, one of them retracted.

    Module-scoped on purpose. Publishing writes about fifteen resources and
    every one of them is validated by HAPI first, which with the HL7 extensions
    pack loaded takes minutes; republishing per test made the file unusable.
    These tests only read what was published, so once is enough.
    """
    from upstream_api.config import settings
    from upstream_api.fhir import publisher
    from upstream_api.network import get_network

    db_conn = db_conn_module
    store = store_module
    hapi = hapi_module

    original_client = publisher.FhirClient
    publisher.FhirClient = lambda *a, **k: hapi

    def purge():
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM posterior_snapshots WHERE episode_id=%s", (EPISODE_ID,))
            cur.execute("DELETE FROM episodes WHERE episode_id=%s", (EPISODE_ID,))

    # Registered, not just called at the end: a fixture that fails partway
    # through never reaches the code after its yield, and the rows it left
    # behind then break both the next run of this file and any later test that
    # reads snapshots on this stream.
    request.addfinalizer(purge)
    purge()

    net = get_network()
    zone_id = net.zone_ids[0]
    node_id = net.entry_nodes[0]
    opened = dt.datetime.now(UTC) - dt.timedelta(hours=2)

    def evidence(result: str, method: ObservationMethod, **extra) -> uuid.UUID:
        envelope = EventEnvelope(
            stream=STREAM,
            catchment_id=settings.catchment_id,
            event_type=EventType.EVIDENCE_RECORDED,
            event_time=opened + dt.timedelta(minutes=5),
            payload={
                "node_id": node_id,
                "method": method.value,
                "result": result,
                "observer_id": "test-observer",
                "observer_type": "citizen",
                "snap_distance_m": 1.0,
                "oah_codes": [],
                "ai_assisted": False,
                "confirmed_by_observer": False,
                **extra,
            },
        )
        store.append(envelope)
        return envelope.event_id

    kept = evidence("positive", ObservationMethod.CITIZEN_VISUAL_OLFACTORY)
    negative = evidence("negative", ObservationMethod.CITIZEN_VISUAL_OLFACTORY)
    doomed = evidence("positive", ObservationMethod.TEST_STRIP)

    store.append(
        EventEnvelope(
            stream=STREAM,
            catchment_id=settings.catchment_id,
            event_type=EventType.EVIDENCE_RETRACTED,
            event_time=dt.datetime.now(UTC),
            payload={
                "retracts_event_id": str(doomed),
                "reason": "observer withdrew the report",
                "retracted_by": "test-observer",
            },
        )
    )

    with db_conn.cursor() as cur:
        cur.execute("SELECT coalesce(max(seq), 0) FROM events")
        as_of_seq = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO episodes (episode_id, catchment_id, stream, state, opened_at, "
            "state_changed_at, est_start_lo, est_start_hi, clinical_window_end, version, "
            "summary) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                EPISODE_ID,
                settings.catchment_id,
                STREAM,
                "PROBABLE",
                opened,
                opened,
                opened,
                opened + dt.timedelta(hours=6),
                dt.datetime.now(UTC) + dt.timedelta(days=10),
                3,
                Jsonb({}),
            ),
        )
        cur.execute(
            "INSERT INTO posterior_snapshots (ts, fingerprint, episode_id, catchment_id, "
            "stream, as_of_seq, network_version, kernel_version, params_version, p_event, "
            "source_marginals, zone_windows, probe_candidates) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                dt.datetime.now(UTC),
                "fp-publisher-test",
                EPISODE_ID,
                settings.catchment_id,
                STREAM,
                as_of_seq,
                "test",
                "upstream-kernel test",
                "test",
                0.91,
                Jsonb({node_id: 0.7, "__none__": 0.3}),
                Jsonb(
                    {
                        zone_id: {
                            "window_lo": (opened + dt.timedelta(minutes=30)).timestamp(),
                            "window_hi": (opened + dt.timedelta(hours=4)).timestamp(),
                            "p_peak": 0.63,
                            "pathways": ["recreation"],
                        }
                    }
                ),
                Jsonb([]),
            ),
        )

    written = publisher.publish_episode(EPISODE_ID)

    yield {
        "written": written,
        "zone_id": zone_id,
        "node_id": node_id,
        "kept": kept,
        "negative": negative,
        "retracted": doomed,
    }

    publisher.FhirClient = original_client


def _read(hapi, resource_type: str, resource_id: str) -> dict:
    import httpx

    response = httpx.get(f"{hapi.base}/{resource_type}/{resource_id}", timeout=30.0)
    response.raise_for_status()
    return response.json()


def test_the_episode_is_readable_back_as_a_riskassessment(published, hapi):
    """The Phase 7 exit criterion: a state change puts an episode in HAPI."""
    risk = _read(hapi, "RiskAssessment", published["written"]["id"])
    assert risk["identifier"][0]["value"] == EPISODE_ID
    assert risk["meta"]["tag"][0]["code"] == "PROBABLE"
    assert risk["status"] == "amended"
    assert risk["prediction"]


def test_every_observation_in_the_basis_exists(published, hapi):
    """A basis reference that does not resolve makes an episode unexplainable."""
    risk = _read(hapi, "RiskAssessment", published["written"]["id"])
    assert risk["basis"]
    # Spot-check rather than walk: the basis is the catchment's whole horizon.
    for reference in risk["basis"][:20]:
        observation = _read(hapi, *reference["reference"].split("/"))
        assert observation["resourceType"] == "Observation"


def test_retracted_evidence_is_published_but_is_not_the_basis(published, hapi):
    """GC-6 and GC-5 at once.

    The kernel computed this posterior with the retracted observation excluded,
    so naming it as the basis would claim the episode rests on something it does
    not. Removing it from the server instead would break every earlier version
    of the episode that does rest on it.
    """
    from upstream_api.fhir.mapper import observation_id

    risk = _read(hapi, "RiskAssessment", published["written"]["id"])
    basis = {b["reference"] for b in risk["basis"]}

    # The basis is the whole catchment's evidence for the kernel's horizon, not
    # this episode's alone, so assert on the three observations this test made
    # rather than on a total the shared sim stream controls.
    assert f"Observation/{observation_id(published['kept'])}" in basis
    assert f"Observation/{observation_id(published['negative'])}" in basis

    retracted_id = observation_id(published["retracted"])
    assert f"Observation/{retracted_id}" not in basis

    # ...and the retracted one is still on the server.
    assert _read(hapi, "Observation", retracted_id)["status"] == "entered-in-error"


def test_retracted_evidence_is_published_as_entered_in_error_not_deleted(published, hapi):
    """FR-10, GC-5. The retracted observation is still there, and says so."""
    from upstream_api.fhir.mapper import observation_id

    retracted = _read(hapi, "Observation", observation_id(published["retracted"]))
    assert retracted["status"] == "entered-in-error"

    kept = _read(hapi, "Observation", observation_id(published["kept"]))
    assert kept["status"] == "final"


def test_the_negative_observation_records_a_finding_not_absent_data(published, hapi):
    from upstream_api.fhir.mapper import observation_id

    negative = _read(hapi, "Observation", observation_id(published["negative"]))
    assert "dataAbsentReason" not in negative
    assert negative["valueCodeableConcept"]["coding"][0]["code"] == "260385009"


def test_the_zone_and_its_population_are_published(published, hapi):
    from upstream_api.fhir.mapper import zone_group_id, zone_location_id

    location = _read(hapi, "Location", zone_location_id(published["zone_id"]))
    assert location["identifier"][0]["value"] == published["zone_id"]

    group = _read(hapi, "Group", zone_group_id(published["zone_id"]))
    assert group["actual"] is False
    assert "member" not in group


def test_the_episode_subject_resolves(published, hapi):
    """The subject reference has to point at a Group that actually exists."""
    risk = _read(hapi, "RiskAssessment", published["written"]["id"])
    group = _read(hapi, *risk["subject"]["reference"].split("/"))
    assert group["resourceType"] == "Group"


def test_provenance_records_the_kernel_and_the_evidence(published, hapi):
    import httpx

    response = httpx.get(
        f"{hapi.base}/Provenance",
        params={"target": f"RiskAssessment/{published['written']['id']}"},
        timeout=30.0,
    )
    response.raise_for_status()
    entries = response.json().get("entry") or []
    assert entries, "no Provenance was published for the episode"
    provenance = entries[0]["resource"]
    roles = {a["type"]["coding"][0]["code"] for a in provenance["agent"]}
    assert "assembler" in roles
    assert provenance["entity"]


def test_publishing_appends_a_fhir_published_event(published, db_conn_module):
    """The publication is itself on the record."""
    with db_conn_module.cursor() as cur:
        cur.execute(
            "SELECT payload FROM events WHERE event_type=%s AND stream=%s "
            "AND payload->>'episode_id'=%s ORDER BY seq DESC LIMIT 1",
            (EventType.FHIR_PUBLISHED.value, STREAM, EPISODE_ID),
        )
        row = cur.fetchone()
    assert row is not None, "no FhirPublished event was appended"
    assert row[0]["risk_assessment_id"] == published["written"]["id"]
    assert row[0]["observation_count"] >= 2
    assert row[0]["retracted_observation_count"] >= 1


def test_the_episode_row_records_where_it_was_published(published, db_conn_module):
    with db_conn_module.cursor() as cur:
        cur.execute(
            "SELECT fhir_risk_assessment_id FROM episodes WHERE episode_id=%s",
            (EPISODE_ID,),
        )
        assert cur.fetchone()[0] == published["written"]["id"]


def test_an_invalid_resource_is_never_written(hapi):
    """GC-3 on write: validation failure is a hard failure, not a warning."""
    from upstream_api.fhir.client import FhirValidationError
    from upstream_api.fhir.mapper import SD

    with pytest.raises(FhirValidationError):
        hapi.put(
            {
                "resourceType": "RiskAssessment",
                "id": "upstream-never-written",
                "meta": {"profile": [f"{SD}/UpstreamExposureEpisode"]},
                "status": "final",
            }
        )

    import httpx

    response = httpx.get(f"{hapi.base}/RiskAssessment/upstream-never-written", timeout=30.0)
    assert response.status_code == 404
