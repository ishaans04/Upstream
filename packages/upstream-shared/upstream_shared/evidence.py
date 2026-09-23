"""Evidence payloads.

The two validators here are load-bearing policy, not hygiene. GC-8 (the model
proposes, the human confirms) and GC-13 (a quantitative result carries a UCUM
unit) are enforced at the schema boundary so that no producer can skip them.
"""
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from .codes import ObservationMethod


class ObservationResult(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    QUANTITATIVE = "quantitative"


class EvidencePayload(BaseModel):
    node_id: str
    method: ObservationMethod
    result: ObservationResult
    value: float | None = None
    unit: str | None = None                       # UCUM (GC-13)
    observer_id: str
    observer_type: str                            # citizen|officer|sensor|lab
    snap_distance_m: float = Field(ge=0)
    oah_codes: list[str] = Field(default_factory=list)
    ai_assisted: bool = False
    confirmed_by_observer: bool = False
    photo_uri: str | None = None
    mission_id: str | None = None
    window_start: str | None = None               # sensor "normal for this window" evidence
    window_end: str | None = None

    @model_validator(mode="after")
    def _rules(self):
        if self.ai_assisted and not self.confirmed_by_observer:
            raise ValueError("GC-8: AI-assisted evidence requires observer confirmation")
        if self.result is ObservationResult.QUANTITATIVE and (self.value is None or not self.unit):
            raise ValueError("quantitative results need value and a UCUM unit")
        return self


class RetractionPayload(BaseModel):
    """GC-5: a retraction is a new event, never a delete."""

    retracts_event_id: str
    reason: str
    retracted_by: str
