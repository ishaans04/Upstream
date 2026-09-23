"""Web Push to the mission PWA (FR-38).

VAPID keys are generated locally - see the Phase 6 key table - so no third-party account
is involved: the browser's own push service does the delivery.

Nothing in here raises. A mission that was created is a fact in the log; failing to
announce it is a delivery problem, and losing the mission because the push service was
unreachable would be strictly worse than a volunteer not hearing about it.
"""
from __future__ import annotations

import json
import logging

from pywebpush import WebPushException, webpush

from .config import settings
from .db import pool

log = logging.getLogger(__name__)


def send_push(volunteer_id: str, title: str, body: str, url: str) -> bool:
    """Notify one volunteer. Returns whether anything was actually sent."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT push_subscription FROM volunteers WHERE volunteer_id=%s",
                    (volunteer_id,))
        row = cur.fetchone()
    if not row or not row[0]:
        return False                       # no subscription is normal, not an error
    if not settings.vapid_private_key:
        log.info("VAPID keys are not configured; not sending push to %s", volunteer_id)
        return False
    try:
        webpush(subscription_info=row[0],
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject})
        return True
    except WebPushException:
        log.warning("push to %s failed", volunteer_id, exc_info=True)
        return False
    except Exception:
        # pywebpush raises whatever the transport raised for DNS and TLS failures.
        log.warning("push to %s failed before it reached the push service", volunteer_id,
                    exc_info=True)
        return False
