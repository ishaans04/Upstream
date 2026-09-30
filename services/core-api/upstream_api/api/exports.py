"""FR-41: research exports as Parquet (GC-15: open formats), readable by DuckDB.

Two tables per stream:

* episodes - one row per episode, with the fingerprint of the belief it holds and the
  kernel, parameter and network versions that produced it, so a researcher can
  reproduce that belief bit for bit (GC-6);
* evidence - one row per observation, retractions marked rather than dropped (GC-5).

Pseudonymised (PRD 14.2): the observer becomes a keyed hash, stable within one key so
one observer's reports can be linked, useless without the key for testing a guessed
id. Photos and mission ids (which lead back to a volunteer) are not exported at all.

    python -m upstream_api.api.exports --out exports/ --stream live
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from upstream_shared.events import EventType

from ..config import settings
from ..db import pool
from ..security import require_roles

router = APIRouter(tags=["exports"])

_EPISODE_COLS = ("episode_id", "catchment_id", "stream", "state", "opened_at",
                 "state_changed_at", "clinical_window_end", "p_event", "top_source",
                 "fingerprint", "kernel_version", "params_version", "network_version")
_EVIDENCE_COLS = ("event_id", "seq", "catchment_id", "stream", "event_time", "recorded_at",
                  "node_id", "method", "result", "value", "unit", "observer_type",
                  "observer_hash", "snap_distance_m", "ai_assisted", "confirmed_by_observer",
                  "on_mission", "retracted")


def observer_hash(observer_id: str) -> str:
    key = settings.export_pseudonym_key
    if not key:
        raise RuntimeError("EXPORT_PSEUDONYM_KEY is not set; refusing to export observers")
    return hmac.new(key.encode(), observer_id.encode(), hashlib.sha256).hexdigest()[:20]


def _write(rows: list[tuple], cols: tuple[str, ...], path: Path) -> Path:
    table = pa.Table.from_pydict({c: [r[i] for r in rows] for i, c in enumerate(cols)})
    pq.write_table(table, path)
    return path


def export_episodes(out_dir: Path, *, stream: str = "live") -> Path:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""
            SELECT e.episode_id, e.catchment_id, e.stream, e.state, e.opened_at,
                   e.state_changed_at, e.clinical_window_end,
                   (e.summary->>'p_event')::float8, e.summary->>'top_source',
                   e.latest_fingerprint, s.kernel_version, s.params_version,
                   s.network_version
            FROM episodes e
            LEFT JOIN LATERAL (SELECT kernel_version, params_version, network_version
                               FROM posterior_snapshots p
                               WHERE p.fingerprint = e.latest_fingerprint
                                 AND p.catchment_id = e.catchment_id AND p.stream = e.stream
                               ORDER BY p.ts DESC LIMIT 1) s ON TRUE
            WHERE e.catchment_id=%s AND e.stream=%s ORDER BY e.opened_at""",
                    (settings.catchment_id, stream))
        rows = cur.fetchall()
    return _write(rows, _EPISODE_COLS, Path(out_dir) / f"episodes-{stream}.parquet")


def export_evidence(out_dir: Path, *, stream: str = "live") -> Path:
    observer_hash("")                                    # refuse before reading anything
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""
            SELECT e.event_id::text, e.seq, e.catchment_id, e.stream, e.event_time,
                   e.recorded_at, e.payload,
                   EXISTS (SELECT 1 FROM events r
                           WHERE r.event_type=%s AND r.catchment_id=e.catchment_id
                             AND r.stream=e.stream
                             AND r.payload->>'retracts_event_id' = e.event_id::text)
            FROM events e
            WHERE e.event_type=%s AND e.catchment_id=%s AND e.stream=%s ORDER BY e.seq""",
                    (EventType.EVIDENCE_RETRACTED.value, EventType.EVIDENCE_RECORDED.value,
                     settings.catchment_id, stream))
        raw = cur.fetchall()
    rows = []
    for event_id, seq, catchment, strm, event_time, recorded_at, p, retracted in raw:
        rows.append((event_id, seq, catchment, strm, event_time, recorded_at,
                     p.get("node_id"), p.get("method"), p.get("result"),
                     p.get("value"), p.get("unit"), p.get("observer_type"),
                     observer_hash(str(p.get("observer_id", ""))),
                     p.get("snap_distance_m"), bool(p.get("ai_assisted")),
                     bool(p.get("confirmed_by_observer")), p.get("mission_id") is not None,
                     bool(retracted)))
    return _write(rows, _EVIDENCE_COLS, Path(out_dir) / f"evidence-{stream}.parquet")


_EXPORTS = {"episodes": export_episodes, "evidence": export_evidence}


@router.get("/exports/{kind}.parquet",
            dependencies=[Depends(require_roles("agency"))])
def download(kind: str, stream: str = "live"):
    if kind not in _EXPORTS:
        raise HTTPException(404, f"no export named {kind}; try {', '.join(_EXPORTS)}")
    tmp = tempfile.TemporaryDirectory()
    try:
        path = _EXPORTS[kind](Path(tmp.name), stream=stream)
    except RuntimeError as e:
        tmp.cleanup()
        raise HTTPException(503, str(e)) from e
    return FileResponse(path, media_type="application/vnd.apache.parquet",
                        filename=path.name, background=BackgroundTask(tmp.cleanup))


def main() -> None:
    from ..db import close_pool, open_pool

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stream", default="live")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    open_pool()
    try:
        for fn in _EXPORTS.values():
            print(fn(a.out, stream=a.stream))
    finally:
        close_pool()


if __name__ == "__main__":
    main()
