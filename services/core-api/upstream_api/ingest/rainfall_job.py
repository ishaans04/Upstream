"""FR-7: poll Open-Meteo for catchment rainfall every 15 minutes.

Open-Meteo's free non-commercial endpoint needs NO API KEY. If you later switch to a
national radar or gauge feed, only this file changes.
"""
from __future__ import annotations

import datetime as dt

import httpx

from ..config import settings
from .routes import RainfallIn, flow_condition  # noqa: F401  (flow_condition re-exported)


async def poll_rainfall(lon: float, lat: float, now: dt.datetime | None = None
                        ) -> list[RainfallIn]:
    now = now or dt.datetime.now(dt.UTC)
    url = (f"{settings.open_meteo_base_url}/forecast?latitude={lat}&longitude={lon}"
           f"&minutely_15=precipitation&past_days=1&forecast_days=1&timezone=UTC")
    async with httpx.AsyncClient(timeout=20.0) as client:
        data = (await client.get(url)).json()
    times = data["minutely_15"]["time"]
    precip_mm = data["minutely_15"]["precipitation"]     # mm per 15 min
    out: list[RainfallIn] = []
    dry_run = 0.0
    for t, mm in zip(times, precip_mm, strict=True):
        ts = dt.datetime.fromisoformat(t).replace(tzinfo=dt.UTC)
        if ts > now:
            break
        mm_per_h = (mm or 0.0) * 4.0
        dry_run = 0.0 if mm_per_h > 0.2 else dry_run + 0.25
        out.append(RainfallIn(ts=ts, mm_per_h=mm_per_h, antecedent_dry_h=dry_run))
    return out
