import datetime as dt
import os
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb


@pytest.fixture
def db_conn():
    c = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    yield c
    c.close()


@pytest.fixture
def clean_kernel_state(db_conn):
    """The worker's outputs are cumulative; each test needs its own slate.

    Only kernel-owned rows are cleared. `events` is append-only by design (GC-5) and
    is never touched - instead the worker's consumer position is reset and the tests
    use a catchment id of their own, so old evidence is invisible rather than deleted.
    """
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM posterior_snapshots WHERE catchment_id LIKE 'test-%%'")
        cur.execute("DELETE FROM consumer_positions WHERE consumer='kernel'")


@pytest.fixture
def test_catchment(clean_kernel_state) -> str:
    """A catchment id unique to this test, so the append-only log stays append-only."""
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def kernel_worker(test_catchment, db_conn):
    from upstream_kernel.worker import KernelWorker

    # KERNEL_DATABASE_URL, not DATABASE_URL: running the worker as kernel_role is what
    # proves the GC-10 boundary holds in practice rather than only in the grant table.
    dsn = os.environ.get("KERNEL_DATABASE_URL") or os.environ["DATABASE_URL"]
    w = KernelWorker(dsn, test_catchment, stream="sim")
    yield w
    w.close()


@pytest.fixture
def post_evidence(kernel_worker, db_conn):
    """Append EvidenceRecorded for this test's catchment.

    Node ids default to a real entry node of the compiled network. The plan's tests
    name toy ids like "O14"; against the real artefact those are unknown nodes, which
    build_observations skips - the tests would pass while measuring nothing.
    """
    net = kernel_worker.net

    def _post(node_id: str | None = None, result: str = "positive",
              method: str = "citizen_visual_olfactory", minutes_ago: float = 5.0,
              observer_id: str = "vol-test"):
        node = node_id if node_id in net.node_index else net.entry_nodes[0]
        payload = {"node_id": node, "method": method, "result": result,
                   "observer_id": observer_id, "observer_type": "citizen",
                   "snap_distance_m": 2.0, "oah_codes": [], "ai_assisted": False,
                   "confirmed_by_observer": True}
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT append_event(%s,'sim',%s,'EvidenceRecorded',1,%s,%s,NULL,NULL)",
                (uuid.uuid4(), kernel_worker.catchment_id,
                 dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes_ago),
                 Jsonb(payload)))
            return cur.fetchone()[0]

    return _post
