"""FR-37 Belief replay: what did the system believe at any past moment?

PRD 12.5: 'select the latest snapshot with ts <= the chosen moment'. The strictness
matters more than it looks. This endpoint is the evidence for every claim the project
makes about what it knew and when; a slider that quietly showed a later belief than the
moment it names would make all of those claims unfalsifiable.

So there is no nearest-neighbour fallback and no "closest available" behaviour: ask for
a moment before the first snapshot and you get a 404, because the honest answer is that
nothing was believed yet.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..db import pool

router = APIRouter(tags=["replay"])

_SNAPSHOT_COLS = ["ts", "fingerprint", "as_of_seq", "p_event", "source_marginals",
                  "zone_windows", "probe_candidates", "explanation", "kernel_version",
                  "network_version", "params_version"]


@router.get("/replay")
def replay(at: dt.datetime, stream: str = "live"):
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(f"""SELECT {','.join(_SNAPSHOT_COLS)}
                        FROM posterior_snapshots
                        WHERE catchment_id=%s AND stream=%s AND ts <= %s
                        ORDER BY ts DESC LIMIT 1""", (settings.catchment_id, stream, at))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "no belief recorded before that moment")
    return dict(zip(_SNAPSHOT_COLS, row, strict=True))


@router.get("/replay/timeline")
def timeline(stream: str = "live", limit: int = 500):
    """Every snapshot's moment and headline probability: the Phase 10 slider's track."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT ts, p_event, fingerprint FROM posterior_snapshots
                       WHERE catchment_id=%s AND stream=%s ORDER BY ts LIMIT %s""",
                    (settings.catchment_id, stream, limit))
        return [{"ts": r[0], "p_event": r[1], "fingerprint": r[2]} for r in cur.fetchall()]
