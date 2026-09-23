"""The EventStore interface over the append-only log (PRD 11.4).

The kernel depends on this Protocol and on nothing else about storage, which is what
would let Kafka replace Postgres later without the kernel noticing.

`read_as_of` is the belief-replay primitive: give it a sequence number and it returns
exactly the evidence the system held at that moment, which is how a posterior can be
recomputed bit-for-bit from its fingerprint (GC-6).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from psycopg.types.json import Jsonb
from upstream_shared.events import EventEnvelope, EventType

from .db import pool


@dataclass(frozen=True)
class StoredEvent:
    seq: int
    event_id: UUID
    stream: str
    catchment_id: str
    event_type: EventType
    schema_version: int
    event_time: dt.datetime
    recorded_at: dt.datetime
    payload: dict
    causation_id: UUID | None
    correlation_id: UUID | None


_COLS = ("seq,event_id,stream,catchment_id,event_type,schema_version,"
         "event_time,recorded_at,payload,causation_id,correlation_id")


class EventStore(Protocol):
    def append(self, env: EventEnvelope) -> int: ...
    def read_from(self, seq: int, *, catchment_id: str, stream: str,
                  limit: int = 10_000) -> list[StoredEvent]: ...
    def read_as_of(self, *, catchment_id: str, stream: str, as_of_seq: int,
                   since: dt.datetime | None = None) -> list[StoredEvent]: ...


class PostgresEventStore:
    def append(self, env: EventEnvelope) -> int:
        with pool.connection() as conn, conn.cursor() as cur:
            # Jsonb, not Json: append_event takes jsonb, and json -> jsonb is only an
            # assignment cast, so passing Json fails function resolution outright.
            cur.execute(
                "SELECT append_event(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (env.event_id, env.stream, env.catchment_id, env.event_type.value,
                 env.schema_version, env.event_time, Jsonb(env.payload),
                 env.causation_id, env.correlation_id))
            return cur.fetchone()[0]

    def read_from(self, seq, *, catchment_id, stream, limit=10_000):
        return self._query(
            f"SELECT {_COLS} FROM events WHERE catchment_id=%s AND stream=%s AND seq>%s "
            f"ORDER BY seq LIMIT %s", (catchment_id, stream, seq, limit))

    def read_as_of(self, *, catchment_id, stream, as_of_seq, since=None):
        sql = f"SELECT {_COLS} FROM events WHERE catchment_id=%s AND stream=%s AND seq<=%s"
        args: list = [catchment_id, stream, as_of_seq]
        if since is not None:
            sql += " AND event_time >= %s"
            args.append(since)
        return self._query(sql + " ORDER BY seq", tuple(args))

    @staticmethod
    def _query(sql, args) -> list[StoredEvent]:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return [StoredEvent(r[0], r[1], r[2], r[3], EventType(r[4]), r[5],
                                r[6], r[7], r[8], r[9], r[10]) for r in cur.fetchall()]


store = PostgresEventStore()
