"""FR-32: accept aggregate syndrome counts as a MeasureReport. Suppress small ones.

Nothing here can accept a patient-level resource. The route takes a
MeasureReport and rejects anything else; it rejects an individual report, a
report whose subject is a Patient, and a report carrying `evaluatedResource`
(the field that would point at the records behind the count). And the schema's
`CHECK (count >= 5)` makes a suppressed value unstorable even by mistake.

Rejections are deliberately loud. A boundary that silently drops what it does
not understand teaches its callers nothing, and the caller here is a health
system that needs to know its feed was refused.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, HTTPException

from .db import conn

router = APIRouter(tags=["clinical"])

# PRD 14.1. Below this, an area-and-day count is re-identifiable, so it is not
# stored at all rather than stored and hidden.
SUPPRESSION_THRESHOLD = 5


@router.post("/counts")
def post_counts(measure_report: dict, stream: Literal["live", "sim"] = "live") -> dict:
    return ingest_measure_report(measure_report, stream=stream)


def ingest_measure_report(mr: dict, *, stream: str = "live") -> dict:
    """Store the acceptable counts in a report. Returns what happened to each."""
    _reject_anything_patient_level(mr)

    area = _area_code(mr)
    day = _period_start(mr)

    accepted = suppressed = 0
    for group in mr.get("group") or []:
        syndrome = _syndrome(group)
        value = (group.get("measureScore") or {}).get("value")
        # An absent score means the publisher suppressed it. Storing zero would
        # be a claim that nobody presented, which is a different thing entirely.
        if value is None or value < SUPPRESSION_THRESHOLD:
            suppressed += 1
            continue
        _store(day, area, syndrome, int(value), stream)
        accepted += 1

    return {"accepted": accepted, "suppressed": suppressed}


def _reject_anything_patient_level(mr: dict) -> None:
    if mr.get("resourceType") != "MeasureReport":
        raise HTTPException(400, "only MeasureReport is accepted at this boundary")
    if mr.get("type") != "summary":
        raise HTTPException(
            400, f"only aggregate (summary) reports are accepted, not {mr.get('type')!r} (GC-7)"
        )

    subject = (mr.get("subject") or {}).get("reference", "")
    if not subject.startswith("Group/"):
        raise HTTPException(
            400, "the subject of an accepted report is a Group, never a Patient (GC-7)"
        )
    if mr.get("evaluatedResource"):
        raise HTTPException(
            400,
            "evaluatedResource points at the records behind a count and is not accepted (GC-7)",
        )


def _area_code(mr: dict) -> str:
    area = (mr.get("subject") or {}).get("reference", "").split("/")[-1]
    if not area:
        raise HTTPException(400, "the report names no area")
    return area


def _period_start(mr: dict) -> dt.date:
    start = (mr.get("period") or {}).get("start")
    if not start:
        raise HTTPException(400, "the report names no period")
    try:
        return dt.date.fromisoformat(str(start)[:10])
    except ValueError as exc:
        raise HTTPException(400, f"unreadable period start {start!r}") from exc


def _syndrome(group: dict) -> str:
    codings = ((group.get("code") or {}).get("coding")) or []
    for coding in codings:
        if coding.get("code"):
            return str(coding["code"])
    raise HTTPException(400, "each group must name the syndrome it counts")


def _store(day: dt.date, area: str, syndrome: str, count: int, stream: str) -> None:
    # A corrected feed for a day it already sent replaces that day, rather than
    # adding a second row that would double it.
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO syndromic_counts (stream, day, area_code, syndrome, count, source) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (stream, day, area_code, syndrome) "
            "DO UPDATE SET count = EXCLUDED.count, received_at = now()",
            (stream, day, area, syndrome, count, "measure-report"),
        )
