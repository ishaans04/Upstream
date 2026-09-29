"""The clinical statistics service: the health zone (GC-7, PRD 14.1).

Its own container, its own database, its own role, and no credential for the
environmental database. Aggregate counts come in at `POST /counts`; test results
and upstream-search requests go out through `episode_client`, and nothing else
crosses in either direction.

The daily job runs in-process on a timer. It is idempotent -- a second run on the
same day adds a second result row and a second event, never a changed one -- so
a restart that runs it twice costs nothing but a duplicate line in the log.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI

from . import jobs
from .db import close_pool, open_pool
from .ingest import router as ingest_router

log = logging.getLogger(__name__)

# 0 disables the timer, which is what tests and one-off runs want.
DAILY_INTERVAL_S = float(os.environ.get("CLINICAL_DAILY_INTERVAL_S") or 86400)


async def _daily_loop() -> None:
    while True:
        await asyncio.sleep(DAILY_INTERVAL_S)
        for job in (jobs.run_daily, jobs.scan_clusters):
            try:
                log.info("%s: %s", job.__name__, await asyncio.to_thread(job))
            except Exception:           # one bad day must not stop every later one
                log.exception("%s failed", job.__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    task = asyncio.create_task(_daily_loop()) if DAILY_INTERVAL_S > 0 else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
        close_pool()


app = FastAPI(title="Upstream clinical statistics", version="0.1.0", lifespan=lifespan)
app.include_router(ingest_router)

Stream = Literal["live", "sim"]


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/run-daily")
def run_daily(stream: Stream = "live"):
    """FR-34: test every active episode and publish only the result."""
    return jobs.run_daily(stream=stream)


@app.post("/scan-clusters")
def scan_clusters(stream: Stream = "live"):
    """FR-35: an unexplained cluster asks the kernel to search upstream of it."""
    return jobs.scan_clusters(stream=stream)
