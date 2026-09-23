from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import close_pool, open_pool
from .ingest.routes import router as ingest_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    yield
    close_pool()


app = FastAPI(title="Upstream Core API", version="0.1.0", lifespan=lifespan)
app.include_router(ingest_router)


@app.get("/healthz")
def healthz():
    return {"ok": True}
