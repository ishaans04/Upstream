import asyncio
import datetime as dt
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from upstream_shared.events import EventEnvelope, EventType

from .config import settings
from .db import close_pool, open_pool
from .eventlog import store
from .ingest.rainfall_job import poll_rainfall
from .ingest.routes import rainfall as ingest_rainfall
from .ingest.routes import router as ingest_router
from .ingest.sensor_job import derive_sensor_evidence
from .network import get_network
from .workflows import timers
from .workflows.consumer import process_new_posteriors

log = logging.getLogger(__name__)

DERIVED_EVIDENCE_INTERVAL_S = 900
EPISODE_CONSUMER_INTERVAL_S = 5
TIMER_SWEEP_INTERVAL_S = 300


async def _derived_evidence_loop():
    """Layer 3 (PRD 10.4): scheduled jobs that turn raw feeds into evidence."""
    while True:
        try:
            net = get_network()
            lon, lat = net.lonlat.mean(axis=0)
            for r in await poll_rainfall(float(lon), float(lat)):
                ingest_rainfall(r)
            end = dt.datetime.now(dt.UTC).replace(second=0, microsecond=0)
            start = end - dt.timedelta(minutes=15)
            for ev in derive_sensor_evidence(start, end):
                store.append(EventEnvelope(
                    stream="live", catchment_id=settings.catchment_id,
                    event_type=EventType.EVIDENCE_RECORDED, event_time=end,
                    payload=ev.model_dump(mode="json")))
        except asyncio.CancelledError:
            raise
        except Exception:
            # NFR-8: a failing derived-evidence pass must never take ingestion down.
            log.exception("derived-evidence pass failed; continuing")
        await asyncio.sleep(DERIVED_EVIDENCE_INTERVAL_S)


async def _episode_lifecycle_loop():
    """Layer 5 (PRD 10.4): consume the kernel's posteriors and run the episode timers.

    The deadline sweep runs here as well as inside DBOS. A clinical-relevance window is
    16 days long (FR-22); if the only thing that could close it were a durable sleep,
    then a DBOS that failed to launch would leave every episode open forever and
    nothing would say so. The sweep reads the deadlines straight off the rows, so the
    worst a missing workflow engine costs is punctuality.
    """
    next_sweep = 0.0
    while True:
        try:
            process_new_posteriors(stream="live")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("episode consumer pass failed; continuing")     # NFR-8
        try:
            now = asyncio.get_running_loop().time()
            if now >= next_sweep:
                next_sweep = now + TIMER_SWEEP_INTERVAL_S
                log.info("timer sweep: %s", timers.sweep_due())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("timer sweep failed; continuing")               # NFR-8
        await asyncio.sleep(EPISODE_CONSUMER_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    timers.launch(settings.database_url)
    tasks = [asyncio.create_task(_derived_evidence_loop()),
             asyncio.create_task(_episode_lifecycle_loop())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        close_pool()


app = FastAPI(title="Upstream Core API", version="0.1.0", lifespan=lifespan)
app.include_router(ingest_router)


@app.get("/healthz")
def healthz():
    return {"ok": True}
