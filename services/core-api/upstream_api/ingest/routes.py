"""Everything that turns the outside world into events.

Two rules shape this module. A proposal never enters the log - only a confirmation
does (GC-8). And nothing is ever deleted: a retraction is a new event that points at
the one it retracts (GC-5).

Ingestion deliberately depends on the log and nothing else, so reports are still
accepted when the kernel is down (NFR-8).
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from upstream_shared.codes import ObservationMethod
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.evidence import EvidencePayload, ObservationResult, RetractionPayload

from ..config import settings
from ..db import pool
from ..eventlog import store
from ..network import snap
from .normaliser import get_normaliser

router = APIRouter(prefix="/ingest", tags=["ingest"])


class ProposeIn(BaseModel):
    lon: float
    lat: float
    observed_at: dt.datetime
    free_text: str = ""
    photo_uri: str | None = None


class ConfirmIn(BaseModel):
    node_id: str
    observed_at: dt.datetime
    method: ObservationMethod
    result: ObservationResult
    value: float | None = None
    unit: str | None = None
    observer_id: str
    observer_type: str
    snap_distance_m: float
    oah_codes: list[str] = []
    ai_assisted: bool = False
    confirmed_by_observer: bool = False
    photo_uri: str | None = None
    mission_id: str | None = None


class LabIn(BaseModel):
    """A lab result is not a field observation.

    It carries no `result` (it is quantitative by definition) and no snap distance:
    the sample is tied to a node id by the chain of custody, not by a GPS fix.
    """

    node_id: str
    observed_at: dt.datetime
    method: ObservationMethod
    value: float
    unit: str                                     # UCUM (GC-13)
    observer_id: str
    observer_type: str = "lab"
    snap_distance_m: float = 0.0
    oah_codes: list[str] = []
    mission_id: str | None = None


class RetractIn(BaseModel):
    """The documented request shape for FR-10 is {event_id, reason}."""

    event_id: str
    reason: str
    retracted_by: str


def _validation_detail(e: ValidationError):
    """Make a pydantic error safe to put in an HTTP response body.

    Two things bite here. `ctx` holds the original exception object, and `input` holds
    the raw value - a datetime, an enum - and neither survives JSONResponse's json.dumps.
    Handing `e.errors()` straight to HTTPException turns a clean 422 into a 500.
    """
    return jsonable_encoder(e.errors(include_url=False, include_context=False))


@router.post("/report/propose")
def propose(body: ProposeIn):
    """FR-3: AI proposes fields. Appends nothing to the log (GC-8)."""
    try:
        node_id, dist = snap(body.lon, body.lat)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    proposal = get_normaliser().propose(body.free_text, None, None)
    return {"snapped_node_id": node_id, "snap_distance_m": dist,
            "proposal": proposal.model_dump(),
            "confirm_prompt": proposal.rationale,
            "notice": "These fields are a suggestion. Please confirm or correct them."}


@router.post("/report/confirm", status_code=201)
def confirm(body: ConfirmIn):
    """FR-1, FR-2, FR-3: record confirmed evidence, positive or negative."""
    return _append_evidence(body)


@router.post("/lab", status_code=201)
def lab_result(body: LabIn):
    """FR-9: lab results, including ones that arrive days later (GC-4)."""
    confirmed = ConfirmIn(**body.model_dump(),
                          result=ObservationResult.QUANTITATIVE,
                          confirmed_by_observer=True)
    return _append_evidence(confirmed)


@router.post("/retract", status_code=201)
def retract(body: RetractIn):
    """FR-10: retraction is a new event, never a delete (GC-5)."""
    payload = RetractionPayload(retracts_event_id=body.event_id, reason=body.reason,
                                retracted_by=body.retracted_by)
    try:
        causation = uuid.UUID(body.event_id)
    except ValueError as e:
        raise HTTPException(422, f"event_id is not a UUID: {body.event_id}") from e
    env = EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                        event_type=EventType.EVIDENCE_RETRACTED,
                        event_time=dt.datetime.now(dt.UTC),
                        payload=payload.model_dump(),
                        causation_id=causation)
    return {"seq": store.append(env), "event_id": str(env.event_id)}


class SensorIn(BaseModel):
    sensor_id: str
    node_id: str
    ts: dt.datetime
    parameter: str
    value: float
    unit: str
    stream: str = "live"


@router.post("/sensor", status_code=201)
def sensor(body: SensorIn):
    """FR-6: raw readings land in the hypertable; derived evidence comes from sensor_job."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("INSERT INTO sensor_readings (ts,sensor_id,node_id,catchment_id,stream,"
                    "parameter,value,unit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (body.ts, body.sensor_id, body.node_id, settings.catchment_id,
                     body.stream, body.parameter, body.value, body.unit))
    return {"ok": True}


class RainfallIn(BaseModel):
    ts: dt.datetime
    mm_per_h: float
    antecedent_dry_h: float | None = None
    stream: str = "live"


@router.post("/rainfall", status_code=201)
def rainfall(body: RainfallIn):
    """FR-7: rainfall every 15 minutes, with the derived flow condition (PRD 7.9)."""
    cond = flow_condition(body.mm_per_h)
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("INSERT INTO rainfall (ts,catchment_id,stream,mm_per_h,antecedent_dry_h,"
                    "flow_condition) VALUES (%s,%s,%s,%s,%s,%s)",
                    (body.ts, settings.catchment_id, body.stream, body.mm_per_h,
                     body.antecedent_dry_h, cond))
    env = EventEnvelope(stream=body.stream, catchment_id=settings.catchment_id,
                        event_type=EventType.RAINFALL_OBSERVED, event_time=body.ts,
                        payload={"mm_per_h": body.mm_per_h, "flow_condition": cond,
                                 "antecedent_dry_h": body.antecedent_dry_h})
    return {"seq": store.append(env), "flow_condition": cond}


class OverflowIn(BaseModel):
    outfall_id: str
    node_id: str
    ts: dt.datetime
    active: bool


@router.post("/overflow", status_code=201)
def overflow(body: OverflowIn):
    """FR-8: an overflow activation is both a signal and a piece of evidence."""
    env = EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                        event_type=EventType.OVERFLOW_ACTIVATED, event_time=body.ts,
                        payload=body.model_dump(mode="json"))
    seq = store.append(env)
    ev = EvidencePayload(node_id=body.node_id, method=ObservationMethod.OVERFLOW_TELEMETRY,
                         result=ObservationResult.POSITIVE if body.active
                         else ObservationResult.NEGATIVE,
                         observer_id=body.outfall_id, observer_type="sensor",
                         snap_distance_m=0.0, confirmed_by_observer=True)
    store.append(EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                               event_type=EventType.EVIDENCE_RECORDED, event_time=body.ts,
                               payload=ev.model_dump(mode="json"), causation_id=env.event_id))
    return {"seq": seq}


def flow_condition(mm_per_h: float) -> str:
    """PRD 7.9 role 2: rainfall selects the precomputed table."""
    if mm_per_h >= 10.0:
        return "storm"
    if mm_per_h >= 1.0:
        return "wet"
    return "dry"


def _append_evidence(body: ConfirmIn) -> dict:
    """Append confirmed evidence and return both of its identities.

    The sequence number orders the log; the event id is what everything downstream
    refers to a single observation by. Officer sign-off (FR-21) needs the id, so
    returning only the seq made the documented workflow impossible to perform from
    the API.
    """
    try:
        payload = EvidencePayload(**body.model_dump(exclude={"observed_at"}))
    except ValidationError as e:
        raise HTTPException(422, _validation_detail(e)) from e
    try:
        env = EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                            event_type=EventType.EVIDENCE_RECORDED,
                            event_time=body.observed_at,
                            payload=payload.model_dump(mode="json"))
    except ValidationError as e:
        raise HTTPException(422, _validation_detail(e)) from e
    return {"seq": store.append(env), "event_id": str(env.event_id)}
