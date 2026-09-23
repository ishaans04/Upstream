import datetime as dt
import threading
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration


def _append(conn, *, payload, commit=True):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT append_event(%s,'live','catch-1','EvidenceRecorded',1,%s,%s,NULL,NULL)",
            (uuid.uuid4(), dt.datetime.now(dt.UTC), Jsonb(payload)),
        )
        seq = cur.fetchone()[0]
    if commit and not conn.autocommit:
        conn.commit()
    return seq


def test_append_event_returns_monotonic_seq(db_conn):
    seqs = [_append(db_conn, payload={"i": i}) for i in range(3)]
    assert seqs == sorted(seqs) and len(set(seqs)) == 3


def test_events_are_append_only(db_conn):
    seq = _append(db_conn, payload={"x": 1})
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db_conn.cursor() as cur:
            cur.execute("SET ROLE app_role")
            cur.execute("UPDATE events SET payload='{}'::jsonb WHERE seq=%s", (seq,))


def test_commit_order_matches_seq_order(db_conn_factory):
    """PRD 12.2 ordering rule: a slow txn must not commit after a later one."""
    a, b = db_conn_factory(), db_conn_factory()
    a.autocommit = False
    result = {}
    seq_a = _append(a, payload={"who": "a"}, commit=False)
    t = threading.Thread(target=lambda: result.update(seq_b=_append(b, payload={"who": "b"})))
    t.start()
    t.join(timeout=2)
    assert "seq_b" not in result, "b should be blocked on the advisory lock"
    a.commit()
    t.join(timeout=10)
    assert result["seq_b"] > seq_a
