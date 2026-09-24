"""The FHIR view of the engine (Task 7.3).

The mapper is pure: internal state in, a resource dict out. Everything here is
therefore a unit test, with one exception at the bottom -- the integration test
that puts the mapper's output in front of the real validator, because a resource
that is well-shaped and still invalid is exactly the failure a unit test cannot
see.
"""
import base64
import datetime as dt
import json
import os
import uuid

import pytest
from upstream_api.eventlog import StoredEvent
from upstream_api.fhir.mapper import (
    SD,
    episode_to_riskassessment,
    evidence_to_observation,
    provenance_for,
    zone_to_group,
    zone_to_location,
)
from upstream_shared.codes import ObservationMethod
from upstream_shared.episode import EpisodeState
from upstream_shared.events import EventType

UTC = dt.UTC


def _event(**payload) -> StoredEvent:
    base = {
        "node_id": "N1",
        "method": ObservationMethod.CITIZEN_VISUAL_OLFACTORY.value,
        "result": "positive",
        "observer_id": "citizen-7",
        "observer_type": "citizen",
        "snap_distance_m": 3.0,
        "oah_codes": [],
        "ai_assisted": False,
        "confirmed_by_observer": False,
    }
    base.update(payload)
    event_time = base.pop("_event_time", dt.datetime(2026, 9, 20, 7, 42, tzinfo=UTC))
    recorded_at = base.pop("_recorded_at", dt.datetime(2026, 9, 20, 7, 44, tzinfo=UTC))
    return StoredEvent(
        seq=1,
        event_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        stream="live",
        catchment_id="coimbra-ribeira",
        event_type=EventType.EVIDENCE_RECORDED,
        schema_version=1,
        event_time=event_time,
        recorded_at=recorded_at,
        payload=base,
        causation_id=None,
        correlation_id=None,
    )


def _episode(state=EpisodeState.SUSPECTED, version=1) -> dict:
    return {
        "episode_id": "EE-2841",
        "state": state.value,
        "version": version,
        "stream": "live",
        "clinical_window_end": dt.datetime(2026, 10, 6, 7, 20, tzinfo=UTC),
    }


def _zone_window(lo: float, hi: float, p_peak: float, pathways=("recreation",)) -> dict:
    return {
        "window_lo": lo,
        "window_hi": hi,
        "p_peak": p_peak,
        "pathways": list(pathways),
    }


def _snapshot(zones: dict | None = None, **over) -> dict:
    snap = {
        "ts": dt.datetime(2026, 9, 20, 7, 45, 10, tzinfo=UTC),
        "fingerprint": "8f14e45fceea167a5a36dedd4bea2543",
        "kernel_version": "upstream-kernel 0.1.0",
        "source_marginals": {"N1": 0.63, "N2": 0.15, "__none__": 0.22},
        "zone_windows": zones
        if zones is not None
        else {
            "ZONE_A": _zone_window(
                dt.datetime(2026, 9, 20, 7, 20, tzinfo=UTC).timestamp(),
                dt.datetime(2026, 9, 20, 13, 20, tzinfo=UTC).timestamp(),
                0.41,
            )
        },
        "evidence_ids": ["ev-11111111"],
    }
    snap.update(over)
    return snap


@pytest.fixture
def snap():
    return _snapshot()


@pytest.fixture
def snap_two_zones():
    return _snapshot(
        {
            "ZONE_A": _zone_window(
                dt.datetime(2026, 9, 20, 7, 20, tzinfo=UTC).timestamp(),
                dt.datetime(2026, 9, 20, 13, 20, tzinfo=UTC).timestamp(),
                0.41,
            ),
            "ZONE_B": _zone_window(
                dt.datetime(2026, 9, 20, 9, 5, tzinfo=UTC).timestamp(),
                dt.datetime(2026, 9, 20, 15, 5, tzinfo=UTC).timestamp(),
                0.22,
                ("animal_contact", "floodwater"),
            ),
        }
    )


# --- The episode as a RiskAssessment ---------------------------------------


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (EpisodeState.SUSPECTED, "preliminary"),
        (EpisodeState.CONFIRMED, "final"),
        (EpisodeState.RESOLVED, "final"),
        (EpisodeState.REFUTED, "cancelled"),
    ],
)
def test_riskassessment_status_maps_from_episode_state(state, expected, snap, _network):
    ra = episode_to_riskassessment(_episode(state), snap, _network)
    assert ra["status"] == expected


def test_a_republished_episode_is_amended(snap, _network):
    """Version 1 is preliminary; a later version of the same open episode is amended."""
    ra = episode_to_riskassessment(_episode(EpisodeState.PROBABLE, version=3), snap, _network)
    assert ra["status"] == "amended"


def test_meta_tag_carries_the_exact_episode_state(snap, _network):
    ra = episode_to_riskassessment(_episode(EpisodeState.PROBABLE), snap, _network)
    assert ra["meta"]["tag"][0]["code"] == "PROBABLE"
    assert ra["meta"]["tag"][0]["system"].endswith("/CodeSystem/episode-state")


def test_one_prediction_per_zone_with_a_period_and_a_decimal_probability(
    snap_two_zones, _network
):
    ra = episode_to_riskassessment(_episode(), snap_two_zones, _network)
    assert len(ra["prediction"]) == 2
    assert all(
        "whenPeriod" in p and isinstance(p["probabilityDecimal"], float)
        for p in ra["prediction"]
    )


def test_a_zone_with_no_credible_window_gets_no_prediction(_network):
    """PULSE returns window_lo None for a zone the plume never credibly reaches."""
    snap = _snapshot(
        {
            "ZONE_A": _zone_window(
                dt.datetime(2026, 9, 20, 7, 20, tzinfo=UTC).timestamp(),
                dt.datetime(2026, 9, 20, 13, 20, tzinfo=UTC).timestamp(),
                0.41,
            ),
            "ZONE_B": {
                "window_lo": None,
                "window_hi": None,
                "p_peak": 0.0,
                "pathways": [],
            },
        }
    )
    ra = episode_to_riskassessment(_episode(), snap, _network)
    assert [p["outcome"]["text"] for p in ra["prediction"]]
    assert len(ra["prediction"]) == 1


def test_fingerprint_extension_matches_the_snapshot(snap, _network):
    ra = episode_to_riskassessment(_episode(), snap, _network)
    fp = next(e for e in ra["extension"] if e["url"].endswith("upstream-fingerprint"))
    assert fp["valueString"] == snap["fingerprint"]


def test_note_carries_the_not_a_diagnosis_disclaimer(snap, _network):
    """GC-12."""
    ra = episode_to_riskassessment(_episode(), snap, _network)
    assert any("not a diagnosis" in n["text"].lower() for n in ra["note"])


def test_the_none_pseudo_source_is_never_published_as_a_candidate(snap, _network):
    """`__none__` is the kernel's no-event hypothesis, not a place on the network."""
    ra = episode_to_riskassessment(_episode(), snap, _network)
    ranked = [e for e in ra["extension"] if e["url"].endswith("upstream-source-ranking")]
    refs = [
        sub["valueReference"]["reference"]
        for e in ranked
        for sub in e["extension"]
        if sub["url"] == "sourceLocation"
    ]
    assert refs and not any("none" in r.lower() for r in refs)


def test_exposure_window_extension_carries_an_eighty_percent_credible_level(
    snap, _network
):
    """GC-11: the windows PULSE produces are 80% credible intervals."""
    ra = episode_to_riskassessment(_episode(), snap, _network)
    win = next(e for e in ra["extension"] if e["url"].endswith("upstream-exposure-window"))
    level = next(s for s in win["extension"] if s["url"] == "credibleLevel")
    assert level["valueDecimal"] == 0.80


def test_the_subject_is_a_zone_population_never_a_patient(snap, _network):
    """GC-7: an episode is about a place and the people in it, never an identified one."""
    ra = episode_to_riskassessment(_episode(), snap, _network)
    assert ra["subject"]["reference"].startswith("Group/")


# --- Evidence as Observations ----------------------------------------------


def test_observation_code_is_a_oneaquahealth_indicator(_network):
    """GC-2: what was observed is OAH terminology; only how is Upstream's."""
    obs = evidence_to_observation(_event(), retracted=False)
    assert obs["code"]["coding"][0]["system"] == (
        "http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu"
    )
    assert obs["method"]["coding"][0]["system"].endswith("/CodeSystem/observation-method")


def test_explicit_oah_codes_on_the_evidence_win_over_the_method_default():
    obs = evidence_to_observation(_event(oah_codes=["nitrite"]), retracted=False)
    assert obs["code"]["coding"][0]["code"] == "nitrite"


def test_negative_observation_records_a_negative_finding_not_absent_data():
    """A check that happened and found nothing is evidence, not a missing value.

    The plan reached for dataAbsentReason#not-performed here. That says the
    opposite of what happened and would mislead anyone reading the basis of an
    episode, so an explicit negative carries a coded negative finding instead.
    """
    obs = evidence_to_observation(_event(result="negative"), retracted=False)
    assert "dataAbsentReason" not in obs
    assert obs["valueCodeableConcept"]["coding"][0]["code"] == "260385009"
    assert obs["interpretation"][0]["coding"][0]["code"] == "NEG"


def test_retracted_observation_becomes_entered_in_error():
    """FR-10 + GC-5: a retraction changes status; it never deletes."""
    assert evidence_to_observation(_event(), retracted=True)["status"] == "entered-in-error"


def test_a_retracted_observation_claims_the_profile_that_allows_it():
    """The OneAquaHealth indicator observation pattern-fixes status to #final.

    A withdrawn reading cannot conform to it, and should not: it is no longer an
    indicator. Claiming the indicator profile anyway would make every retraction
    fail validation on write, which is how this was found.
    """
    retracted = evidence_to_observation(_event(), retracted=True)
    assert retracted["meta"]["profile"] == [f"{SD}/UpstreamRetractedObservation"]

    kept = evidence_to_observation(_event(), retracted=False)
    assert kept["meta"]["profile"] == [f"{SD}/UpstreamEvidenceObservation"]


def test_observation_carries_both_times(_network):
    """GC-4, with a lab result that arrived two days after the sample."""
    obs = evidence_to_observation(
        _event(
            method=ObservationMethod.LAB_ECOLI.value,
            result="quantitative",
            value=1840.0,
            unit="{CFU}/(100.mL)",
            _event_time=dt.datetime(2026, 9, 20, 9, 10, tzinfo=UTC),
            _recorded_at=dt.datetime(2026, 9, 22, 14, 5, tzinfo=UTC),
        ),
        retracted=False,
    )
    assert obs["effectiveDateTime"] < obs["issued"]


def test_lab_value_uses_ucum():
    obs = evidence_to_observation(
        _event(
            method=ObservationMethod.LAB_ECOLI.value,
            result="quantitative",
            value=1840.0,
            unit="{CFU}/(100.mL)",
        ),
        retracted=False,
    )
    assert obs["valueQuantity"]["system"] == "http://unitsofmeasure.org"
    assert obs["valueQuantity"]["code"] == "{CFU}/(100.mL)"


def test_ai_assisted_evidence_publishes_the_model_and_the_confirmation():
    """GC-8: the model proposed, the citizen confirmed, and both are on the record."""
    obs = evidence_to_observation(
        _event(ai_assisted=True, confirmed_by_observer=True, ai_model="claude-opus-5"),
        retracted=False,
    )
    ext = next(e for e in obs["extension"] if e["url"].endswith("upstream-ai-assisted"))
    fields = {s["url"]: s for s in ext["extension"]}
    assert fields["modelId"]["valueString"] == "claude-opus-5"
    assert fields["confirmedByObserver"]["valueBoolean"] is True


def test_evidence_without_ai_carries_no_ai_extension():
    obs = evidence_to_observation(_event(), retracted=False)
    assert not [
        e for e in obs.get("extension", []) if e["url"].endswith("upstream-ai-assisted")
    ]


def test_the_performer_is_never_a_patient():
    """GC-7: an observer is a programme or a laboratory, never a patient."""
    obs = evidence_to_observation(_event(), retracted=False)
    for performer in obs["performer"]:
        assert not performer.get("reference", "").startswith("Patient/")
    assert obs["performer"]


# --- Zones -----------------------------------------------------------------


def test_zone_to_location_names_the_zone_and_places_it(_network):
    zone_id = _network.zone_ids[0]
    loc = zone_to_location(_network, zone_id)
    assert loc["resourceType"] == "Location"
    assert loc["identifier"][0]["value"] == zone_id
    assert loc["name"]
    assert loc["mode"] == "instance"
    assert -180 <= loc["position"]["longitude"] <= 180


def test_zone_to_location_publishes_the_boundary_it_is_given(_network):
    """The compiled artefact keeps one anchor node per zone, not the polygon.

    The polygon lives in PostGIS, so the publisher reads it and hands it over;
    the mapper never reaches for a database.
    """
    zone_id = _network.zone_ids[0]
    polygon = {
        "type": "Polygon",
        "coordinates": [[[-8.43, 40.21], [-8.42, 40.21], [-8.42, 40.22], [-8.43, 40.21]]],
    }
    loc = zone_to_location(_network, zone_id, boundary=polygon)
    boundary = next(
        e for e in loc["extension"] if e["url"].endswith("location-boundary-geojson")
    )
    assert boundary["valueAttachment"]["contentType"] == "application/geo+json"
    assert json.loads(
        base64.b64decode(boundary["valueAttachment"]["data"]).decode()
    ) == polygon


def test_a_zone_with_no_polygon_publishes_no_boundary(_network):
    loc = zone_to_location(_network, _network.zone_ids[0])
    assert not [
        e
        for e in loc.get("extension", [])
        if e["url"].endswith("location-boundary-geojson")
    ]


def test_zone_to_group_is_descriptive_and_lists_no_members(_network):
    """GC-7: the group defines who would be affected; it is never a roster."""
    group = zone_to_group(_network, _network.zone_ids[0])
    assert group["actual"] is False
    assert "member" not in group
    assert group["characteristic"][0]["valueReference"]["reference"].startswith("Location/")


def test_the_group_and_the_episode_subject_agree(snap, _network):
    """A dangling subject reference would make every published episode unresolvable."""
    ra = episode_to_riskassessment(_episode(), snap, _network)
    group = zone_to_group(_network, "ZONE_A")
    assert ra["subject"]["reference"] == f"Group/{group['id']}"


# --- Provenance ------------------------------------------------------------


def test_provenance_lists_the_kernel_and_the_people_behind_the_evidence(snap):
    prov = provenance_for(
        "RiskAssessment/ee-2841-v3",
        "3",
        snap,
        ["Observation/ev-11111111"],
        agents=[
            {
                "type": {
                    "coding": [
                        {
                            "system": (
                                "http://terminology.hl7.org/CodeSystem/"
                                "provenance-participant-type"
                            ),
                            "code": "author",
                        }
                    ]
                },
                "who": {"display": "citizen-7"},
            }
        ],
    )
    roles = {a["type"]["coding"][0]["code"] for a in prov["agent"]}
    assert {"assembler", "author"} <= roles
    assert prov["target"][0]["reference"] == "RiskAssessment/ee-2841-v3/_history/3"
    assert [e["what"]["reference"] for e in prov["entity"]] == ["Observation/ev-11111111"]


def test_every_resource_declares_the_profile_it_claims_to_meet(snap, _network):
    """A resource without meta.profile is not validated against anything on write."""
    resources = [
        episode_to_riskassessment(_episode(), snap, _network),
        evidence_to_observation(_event(), retracted=False),
        zone_to_location(_network, _network.zone_ids[0]),
        zone_to_group(_network, _network.zone_ids[0]),
        provenance_for("RiskAssessment/x", "1", snap, [], agents=[]),
    ]
    for resource in resources:
        assert resource["meta"]["profile"][0].startswith(SD)


# --- Validation on write ----------------------------------------------------


@pytest.mark.integration
def test_every_generated_resource_passes_the_hl7_validator(snap, _network):
    """GC-3 / FR-26: validation on write, not only in CI.

    CI checks the profiles and the hand-written examples. This checks what the
    mapper actually produces, against the server that will store it -- the two
    can diverge, and only this test notices when they do.
    """
    from upstream_api.fhir.client import FhirClient

    client = FhirClient(os.environ.get("HAPI_BASE_URL", "http://localhost:8080/fhir"))
    resources = [
        episode_to_riskassessment(_episode(), snap, _network),
        evidence_to_observation(_event(), retracted=False),
        evidence_to_observation(_event(result="negative"), retracted=False),
        evidence_to_observation(
            _event(
                method=ObservationMethod.LAB_ECOLI.value,
                result="quantitative",
                value=1840.0,
                unit="{CFU}/(100.mL)",
            ),
            retracted=False,
        ),
        zone_to_location(_network, _network.zone_ids[0]),
        zone_to_group(_network, _network.zone_ids[0]),
    ]
    failures = {}
    for resource in resources:
        report = client.validate(resource)
        if report["issue_errors"]:
            failures[f"{resource['resourceType']}/{resource['id']}"] = report["issues"]
    assert not failures, json.dumps(failures, indent=2)[:4000]


@pytest.mark.integration
def test_the_validator_would_reject_a_resource_that_broke_the_profile():
    """Proves the test above is not passing vacuously.

    `$validate` answers with an empty OperationOutcome both when a resource is
    valid and when the server holds no profile to check it against. If Upstream's
    profiles were never loaded into HAPI, every resource would "pass" and
    validation on write would be checking nothing at all.
    """
    from upstream_api.fhir.client import FhirClient
    from upstream_api.fhir.mapper import SD

    client = FhirClient(os.environ.get("HAPI_BASE_URL", "http://localhost:8080/fhir"))
    stripped = {
        "resourceType": "RiskAssessment",
        "id": "not-an-episode",
        "meta": {"profile": [f"{SD}/UpstreamExposureEpisode"]},
        "status": "final",
    }
    report = client.validate(stripped)
    assert report["issue_errors"] > 0
    assert any(
        "UpstreamExposureEpisode" in json.dumps(issue) for issue in report["issues"]
    ), "HAPI did not check against Upstream's profile; run fhir/scripts/load-into-hapi.sh"
