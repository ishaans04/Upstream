"""Mission endpoints for the field PWA (FR-38).

`/missions/mine` is scoped to one volunteer and returns only what they can still act
on. The completion response carries the measured effect of the trip rather than a
thank-you, which is the whole point of G7.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import pool
from ..workflows.missions import (
    OPEN_STATUSES,
    accept_mission,
    complete_mission,
    decline_mission,
    get_mission_feedback,
)

router = APIRouter(prefix="/missions", tags=["missions"])

_COLS = ("mission_id", "episode_id", "node_id", "window_start", "window_end", "methods",
         "mode", "status", "expected_gain", "realised_gain", "assignee_id")


class VolunteerIn(BaseModel):
    volunteer_id: str


class CompleteIn(BaseModel):
    evidence_event_id: str


@router.get("/mine")
def my_missions(volunteer_id: str, include_closed: bool = False):
    sql = f"SELECT {','.join(_COLS)} FROM missions WHERE assignee_id=%s"
    args: list = [volunteer_id]
    if not include_closed:
        sql += " AND status = ANY(%s)"
        args.append(list(OPEN_STATUSES))
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(sql + " ORDER BY window_start", args)
        return [dict(zip(_COLS, r, strict=True)) for r in cur.fetchall()]


@router.post("/{mission_id}/accept")
def accept(mission_id: str, body: VolunteerIn):
    return _act(accept_mission, mission_id, body.volunteer_id, status="accepted")


@router.post("/{mission_id}/decline")
def decline(mission_id: str, body: VolunteerIn):
    return _act(decline_mission, mission_id, body.volunteer_id, status="declined")


@router.post("/{mission_id}/complete")
def complete(mission_id: str, body: CompleteIn):
    try:
        complete_mission(mission_id, body.evidence_event_id)
    except KeyError as e:
        raise HTTPException(404, f"no such mission: {mission_id}") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return get_mission_feedback(mission_id)


def _act(fn, mission_id: str, volunteer_id: str, *, status: str) -> dict:
    """A mission that is expired or already taken is a conflict, not a bad request."""
    try:
        fn(mission_id, volunteer_id)
    except KeyError as e:
        raise HTTPException(404, f"no such mission: {mission_id}") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"mission_id": mission_id, "status": status}
