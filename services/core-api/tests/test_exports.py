"""Task 11.2 / FR-41: research exports in an open format, pseudonymised (PRD 14.2)."""
from __future__ import annotations

import duckdb
import pytest
from conftest import STREAM

pytestmark = pytest.mark.integration

KEY = "export-key-" + "z" * 32


@pytest.fixture(autouse=True)
def _key(_pool, monkeypatch):
    from upstream_api.config import settings

    monkeypatch.setattr(settings, "export_pseudonym_key", KEY)


def columns(path) -> list[str]:
    return [r[0] for r in duckdb.sql(f"DESCRIBE SELECT * FROM '{path}'").fetchall()]


def test_export_writes_parquet_readable_by_duckdb(tmp_path, an_episode):
    from upstream_api.api.exports import export_episodes

    p = export_episodes(tmp_path, stream=STREAM)
    assert p.suffix == ".parquet"
    assert duckdb.sql(f"SELECT count(*) FROM '{p}' WHERE episode_id = '{an_episode}'"
                      ).fetchone()[0] == 1


def test_export_includes_the_fingerprint_for_reproducibility(tmp_path, an_episode, db_conn):
    from upstream_api.api.exports import export_episodes

    p = export_episodes(tmp_path, stream=STREAM)
    cols = columns(p)
    for c in ("fingerprint", "kernel_version", "params_version", "network_version"):
        assert c in cols
    fp = duckdb.sql(f"SELECT fingerprint FROM '{p}' WHERE episode_id='{an_episode}'").fetchone()[0]
    with db_conn.cursor() as cur:
        cur.execute("SELECT latest_fingerprint FROM episodes WHERE episode_id=%s", (an_episode,))
        assert fp and fp == cur.fetchone()[0]


def test_export_contains_no_observer_identifiers(tmp_path, post_evidence):
    """PRD 14.2: research exports are pseudonymised."""
    from upstream_api.api.exports import export_evidence

    post_evidence("positive")                                 # observer "off-1"
    p = export_evidence(tmp_path, stream=STREAM)
    cols = columns(p)
    assert "observer_hash" in cols
    for c in ("observer_id", "photo_uri", "mission_id"):
        assert c not in cols
    raw = p.read_bytes()
    assert b"off-1" not in raw


def test_the_same_observer_hashes_the_same_way_and_the_key_matters(tmp_path, post_evidence,
                                                                   monkeypatch):
    """Researchers can link one observer's reports without learning who they are, and
    without the key nobody can test a guessed id against the hash."""
    from upstream_api.api.exports import export_evidence, observer_hash
    from upstream_api.config import settings

    post_evidence("positive")
    post_evidence("negative")
    p = export_evidence(tmp_path, stream=STREAM)
    hashes = {r[0] for r in duckdb.sql(f"SELECT observer_hash FROM '{p}' "
                                       f"WHERE observer_type='officer'").fetchall()}
    assert observer_hash("off-1") in hashes
    monkeypatch.setattr(settings, "export_pseudonym_key", "a-different-key-" + "q" * 32)
    assert observer_hash("off-1") not in hashes


def test_retracted_evidence_is_exported_and_marked(tmp_path, post_evidence, store):
    """GC-5: nothing is deleted - a retraction travels with the data."""
    import datetime as dt

    from upstream_api.api.exports import export_evidence
    from upstream_api.config import settings
    from upstream_shared.events import EventEnvelope, EventType

    eid = post_evidence("positive")
    store.append(EventEnvelope(stream=STREAM, catchment_id=settings.catchment_id,
                               event_type=EventType.EVIDENCE_RETRACTED,
                               event_time=dt.datetime.now(dt.UTC),
                               payload={"retracts_event_id": eid, "reason": "test",
                                        "retracted_by": "off-1"}))
    p = export_evidence(tmp_path, stream=STREAM)
    assert duckdb.sql(f"SELECT retracted FROM '{p}' WHERE event_id='{eid}'").fetchone()[0] is True


def test_exports_refuse_without_a_pseudonym_key(tmp_path, monkeypatch):
    from upstream_api.api.exports import export_evidence
    from upstream_api.config import settings

    monkeypatch.setattr(settings, "export_pseudonym_key", "")
    with pytest.raises(RuntimeError, match="EXPORT_PSEUDONYM_KEY"):
        export_evidence(tmp_path, stream=STREAM)
