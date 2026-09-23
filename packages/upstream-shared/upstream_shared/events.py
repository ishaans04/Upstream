"""The event envelope every producer writes and every consumer reads.

GC-4 is why `event_time` is required and separate from the log's `recorded_at`:
when something happened and when the system learned it are different facts, and
belief replay needs both.
"""
import datetime as dt
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class EventType(StrEnum):
    EVIDENCE_RECORDED = "EvidenceRecorded"
    EVIDENCE_RETRACTED = "EvidenceRetracted"
    RAINFALL_OBSERVED = "RainfallObserved"
    OVERFLOW_ACTIVATED = "OverflowActivated"
    POSTERIOR_COMPUTED = "PosteriorComputed"
    EPISODE_OPENED = "EpisodeOpened"
    EPISODE_STATE_CHANGED = "EpisodeStateChanged"
    SIGN_OFF_REQUESTED = "SignOffRequested"
    SIGN_OFF_GIVEN = "SignOffGiven"
    MISSION_CREATED = "MissionCreated"
    MISSION_ACCEPTED = "MissionAccepted"
    MISSION_COMPLETED = "MissionCompleted"
    MISSION_EXPIRED = "MissionExpired"
    FHIR_PUBLISHED = "FhirPublished"
    CLINICAL_TEST_RESULT = "ClinicalTestResult"
    UPSTREAM_SEARCH_REQUESTED = "UpstreamSearchRequested"
    NETWORK_VERSION_PUBLISHED = "NetworkVersionPublished"
    PARAMETERS_VERSION_PUBLISHED = "ParametersVersionPublished"


MAX_CLOCK_SKEW = dt.timedelta(minutes=5)


class EventEnvelope(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    stream: str
    catchment_id: str
    event_type: EventType
    schema_version: int = 1
    event_time: dt.datetime                       # GC-4
    payload: dict
    causation_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None

    @field_validator("event_time")
    @classmethod
    def _not_future(cls, v: dt.datetime) -> dt.datetime:
        if v.tzinfo is None:
            raise ValueError("event_time must be timezone-aware")
        if v > dt.datetime.now(dt.UTC) + MAX_CLOCK_SKEW:
            raise ValueError("event_time is in the future (FR-5 plausibility check)")
        return v

    @field_validator("stream")
    @classmethod
    def _known_stream(cls, v: str) -> str:
        if v not in ("live", "sim"):
            raise ValueError("stream must be one of: live, sim")
        return v
