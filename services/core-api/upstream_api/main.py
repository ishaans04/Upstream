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

log = logging.getLogger(__name__)

DERIVED_EVIDENCE_INTERVAL_S = 900


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    task = asyncio.create_task(_derived_evidence_loop())
    try:
        yield
    finally:
        task.cancel()
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
