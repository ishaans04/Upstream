"""Task 11.1: the recurring-source report (PRD 7.7) for the environmental agency."""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from conftest import STREAM
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from upstream_api.config import settings
from upstream_api.main import app

pytestmark = pytest.mark.integration

client = TestClient(app)


@pytest.fixture(autouse=True)
def _needs_pool(_pool):
    """Routes use the module-level pool; TestClient only runs the lifespan as a CM."""


@pytest.fixture
def recurring(db_conn, _network):
    """Three closed episodes on the sim stream that each lean to the same outfall."""
    entries = _network.entry_nodes
    made = []
    with db_conn.cursor() as cur:
        for k in range(3):
            eid, fp = f"EE-R{uuid.uuid4().hex[:6]}", f"sha256:report-{uuid.uuid4().hex}"
            cur.execute("""INSERT INTO posterior_snapshots (ts,fingerprint,catchment_id,stream,
                           as_of_seq,network_version,kernel_version,params_version,p_event,
                           source_marginals,zone_windows,probe_candidates,explanation)
                           VALUES (now(),%s,%s,%s,0,'n','test','p',0.99,%s,'{}','[]','{}')""",
                        (fp, settings.catchment_id, STREAM,
                         Jsonb({"__none__": 0.01, entries[0]: 0.9, entries[1]: 0.09})))
            cur.execute("""INSERT INTO episodes (episode_id,catchment_id,stream,state,opened_at,
                           state_changed_at,latest_fingerprint)
                           VALUES (%s,%s,%s,'RESOLVED',%s,now(),%s)""",
                        (eid, settings.catchment_id, STREAM,
                         dt.datetime.now(dt.UTC) - dt.timedelta(days=30 * k), fp))
            made.append((eid, fp))
    yield entries[0]
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM episodes WHERE episode_id = ANY(%s)", ([m[0] for m in made],))
        cur.execute("DELETE FROM posterior_snapshots WHERE fingerprint = ANY(%s)",
                    ([m[1] for m in made],))


def test_the_report_names_a_place_to_inspect(recurring):
    body = client.get("/reports/recurring-sources", params={"stream": STREAM}).json()
    top = body["sources"][0]
    assert top["node_id"] == recurring
    assert top["episode_count"] >= 3 and top["pooled_probability"] > 0.5
    assert top["outfall_id"].startswith("O") and top["is_synthetic"] is True
    # The public label, not the internal node id, in the sentence an officer reads.
    assert top["outfall_id"] in top["suggested_action"]
    assert "inspect" in top["suggested_action"].lower()


def test_the_report_never_attributes_blame(recurring):
    """GC-12: a place to look, never a party to blame."""
    text = client.get("/reports/recurring-sources", params={"stream": STREAM}).text.lower()
    assert not any(w in text for w in ("polluter", "responsible", "blame", "culprit"))
    assert "not a finding of fault" in text


def test_the_nightly_run_records_the_report_once_a_day(recurring, db_conn):
    from upstream_api.api.reports import record_recurring_sources

    # The log is append-only, so every run needs a date no earlier run has used.
    day = dt.date(2100, 1, 1) + dt.timedelta(days=uuid.uuid4().int % 300_000)
    first = record_recurring_sources(STREAM, day=day)
    again = record_recurring_sources(STREAM, day=day)
    assert first is True and again is False
    with db_conn.cursor() as cur:
        cur.execute("""SELECT count(*), max(payload->'sources'->0->>'node_id') FROM events
                       WHERE event_type='RecurringSourcesReported' AND stream=%s
                         AND catchment_id=%s AND payload->>'report_date'=%s""",
                    (STREAM, settings.catchment_id, day.isoformat()))
        n, node = cur.fetchone()
    assert n == 1 and node == recurring
