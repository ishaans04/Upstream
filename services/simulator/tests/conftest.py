"""Fixtures for the simulator.

Runs are written under a catchment id of their own. The log is append-only, so a
test that wrote into the real catchment's sim stream would leave incidents behind
for the next kernel run to find.
"""
import datetime as dt
import os
import uuid

import numpy as np
import psycopg
import pytest

# The committed Coimbra network, not whatever data/artifacts holds: CI compiles a
# synthetic line there, and these tests are about the real catchment.
REAL_NETWORK = os.environ.get("SIM_TEST_NETWORK", "bench/fixtures/network.npz")


@pytest.fixture(scope="session")
def net():
    from upstream_kernel.compile.loader import load_network

    return load_network(REAL_NETWORK)


@pytest.fixture(scope="session")
def now():
    return dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)


@pytest.fixture(scope="session")
def owner_dsn():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is not set")
    return dsn


@pytest.fixture(scope="session")
def written(net, now, owner_dsn):
    """One scenario, written to the log and to sim_truth, and read back."""
    from upstream_sim.run import SimStore, TruthWriter, run_scenario
    from upstream_sim.scenario import sample_scenario

    catchment = f"simtest-{uuid.uuid4().hex[:10]}"
    store, truth = SimStore(owner_dsn, catchment), TruthWriter(owner_dsn)
    scenario = sample_scenario(net, np.random.default_rng(11), now=now)
    posted = []
    try:
        out = run_scenario(net, scenario, n_citizens=60, n_sensors=2, store=store,
                           truth_writer=truth, clinical_poster=posted.append, clinical_days=60,
                           run_id=f"test-{uuid.uuid4().hex[:8]}", now=now)
    finally:
        store.close()
        truth.close()
    yield {**out, "catchment": catchment, "posted": posted}
    with psycopg.connect(owner_dsn, autocommit=True) as c:
        # Ground truth is not the event log: removing a test's truth deletes no event.
        c.execute("DELETE FROM sim_truth.injected_events WHERE run_id=%s", (out["run_id"],))


@pytest.fixture
def owner_conn(owner_dsn):
    with psycopg.connect(owner_dsn, autocommit=True) as c:
        yield c


@pytest.fixture
def kernel_conn():
    """The kernel's own credential. GC-10 is about this role, so no other will do."""
    dsn = os.environ.get("KERNEL_DATABASE_URL")
    if not dsn:
        pytest.skip("KERNEL_DATABASE_URL is not set")
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c
