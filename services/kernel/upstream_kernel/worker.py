"""Layer 4 (PRD 10.4): wake on new events, recompute everything, write a snapshot.

Deliberately dumb: no incremental state, no caches keyed on evidence. Every wake-up
reloads the full evidence set for the horizon and recomputes (GC-6). At ~11.5k
hypotheses that measures at well under two seconds, inside the five-second budget.

This worker is the only writer of `posterior_snapshots`, and it never touches
`episodes` - the kernel computes, it does not decide (PRD 10.3). That boundary is
enforced by the `kernel_role` grants from Phase 0, not by convention here.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import select
import uuid
from collections import namedtuple

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from .compile.loader import load_network
from .evidence_view import build_observations
from .model.hypotheses import build_grid
from .model.posterior import compute_posterior, source_marginals, start_time_credible_interval
from .model.priors import PriorInputs
from .physics.params import FLOW_CONDITIONS, default_params
from .physics.tables import load_tables
from .probe import probe
from .pulse import pulse
from .trace import explain

log = logging.getLogger(__name__)

KERNEL_VERSION = "upstream-kernel 0.1.0"
HORIZON_HOURS = 24
LEGACY_CONSUMER = "kernel"


def consumer_name(catchment_id: str, stream: str) -> str:
    """One cursor per catchment and stream.

    `seq` is a single global identity column and `consumer_positions` is keyed by name
    alone, so every worker pointed at this database shared one row: the deployed kernel
    and a worker running against a test catchment each moved the other's cursor, which
    makes a worker re-process evidence it has already handled or skip evidence it never
    saw. The same mistake was made on the episode consumer (GC-10).
    """
    return f"{LEGACY_CONSUMER}:{catchment_id}:{stream}"
BIN_S = 900

StoredRow = namedtuple("StoredRow", "seq event_id event_type event_time payload")


class KernelWorker:
    def __init__(self, dsn: str, catchment_id: str, stream: str = "live"):
        self.dsn, self.catchment_id, self.stream = dsn, catchment_id, stream
        self.net = load_network(os.environ.get("NETWORK_ARTIFACT", "data/artifacts/network.npz"))
        self.tables = load_tables(os.environ.get("TABLES_ARTIFACT", "data/artifacts/tables.npz"))
        self.params = default_params()
        self.conn = psycopg.connect(dsn, autocommit=True)

    def close(self) -> None:
        self.conn.close()

    # --- main loop -------------------------------------------------------
    def run(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("LISTEN events")
        self.process_once()
        while True:
            # Block until Postgres says something happened, or time out and
            # recompute anyway so a missed notify cannot wedge the worker.
            if select.select([self.conn], [], [], 5.0)[0]:
                self.conn.execute("SELECT 1")          # drain notifies
                for _ in self.conn.notifies(timeout=0.1):
                    pass
            try:
                self.process_once()
            except Exception:
                log.exception("recompute failed; will retry on the next wake-up")

    def process_once(self) -> None:
        last = self._position()
        events = self._read_events()
        if not events or events[-1].seq <= last:
            return
        post, extras = self._recompute(events)
        self._write_snapshot(post, extras, as_of_seq=events[-1].seq)
        self._set_position(events[-1].seq)

    # --- computation -----------------------------------------------------
    def _horizon(self) -> tuple[dt.datetime, dt.datetime]:
        """Snap the horizon to the bin grid.

        A horizon that ended at "whenever the worker happened to wake" would put a
        different pair of timestamps into every fingerprint, so recomputing the same
        evidence twice would produce two different fingerprints and GC-6 replay would
        never match. Aligning to the bin boundary makes the fingerprint a function of
        the evidence and the versions, which is the whole point of it.
        """
        now = dt.datetime.now(dt.UTC)
        end = dt.datetime.fromtimestamp((now.timestamp() // BIN_S) * BIN_S, dt.UTC)
        return end - dt.timedelta(hours=HORIZON_HOURS), end

    def _recompute(self, events):
        horizon_start, horizon_end = self._horizon()
        grid = build_grid(self.net, horizon_start=horizon_start, horizon_end=horizon_end,
                          bin_s=BIN_S)
        flow_idx, prior_inputs = self._flow_and_priors(grid)
        obs = build_observations(events, self.net, self.params)
        post = compute_posterior(obs, self.net, grid, self.tables, prior_inputs, self.params,
                                 flow_idx=flow_idx, kernel_version=KERNEL_VERSION,
                                 stream=self.stream)
        zones = pulse(post, self.net, self.tables, self.params)
        # The real flow condition, not a default: PROBE refuses to send anyone out in
        # high flow (PRD 7.5), and that gate is only meaningful if it sees the weather.
        candidates = probe(post, self.net, self.tables, self.params, zones,
                           now=dt.datetime.now(dt.UTC),
                           flow_condition=FLOW_CONDITIONS[flow_idx])
        ex = explain(post, obs, self.net, grid, self.tables, self.params)
        lo, hi = start_time_credible_interval(post, self.net)
        return post, {"zones": zones, "probe": candidates, "explanation": ex,
                      "est_start": (lo, hi),
                      "marginals": source_marginals(post, self.net)}

    def _flow_and_priors(self, grid):
        B = int((grid.horizon_end - grid.horizon_start) // grid.bin_s)
        cond = np.full(B, FLOW_CONDITIONS.index("dry"), dtype=np.int8)
        dry = np.full(B, 24.0)
        with self.conn.cursor() as cur:
            cur.execute("""SELECT ts, flow_condition, coalesce(antecedent_dry_h,24)
                           FROM rainfall WHERE catchment_id=%s AND stream=%s
                             AND ts >= to_timestamp(%s) AND ts < to_timestamp(%s)""",
                        (self.catchment_id, self.stream, grid.horizon_start, grid.horizon_end))
            for ts, fc, adh in cur.fetchall():
                b = int((ts.timestamp() - grid.horizon_start) // grid.bin_s)
                if 0 <= b < B and fc in FLOW_CONDITIONS:
                    cond[b] = FLOW_CONDITIONS.index(fc)
                    dry[b] = adh
        K = len(self.net.entry_idx)
        inputs = PriorInputs(cond, dry, self._past_episode_counts(K), np.zeros(K))
        return int(cond[-1]), inputs

    def _past_episode_counts(self, K: int) -> np.ndarray:
        """Filled by Phase 11 pooling; zeros until then."""
        counts = np.zeros(K, dtype=np.int32)
        with self.conn.cursor() as cur:
            cur.execute("SELECT summary->>'top_source', count(*) FROM episodes "
                        "WHERE state IN ('CONFIRMED','RESOLVED') GROUP BY 1")
            for entry_id, n in cur.fetchall():
                if entry_id in self.net.entry_nodes:
                    counts[self.net.entry_nodes.index(entry_id)] = n
        return counts

    # --- persistence -----------------------------------------------------
    def _write_snapshot(self, post, extras, *, as_of_seq: int) -> None:
        now = dt.datetime.now(dt.UTC)
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO posterior_snapshots
                (ts,fingerprint,episode_id,catchment_id,stream,as_of_seq,network_version,
                 kernel_version,params_version,p_event,source_marginals,zone_windows,
                 probe_candidates,explanation)
                VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (now, post.fingerprint, self.catchment_id, self.stream, as_of_seq,
                         post.network_version, post.kernel_version, post.params_version,
                         post.p_event, Jsonb(extras["marginals"]), Jsonb(extras["zones"]),
                         Jsonb(extras["probe"]), Jsonb(extras["explanation"])))
            top = sorted(((k, v) for k, v in extras["marginals"].items()
                          if not k.startswith("__")), key=lambda kv: -kv[1])[:3]
            cur.execute("SELECT append_event(%s,%s,%s,'PosteriorComputed',1,%s,%s,NULL,NULL)",
                        (uuid.uuid4(), self.stream, self.catchment_id, now,
                         Jsonb({"fingerprint": post.fingerprint, "p_event": post.p_event,
                                "as_of_seq": as_of_seq, "top_sources": top,
                                "est_start": [extras["est_start"][0], extras["est_start"][1]],
                                "zone_windows": extras["zones"],
                                "probe_candidates": extras["probe"][:5]})))

    def _read_events(self):
        horizon = dt.datetime.now(dt.UTC) - dt.timedelta(hours=HORIZON_HOURS)
        with self.conn.cursor() as cur:
            cur.execute("""SELECT seq,event_id,event_type,event_time,payload FROM events
                           WHERE catchment_id=%s AND stream=%s
                             AND event_type IN ('EvidenceRecorded','EvidenceRetracted')
                             AND event_time >= %s ORDER BY seq""",
                        (self.catchment_id, self.stream, horizon))
            return [StoredRow(*r) for r in cur.fetchall()]

    def _position(self) -> int:
        with self.conn.cursor() as cur:
            name = consumer_name(self.catchment_id, self.stream)
            cur.execute("SELECT last_seq FROM consumer_positions WHERE consumer=%s", (name,))
            row = cur.fetchone()
            if row is not None:
                return row[0]
            # Inherit the old shared cursor once, so upgrading does not replay the log.
            cur.execute("SELECT last_seq FROM consumer_positions WHERE consumer=%s",
                        (LEGACY_CONSUMER,))
            legacy = cur.fetchone()
            return legacy[0] if legacy else 0

    def _set_position(self, seq: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO consumer_positions (consumer,last_seq,updated_at)
                           VALUES (%s,%s,now()) ON CONFLICT (consumer)
                           DO UPDATE SET last_seq=EXCLUDED.last_seq, updated_at=now()""",
                        (consumer_name(self.catchment_id, self.stream), seq))

    def reset_position(self) -> None:
        self._set_position(0)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    KernelWorker(os.environ["KERNEL_DATABASE_URL"], os.environ["CATCHMENT_ID"]).run()


if __name__ == "__main__":
    main()
