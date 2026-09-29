"""Fixtures for the health zone.

Every fixture here connects with `CLINICAL_DATABASE_URL` and nothing else. A
test that needed the environmental database would be a test of the wrong
service.
"""
import json
import os
from dataclasses import dataclass

import httpx
import psycopg
import pytest

AREA = "zone-boundary-test"


@pytest.fixture(scope="session")
def _clinical_pool():
    from clinical_stats.db import DSN, close_pool, open_pool

    if not DSN:
        pytest.skip("CLINICAL_DATABASE_URL is not set")
    try:
        open_pool()
    except Exception as exc:  # pragma: no cover - environment, not behaviour
        pytest.skip(f"the clinical database is not reachable: {exc}")
    yield
    close_pool()


@pytest.fixture
def clinical_conn(_clinical_pool):
    """A direct connection, for asserting on the schema itself."""
    connection = psycopg.connect(os.environ["CLINICAL_DATABASE_URL"], autocommit=True)
    yield connection
    connection.close()


@pytest.fixture
def clinical_counts(clinical_conn):
    """Isolate this test's area. Nothing else in the table is touched."""

    def purge():
        with clinical_conn.cursor() as cur:
            for table in ("syndromic_counts", "baselines", "test_results"):
                cur.execute(f"DELETE FROM {table} WHERE area_code LIKE %s", (AREA + "%",))

    purge()
    yield
    purge()


@dataclass
class Call:
    method: str
    path: str
    body: bytes


@pytest.fixture
def core_api():
    """A stand-in for the Core API that records every request the health zone makes.

    `episodes` is what GET /clinical/episodes will answer. Every call, of any
    method to any path, lands in `calls` -- so a test can assert on everything that
    left the service, not only on the calls it expected.
    """
    from clinical_stats import episode_client

    class FakeCoreApi:
        def __init__(self):
            self.episodes: list[dict] = []
            self.calls: list[Call] = []

        def handler(self, request: httpx.Request) -> httpx.Response:
            self.calls.append(Call(request.method, request.url.path, request.content))
            if request.method == "GET" and request.url.path == "/clinical/episodes":
                return httpx.Response(200, json={"episodes": self.episodes})
            if request.method == "POST":
                return httpx.Response(201, json={"seq": len(self.calls)})
            return httpx.Response(404)

        def posted(self, path: str) -> list[dict]:
            return [json.loads(c.body) for c in self.calls
                    if c.method == "POST" and c.path == path]

    fake = FakeCoreApi()
    episode_client.use_transport(httpx.MockTransport(fake.handler))
    yield fake
    episode_client.use_transport(None)
