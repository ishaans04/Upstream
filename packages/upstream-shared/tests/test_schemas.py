import datetime as dt

import pytest
from pydantic import ValidationError
from upstream_shared.episode import EpisodeState
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.evidence import EvidencePayload, ObservationResult


def test_evidence_payload_roundtrip():
    p = EvidencePayload(node_id="J4", method="citizen_visual_olfactory",
                        result=ObservationResult.NEGATIVE, observer_id="vol-1182",
                        observer_type="citizen", snap_distance_m=12.5,
                        oah_codes=["OAH-IND-001"], ai_assisted=True, confirmed_by_observer=True)
    assert EvidencePayload.model_validate(p.model_dump()) == p


def test_ai_assisted_requires_confirmation():
    """GC-8: AI-assisted evidence is unusable until the observer confirms."""
    with pytest.raises(ValidationError):
        EvidencePayload(node_id="J4", method="citizen_freetext",
                        result=ObservationResult.POSITIVE, observer_id="v1",
                        observer_type="citizen", snap_distance_m=1.0,
                        ai_assisted=True, confirmed_by_observer=False)


def test_quantitative_result_requires_value_and_unit():
    with pytest.raises(ValidationError):
        EvidencePayload(node_id="J4", method="lab_ecoli",
                        result=ObservationResult.QUANTITATIVE, observer_id="lab-1",
                        observer_type="lab", snap_distance_m=0.0)


def test_envelope_rejects_future_event_time():
    with pytest.raises(ValidationError):
        EventEnvelope(stream="live", catchment_id="c1",
                      event_type=EventType.EVIDENCE_RECORDED, schema_version=1,
                      event_time=dt.datetime.now(dt.UTC) + dt.timedelta(hours=2), payload={})


def test_episode_state_transitions_match_prd():
    assert EpisodeState.SUSPECTED.can_transition_to(EpisodeState.PROBABLE)
    assert EpisodeState.SUSPECTED.can_transition_to(EpisodeState.REFUTED)
    assert not EpisodeState.SUSPECTED.can_transition_to(EpisodeState.CONFIRMED)
    assert not EpisodeState.RESOLVED.can_transition_to(EpisodeState.PROBABLE)
