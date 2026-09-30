"""The health zone's only line to the environmental side (GC-7).

It is HTTP to three Core API routes, not a database connection: one read (where
and when people may have been exposed) and two writes (a test result, a request
to search upstream). What each write sends is spelled out field by field here,
and the Core API refuses anything else, so a count cannot leave this service
through this module or around it.
"""
from __future__ import annotations

import datetime as dt
import os

import httpx

from .matched_filter import TestResult

BASE_URL = os.environ.get("EPISODE_API_BASE_URL", "http://api:8000")
# A public_health service token (Phase 11): the Core API's /clinical routes require it.
# Mint one with `python -m upstream_api.security mint --sub clinical-stats
# --role public_health`.
TOKEN = os.environ.get("CORE_API_TOKEN", "")

# Tests replace the transport to see exactly what would have been sent.
_transport: httpx.BaseTransport | None = None


def use_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def _client() -> httpx.Client:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    return httpx.Client(base_url=BASE_URL, timeout=15.0, transport=_transport, headers=headers)


def active_episodes(stream: str = "live") -> list[dict]:
    """Episodes still inside their clinical relevance window, with zone curves."""
    with _client() as c:
        response = c.get("/clinical/episodes", params={"stream": stream})
        response.raise_for_status()
        return response.json()["episodes"]


def post_test_result(result: TestResult, stream: str = "live") -> None:
    with _client() as c:
        c.post("/clinical/test-result", params={"stream": stream},
               json=result.to_wire()).raise_for_status()


def request_upstream_search(*, area_code: str, syndrome: str, day: dt.date, p_value: float,
                            method: str, stream: str = "live") -> None:
    body = {"area_code": area_code, "syndrome": syndrome, "day": day.isoformat(),
            "p_value": p_value, "method": method}
    with _client() as c:
        c.post("/clinical/upstream-search", params={"stream": stream},
               json=body).raise_for_status()
