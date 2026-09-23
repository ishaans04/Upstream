"""The episode consumer: what actually drives the lifecycle in production.

The kernel writes `PosteriorComputed` and stops there (PRD 10.3). Something has to read
those events and decide, and that something needs a durable position in the log: an API
restart must resume where it left off, not replay two days of belief as though it were
new and reopen every episode it finds.

`consumer_positions` is the same mechanism the kernel uses for its own cursor, so both
sides of the boundary recover the same way.
"""
from __future__ import annotations

import logging

from upstream_shared.events import EventType

from ..config import settings
from ..db import pool
from ..eventlog import store
from .episode import on_posterior_computed

log = logging.getLogger(__name__)

CONSUMER = "episodes"
BATCH = 500


def process_new_posteriors(*, stream: str = "live") -> int:
    """Consume every PosteriorComputed event since the stored position. Returns the count.

    The position advances past events of every type, not only the ones acted on;
    otherwise the cursor would stall behind the first piece of evidence in the log and
    re-read it forever.
    """
    last = _position()
    events = store.read_from(last, catchment_id=settings.catchment_id, stream=stream,
                             limit=BATCH)
    if not events:
        return 0
    handled = 0
    for event in events:
        if event.event_type is not EventType.POSTERIOR_COMPUTED:
            continue
        try:
            on_posterior_computed(event)
            handled += 1
        except Exception:
            # NFR-8: one malformed posterior must not wedge the lifecycle for every
            # later one. The event stays in the log and the position still advances,
            # so this is visible in the logs rather than silently retried forever.
            log.exception("episode consumer failed on event %s", event.event_id)
    _set_position(events[-1].seq)
    return handled


def _position() -> int:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT last_seq FROM consumer_positions WHERE consumer=%s", (CONSUMER,))
        row = cur.fetchone()
    return row[0] if row else 0


def _set_position(seq: int) -> None:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO consumer_positions (consumer,last_seq,updated_at)
                       VALUES (%s,%s,now()) ON CONFLICT (consumer)
                       DO UPDATE SET last_seq=EXCLUDED.last_seq, updated_at=now()""",
                    (CONSUMER, seq))
