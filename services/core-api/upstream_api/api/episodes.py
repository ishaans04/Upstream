"""Episode read APIs and officer sign-off (FR-36, FR-21, FR-39, GC-12).

Two audiences, two shapes. `/episodes` is the operations console: it names candidate
sources because acting on an episode means going to look at one. `/public-health/...`
is the clinical view, and it deliberately carries none of that - GC-12 forbids naming a
polluter, and a clinician does not need to know which outfall is suspected to interpret
a patient's exposure window.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..db import pool
from ..workflows.episode import give_signoff, request_signoff

router = APIRouter(tags=["episodes"])

NOT_A_DIAGNOSIS = "Environmental context, not a diagnosis."     # GC-12, verbatim
EVIDENCE_HORIZON_HOURS = 24


class SignoffIn(BaseModel):
    officer_id: str
    field_result_event_id: str | None = None


class SignoffRequestIn(BaseModel):
    reason: str


@router.get("/episodes")
def list_episodes(stream: str = "live", limit: int = 100):
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT episode_id, state, opened_at, state_changed_at,
                              clinical_window_end, summary, latest_fingerprint
                       FROM episodes WHERE catchment_id=%s AND stream=%s
                       ORDER BY opened_at DESC LIMIT %s""",
                    (settings.catchment_id, stream, limit))
        rows = cur.fetchall()
    return [{"episode_id": r[0], "state": r[1], "opened_at": r[2], "state_changed_at": r[3],
             "clinical_window_end": r[4], "p_event": (r[5] or {}).get("p_event"),
             "top_sources": (r[5] or {}).get("top_sources", []),
             "zone_windows": (r[5] or {}).get("zone_windows", {}),
             "fingerprint": r[6]} for r in rows]


@router.get("/episodes/{episode_id}")
def get_episode(episode_id: str, stream: str = "live"):
    """One episode with the belief behind it and the evidence it was built from."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT episode_id, state, stream, opened_at, state_changed_at,
                              est_start_lo, est_start_hi, clinical_window_end, summary,
                              latest_fingerprint, version
                       FROM episodes WHERE episode_id=%s""", (episode_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"no such episode: {episode_id}")
        summary = row[8] or {}
        cur.execute("""SELECT explanation, source_marginals, probe_candidates, ts
                       FROM posterior_snapshots WHERE catchment_id=%s AND stream=%s
                       ORDER BY ts DESC LIMIT 1""", (settings.catchment_id, row[2]))
        snap = cur.fetchone()
        cur.execute("""SELECT event_id, event_type, event_time, recorded_at, payload
                       FROM events WHERE catchment_id=%s AND stream=%s
                         AND event_type IN ('EvidenceRecorded','EvidenceRetracted')
                         AND event_time >= %s ORDER BY seq""",
                    (settings.catchment_id, row[2],
                     row[3] - dt.timedelta(hours=EVIDENCE_HORIZON_HOURS)))
        evidence = cur.fetchall()
    return {
        "episode_id": row[0], "state": row[1], "stream": row[2], "opened_at": row[3],
        "state_changed_at": row[4], "est_start_lo": row[5], "est_start_hi": row[6],
        "clinical_window_end": row[7], "p_event": summary.get("p_event"),
        "top_sources": summary.get("top_sources", []),
        "zone_windows": summary.get("zone_windows", {}),
        "fingerprint": row[9], "version": row[10],
        "explanation": (snap[0] if snap else {}) or {},
        "source_marginals": (snap[1] if snap else {}) or {},
        "probe_candidates": (snap[2] if snap else []) or [],
        "belief_ts": snap[3] if snap else None,
        "evidence": [{"event_id": str(e[0]), "event_type": e[1], "event_time": e[2],
                      "recorded_at": e[3], "payload": e[4]} for e in evidence],
        "notice": NOT_A_DIAGNOSIS,
    }


@router.post("/episodes/{episode_id}/signoff")
def signoff(episode_id: str, body: SignoffIn):
    """FR-21. The workflow is the authority; this turns its refusals into status codes."""
    try:
        give_signoff(episode_id, body.officer_id, body.field_result_event_id)
    except KeyError as e:
        raise HTTPException(404, f"no such episode: {episode_id}") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except PermissionError as e:
        raise HTTPException(409, str(e)) from e
    return {"episode_id": episode_id, "state": "CONFIRMED", "officer_id": body.officer_id}


@router.post("/episodes/{episode_id}/signoff/request")
def ask_for_signoff(episode_id: str, body: SignoffRequestIn):
    try:
        request_signoff(episode_id, body.reason)
    except KeyError as e:
        raise HTTPException(404, f"no such episode: {episode_id}") from e
    return {"episode_id": episode_id, "requested": True}


@router.get("/public-health/episodes")
def public_health_episodes(stream: str = "live", limit: int = 100):
    """FR-39: the clinical view.

    Exposure windows and pathways only. No candidate source, no marginals, no evidence:
    GC-12 forbids naming a polluter, and every record carries the notice verbatim.
    """
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT episode_id, state, opened_at, clinical_window_end, summary
                       FROM episodes WHERE catchment_id=%s AND stream=%s
                         AND state IN ('PROBABLE','CONFIRMED','RESOLVED')
                       ORDER BY opened_at DESC LIMIT %s""",
                    (settings.catchment_id, stream, limit))
        rows = cur.fetchall()
    episodes = []
    for episode_id, state, opened_at, window_end, summary in rows:
        zone_windows = (summary or {}).get("zone_windows", {})
        pathways = sorted({p for w in zone_windows.values()
                           if isinstance(w, dict) for p in w.get("pathways", [])})
        episodes.append({"episode_id": episode_id, "state": state, "opened_at": opened_at,
                         "clinical_window_end": window_end, "zone_windows": zone_windows,
                         "pathways": pathways, "notice": NOT_A_DIAGNOSIS})
    return {"notice": NOT_A_DIAGNOSIS, "episodes": episodes}
