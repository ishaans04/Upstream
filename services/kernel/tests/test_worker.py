import datetime as dt

import pytest

pytestmark = pytest.mark.integration


def _snapshots(db_conn, catchment):
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM posterior_snapshots WHERE catchment_id=%s",
                    (catchment,))
        return cur.fetchone()[0]


def test_worker_writes_a_snapshot_after_new_evidence(kernel_worker, post_evidence, db_conn):
    post_evidence(result="positive")
    kernel_worker.process_once()
    assert _snapshots(db_conn, kernel_worker.catchment_id) == 1


def test_worker_emits_posterior_computed_with_a_fingerprint(kernel_worker, post_evidence,
                                                            db_conn):
    post_evidence(result="positive")
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT payload FROM events WHERE event_type='PosteriorComputed' "
                    "AND catchment_id=%s", (kernel_worker.catchment_id,))
        p = cur.fetchone()[0]
    assert p["fingerprint"].startswith("sha256:") and 0 <= p["p_event"] <= 1


def test_worker_advances_its_consumer_position(kernel_worker, post_evidence, db_conn):
    post_evidence(result="positive")
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT last_seq FROM consumer_positions WHERE consumer='kernel'")
        assert cur.fetchone()[0] > 0


def test_reprocessing_the_same_evidence_yields_the_same_fingerprint(kernel_worker,
                                                                    post_evidence, db_conn):
    post_evidence(result="positive")
    kernel_worker.process_once()
    kernel_worker.reset_position()
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT fingerprint FROM posterior_snapshots WHERE catchment_id=%s",
                    (kernel_worker.catchment_id,))
        assert len(cur.fetchall()) == 1


def test_belief_replay_returns_the_state_at_a_past_moment(kernel_worker, post_evidence,
                                                          db_conn):
    post_evidence(result="positive")
    kernel_worker.process_once()
    t_mid = dt.datetime.now(dt.UTC)
    post_evidence(result="negative", observer_id="vol-test-2")
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT p_event FROM posterior_snapshots WHERE catchment_id=%s AND ts <= %s "
                    "ORDER BY ts DESC LIMIT 1", (kernel_worker.catchment_id, t_mid))
        early = cur.fetchone()[0]
        cur.execute("SELECT p_event FROM posterior_snapshots WHERE catchment_id=%s "
                    "ORDER BY ts DESC LIMIT 1", (kernel_worker.catchment_id,))
        latest = cur.fetchone()[0]
    assert early != latest


def test_worker_does_nothing_when_there_is_no_new_evidence(kernel_worker, post_evidence,
                                                           db_conn):
    """Idempotence: a spurious notify must not write a duplicate snapshot."""
    post_evidence(result="positive")
    kernel_worker.process_once()
    kernel_worker.process_once()
    kernel_worker.process_once()
    assert _snapshots(db_conn, kernel_worker.catchment_id) == 1


def test_kernel_role_cannot_write_episodes_through_the_worker(kernel_worker):
    """PRD 10.3 / GC-10, enforced by grants rather than by convention.

    The worker holds a live connection as kernel_role, so this asserts the boundary
    on the same connection the recompute path uses, not on a hypothetical one.
    """
    import psycopg

    if "kernel_role" not in (kernel_worker.dsn or ""):
        pytest.skip("worker is not connected as kernel_role")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), kernel_worker.conn.cursor() as cur:
        cur.execute("INSERT INTO episodes (episode_id,catchment_id,stream,state,opened_at,"
                    "state_changed_at) VALUES ('x','c','sim','SUSPECTED',now(),now())")


def test_retraction_changes_the_fingerprint(kernel_worker, post_evidence, db_conn):
    """GC-5: a retraction is new evidence, so the posterior it produces is a new one."""
    import uuid

    from psycopg.types.json import Jsonb

    post_evidence(result="positive")
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT fingerprint FROM posterior_snapshots WHERE catchment_id=%s",
                    (kernel_worker.catchment_id,))
        before = cur.fetchone()[0]
        cur.execute("SELECT event_id FROM events WHERE catchment_id=%s "
                    "AND event_type='EvidenceRecorded' ORDER BY seq LIMIT 1",
                    (kernel_worker.catchment_id,))
        target = cur.fetchone()[0]
        cur.execute("SELECT append_event(%s,'sim',%s,'EvidenceRetracted',1,%s,%s,NULL,NULL)",
                    (uuid.uuid4(), kernel_worker.catchment_id, dt.datetime.now(dt.UTC),
                     Jsonb({"retracts_event_id": str(target), "reason": "test",
                            "retracted_by": "officer-1"})))
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT fingerprint FROM posterior_snapshots WHERE catchment_id=%s "
                    "ORDER BY ts DESC LIMIT 1", (kernel_worker.catchment_id,))
        after = cur.fetchone()[0]
    assert after != before
