"""PRD 7.7: the recurring-source report, for the environmental agency.

Closed episodes of one stream are pooled (upstream_kernel.pooling); an outfall that
keeps turning up is reported as a place to inspect. It is never a finding against
anyone (GC-12, PRD 14.4): a recurring discharge at an outfall is as often a
misconnected house or a failing overflow as it is a party at fault.

The report is computed on request. Once a day the same report is also appended to the
event log, so what was recommended, and when, stays on record (GC-5).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from upstream_kernel.pooling import MIN_EPISODES, RHO, pool_closed_episodes
from upstream_shared.events import EventEnvelope, EventType

from ..config import settings
from ..db import pool
from ..eventlog import store
from ..network import get_network
from ..security import require_roles

router = APIRouter(tags=["reports"])

NOT_A_FINDING = ("A place to inspect, not a finding of fault. Recurring discharges at an "
                 "outfall are often a misconnected drain or a failing overflow.")
METHOD = (f"Closed episodes (confirmed or resolved) pooled under a mixture model: each "
          f"episode came from a recurring source with probability {RHO}, otherwise from "
          f"the usual background of sources. Reported when at least {MIN_EPISODES} "
          f"episodes implicate the same outfall.")
NIGHTLY_LOCAL_HOUR = 2


def _outfalls() -> dict[str, tuple[str, bool]]:
    """node_id -> (outfall_id, is_synthetic) for the current network."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT node_id, outfall_id, is_synthetic FROM outfalls "
                    "WHERE network_version=%s", (get_network().version,))
        return {r[0]: (r[1], bool(r[2])) for r in cur.fetchall()}


def recurring_sources(stream: str, since_days: int = 365) -> dict:
    outfalls = _outfalls()
    with pool.connection() as c:
        found = pool_closed_episodes(c, get_network(), settings.catchment_id, stream,
                                     since_days=since_days,
                                     labels={n: o for n, (o, _) in outfalls.items()})
    sources = []
    for r in found:
        outfall_id, synthetic = outfalls.get(r.entry_id, (r.entry_id, False))
        sources.append({**{k: v for k, v in dataclasses.asdict(r).items() if k != "entry_id"},
                        "node_id": r.entry_id, "outfall_id": outfall_id,
                        "is_synthetic": synthetic})
    return {"catchment_id": settings.catchment_id, "stream": stream,
            "since_days": since_days, "generated_at": dt.datetime.now(dt.UTC),
            "method": METHOD, "notice": NOT_A_FINDING, "sources": sources}


@router.get("/reports/recurring-sources",
            dependencies=[Depends(require_roles("agency", "officer"))])
def get_recurring_sources(stream: str = "live", since_days: int = Query(365, ge=1, le=3650)):
    return recurring_sources(stream, since_days)


def record_recurring_sources(stream: str, *, day: dt.date) -> bool:
    """Append the day's report to the log, once per day and stream. True if it did."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT 1 FROM events WHERE event_type=%s AND catchment_id=%s
                         AND stream=%s AND payload->>'report_date'=%s LIMIT 1""",
                    (EventType.RECURRING_SOURCES_REPORTED.value, settings.catchment_id,
                     stream, day.isoformat()))
        if cur.fetchone():
            return False
    report = recurring_sources(stream)
    store.append(EventEnvelope(
        stream=stream, catchment_id=settings.catchment_id,
        event_type=EventType.RECURRING_SOURCES_REPORTED, event_time=report["generated_at"],
        payload={"report_date": day.isoformat(), "method": METHOD, "notice": NOT_A_FINDING,
                 "sources": [{**s, "first_seen": s["first_seen"].isoformat(),
                              "last_seen": s["last_seen"].isoformat()}
                             for s in report["sources"]]}))
    return True


def nightly_due(now: dt.datetime, tz: str) -> dt.date | None:
    """The local date whose report is due at `now`, or None before 02:00."""
    local = now.astimezone(ZoneInfo(tz))
    return local.date() if local.hour >= NIGHTLY_LOCAL_HOUR else None
