"""Mission specs produced by PROBE and carried to the field app."""
import datetime as dt
from enum import StrEnum

from pydantic import BaseModel

from .codes import ObservationMethod


class MissionStatus(StrEnum):
    CREATED = "created"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    EXPIRED = "expired"
    DECLINED = "declined"


class ProbeMode(StrEnum):
    PROTECT = "protect"
    ENFORCE = "enforce"


class MissionSpec(BaseModel):
    mission_id: str
    episode_id: str
    node_id: str
    window_start: dt.datetime
    window_end: dt.datetime
    methods: list[ObservationMethod]
    mode: ProbeMode
    expected_gain: float
    human_summary: str            # e.g. "Check Junction J4 between 02:22 and 02:39"
