"""The environmental side of the health boundary (FR-34, FR-35, GC-7).

Three routes, and each is shaped by what it must *not* carry.

`GET /clinical/episodes` tells the clinical service where and when people may have
been exposed: zone populations, exposure curves and windows. No candidate source,
no evidence, no marginals -- the clinical service tests a curve shape, and GC-12
forbids naming a polluter to anyone health-facing.

`POST /clinical/test-result` and `POST /clinical/upstream-search` are the only two
ways anything comes back. Both bodies forbid unknown fields, so a count cannot
cross this boundary even by a caller who tries: the request is refused, not
trimmed.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.ids import zone_group_id

from ..config import settings
from ..db import pool
from ..eventlog import store
from ..network import get_network
from ..security import require_roles

# Only the health zone calls these (GC-7), with a public_health service token.
router = APIRouter(prefix="/clinical", tags=["clinical"],
                   dependencies=[Depends(require_roles("public_health"))])

Stream = Literal["live", "sim"]


class TestResultIn(BaseModel):
    """FR-34: a test result, and nothing that could be read back as a count.

    `area_code` and `syndrome` say which question the p-value answers; without them
    two results for one episode would be indistinguishable. Both are aggregate
    labels the environmental side already publishes (the area is the zone's
    population Group), so neither says anything about a person.
    """

    model_config = ConfigDict(extra="forbid")

    episode_id: str
    area_code: str
    syndrome: str
    method: str
    p_value: float = Field(ge=0.0, le=1.0)
    effect_size: float | None
    n_days: int = Field(ge=1)
    computed_at: dt.datetime


class UpstreamSearchIn(BaseModel):
    """FR-35: an unexplained cluster, reduced to where, when and how surprising."""

    model_config = ConfigDict(extra="forbid")

    area_code: str
    syndrome: str
    day: dt.date
    p_value: float = Field(ge=0.0, le=1.0)
    method: str


@router.get("/episodes")
def clinical_episodes(stream: Stream = "live"):
    """Episodes a clinical test could still say something about.

    The same rule the CDS card uses: PROBABLE or CONFIRMED, and still inside the
    clinical relevance window. A SUSPECTED episode is one unconfirmed report, and
    testing hospital data against it would spend the health zone's attention on noise.
    """
    net = get_network()
    population = {z: int(p) for z, p in zip(net.zone_ids, net.zone_population, strict=False)}
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT episode_id, state, opened_at, clinical_window_end, summary
                       FROM episodes WHERE catchment_id=%s AND stream=%s
                         AND state IN ('PROBABLE','CONFIRMED')
                         AND clinical_window_end > now()
                       ORDER BY opened_at""", (settings.catchment_id, stream))
        rows = cur.fetchall()
        # The curves live in the belief record; `episodes.summary` keeps only windows.
        cur.execute("""SELECT zone_windows FROM posterior_snapshots
                       WHERE catchment_id=%s AND stream=%s ORDER BY ts DESC LIMIT 1""",
                    (settings.catchment_id, stream))
        snap = cur.fetchone()
    curves = (snap[0] if snap else None) or {}

    out = []
    for episode_id, state, opened_at, window_end, summary in rows:
        zones = {}
        for zone_id, window in ((summary or {}).get("zone_windows") or {}).items():
            curve = curves.get(zone_id) or window or {}
            if not curve.get("t_grid"):
                continue                      # no curve, no shape to test for
            zones[zone_id] = {
                "area_code": zone_group_id(zone_id),
                "population": population.get(zone_id),
                "t_grid": curve["t_grid"],
                "p_exposed": curve["p_exposed"],
                "window_lo": curve.get("window_lo"),
                "window_hi": curve.get("window_hi"),
                "pathways": curve.get("pathways", []),
            }
        out.append({"episode_id": episode_id, "state": state, "opened_at": opened_at,
                    "clinical_window_end": window_end, "zones": zones})
    return {"episodes": out}


@router.post("/test-result", status_code=201)
def clinical_test_result(body: TestResultIn, stream: Stream = "live"):
    """Append a ClinicalTestResult. The payload is the body, verbatim, and nothing more."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM episodes WHERE episode_id=%s AND stream=%s",
                    (body.episode_id, stream))
        if cur.fetchone() is None:
            raise HTTPException(404, f"no such episode: {body.episode_id}")
    env = EventEnvelope(stream=stream, catchment_id=settings.catchment_id,
                        event_type=EventType.CLINICAL_TEST_RESULT,
                        event_time=_not_future(body.computed_at),
                        payload=body.model_dump(mode="json"))
    return {"seq": store.append(env), "event_id": str(env.event_id)}


@router.post("/upstream-search", status_code=201)
def upstream_search(body: UpstreamSearchIn, stream: Stream = "live"):
    """Ask the environmental side to look upstream of an area it has no episode for.

    The area is resolved back to its zone here, on the environmental side, so the
    request carries the node the kernel would search from. An area this catchment
    does not know is refused rather than logged as a request nobody can act on.
    """
    zone_id = _zone_for_area(body.area_code)
    if zone_id is None:
        raise HTTPException(404, f"no receptor zone publishes area {body.area_code!r}")
    net = get_network()
    node_id = net.node_ids[int(net.zone_node_idx[list(net.zone_ids).index(zone_id)])]
    env = EventEnvelope(stream=stream, catchment_id=settings.catchment_id,
                        event_type=EventType.UPSTREAM_SEARCH_REQUESTED,
                        event_time=dt.datetime.now(dt.UTC),
                        payload={**body.model_dump(mode="json"),
                                 "zone_id": zone_id, "search_from_node": node_id})
    return {"seq": store.append(env), "event_id": str(env.event_id), "zone_id": zone_id}


def _zone_for_area(area_code: str) -> str | None:
    for zone_id in get_network().zone_ids:
        if zone_group_id(zone_id) == area_code:
            return zone_id
    return None


def _not_future(ts: dt.datetime) -> dt.datetime:
    # The two services' clocks are not the same clock. A result stamped a few
    # seconds ahead is still a result; EventEnvelope's plausibility check is for
    # evidence, and would refuse it.
    if ts.tzinfo is None:
        raise HTTPException(422, "computed_at must be timezone-aware")
    return min(ts, dt.datetime.now(dt.UTC))
