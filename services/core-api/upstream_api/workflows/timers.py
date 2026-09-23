"""Durable timers (PRD 10.4 Layer 5).

Two things have to be true at once here.

A clinical-relevance window runs for 16 days and a post-episode bioassessment for a
fortnight after that (FR-22, FR-24). A timer that lives in a Python coroutine dies with
the container, so these live in Postgres through DBOS.

But a timer that exists *only* inside DBOS is a single point of silence: if DBOS is not
running - a test process, a degraded deployment, a launch that failed - the episode
never resolves and nothing says so. So every deadline is also written into the row it
belongs to (`episodes.clinical_window_end`, `missions.window_end`) and a sweep can find
it from the database alone. DBOS makes the wake-up prompt; the sweep makes it certain.
"""
from __future__ import annotations

import logging
import os

from dbos import DBOS, DBOSConfig

log = logging.getLogger(__name__)

_launched = False


def launch(database_url: str | None = None) -> bool:
    """Start DBOS. Returns False if it could not start, having said why."""
    global _launched
    if _launched:
        return True
    url = database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        log.warning("no DATABASE_URL: durable timers are disabled, the sweep still runs")
        return False
    try:
        DBOS(config=DBOSConfig(name="upstream-onehealth", database_url=url))
        DBOS.launch()
    except Exception:
        # NFR-8: the API must come up even when the workflow engine will not.
        log.exception("DBOS failed to launch: durable timers are disabled, the sweep still runs")
        return False
    _launched = True
    return True


def is_launched() -> bool:
    return _launched


def start(workflow, *args) -> bool:
    """Start a durable workflow if DBOS is running. Never raises into the caller.

    Returning False is not a silent failure: the deadline is already persisted on the
    row, so `sweep_due()` will still act on it. What is lost is punctuality, not the
    transition.
    """
    if not _launched:
        log.info("DBOS not launched; %s deferred to the deadline sweep", workflow.__name__)
        return False
    try:
        DBOS.start_workflow(workflow, *args)
        return True
    except Exception:
        log.exception("could not start %s; deferring to the deadline sweep", workflow.__name__)
        return False


def sweep_due(now=None) -> dict[str, int]:
    """Run every deadline that has come due, from the database alone.

    Imported lazily so this module stays free of a cycle: episode.py and missions.py
    both import `timers`.
    """
    from . import episode, missions

    return {"episodes_resolved": len(episode.resolve_due_episodes(now)),
            "missions_expired": len(missions.expire_due_missions(now))}
