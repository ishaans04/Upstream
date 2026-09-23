"""Layer 5 (PRD 10.4): the episode lifecycle (FR-20, FR-21, FR-22, PRD 6.3).

The kernel computes and this decides (PRD 10.3). Every decision here is driven by a
`PosteriorComputed` event the kernel wrote, and every decision it takes becomes a new
event of its own, so the whole lifecycle can be replayed from the log (GC-5).

Two rules are load-bearing and not merely enforced by the state table:

* `CONFIRMED` is unreachable except through `give_signoff`, which needs a named officer
  *and* a positive field or lab result that has not been retracted (FR-21).
* `RESOLVED` and `REFUTED` are closed, but not final. PRD 6.3 says later evidence
  reopens an episode with its history preserved, so `_reopen` is a deliberate, logged
  exception to the ordinary transition table rather than a hole in it.
"""
from __future__ import annotations

import datetime as dt
import uuid

from dbos import DBOS
from psycopg.types.json import Jsonb
from upstream_shared.codes import (
    CFU_PER_100ML_FACTOR,
    CLINICAL_RELEVANCE_DAYS,
    LAB_POSITIVE_THRESHOLD_PER_100ML,
    ObservationMethod,
)
from upstream_shared.episode import (
    THRESHOLD_PROBABLE,
    THRESHOLD_REFUTED,
    THRESHOLD_SUSPECTED,
    EpisodeState,
)
from upstream_shared.events import EventEnvelope, EventType

from ..config import settings
from ..db import pool
from ..eventlog import store
from . import timers

CLOSED = {EpisodeState.RESOLVED, EpisodeState.REFUTED}
_COLS = ("episode_id", "catchment_id", "stream", "state", "opened_at", "state_changed_at",
         "clinical_window_end", "latest_fingerprint", "summary")


def _now() -> dt.datetime:
    """The clock, as one function, so tests can move it without patching datetime."""
    return dt.datetime.now(dt.UTC)


# --------------------------------------------------------------------------- consumer


def on_posterior_computed(event) -> None:
    """Consumer of PosteriorComputed. The kernel never does this itself (PRD 10.3)."""
    p_event = float(event.payload["p_event"])
    ep = _latest_episode(event.stream)

    if ep is None or EpisodeState(ep["state"]) in CLOSED:
        if p_event < THRESHOLD_SUSPECTED:
            return                              # nothing open, and nothing worth opening
        ep = _reopen(ep, event, p_event) if ep is not None else _open(event, p_event)

    target = _target_state(EpisodeState(ep["state"]), p_event)
    if target is not None and EpisodeState(ep["state"]).can_transition_to(target):
        _transition(ep, target, reason=f"p_event={p_event:.3f}", event=event)
    _update_summary(ep["episode_id"], event.payload)


def _target_state(current: EpisodeState, p_event: float) -> EpisodeState | None:
    if p_event < THRESHOLD_REFUTED:
        return EpisodeState.REFUTED
    if current is EpisodeState.SUSPECTED and p_event >= THRESHOLD_PROBABLE:
        return EpisodeState.PROBABLE
    return None     # CONFIRMED needs a human (FR-21); RESOLVED comes from a timer (FR-22)


# --------------------------------------------------------------------------- opening


def _open(event, p_event: float) -> dict:
    now = _now()
    episode_id = f"EE-{uuid.uuid4().hex[:4].upper()}"
    lo, hi = (event.payload.get("est_start") or [None, None])[:2]
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO episodes (episode_id,catchment_id,stream,state,opened_at,
                       state_changed_at,est_start_lo,est_start_hi,clinical_window_end,
                       latest_fingerprint,summary)
                       VALUES (%s,%s,%s,'SUSPECTED',%s,%s,
                               to_timestamp(%s),to_timestamp(%s),%s,%s,%s)""",
                    (episode_id, settings.catchment_id, event.stream, now, now, lo, hi,
                     _clinical_window_end(event.payload, now), event.payload.get("fingerprint"),
                     Jsonb({})))
    store.append(EventEnvelope(
        stream=event.stream, catchment_id=settings.catchment_id,
        event_type=EventType.EPISODE_OPENED, event_time=now,
        payload={"episode_id": episode_id, "fingerprint": event.payload.get("fingerprint"),
                 "p_event": p_event},
        causation_id=event.event_id))
    timers.start(episode_workflow, settings.catchment_id, episode_id)
    return _episode(episode_id)


def _reopen(ep: dict, event, p_event: float) -> dict:
    """PRD 6.3: later evidence reopens a closed episode; the history is preserved.

    This is the one transition the state table forbids, and deliberately so: reopening
    is not an ordinary progression, it is an admission that a closed call was wrong, and
    it should be visible as its own decision rather than hidden inside `_ALLOWED`.
    """
    target = (EpisodeState.PROBABLE if p_event >= THRESHOLD_PROBABLE
              else EpisodeState.SUSPECTED)
    now = _now()
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("UPDATE episodes SET clinical_window_end=%s, latest_fingerprint=%s "
                    "WHERE episode_id=%s",
                    (_clinical_window_end(event.payload, now), event.payload.get("fingerprint"),
                     ep["episode_id"]))
    _transition(ep, target, reason=f"reopened on new evidence, p_event={p_event:.3f}",
                event=event, force=True)
    timers.start(episode_workflow, settings.catchment_id, ep["episode_id"])
    return _episode(ep["episode_id"])


def _clinical_window_end(payload: dict, now: dt.datetime) -> dt.datetime:
    """FR-22: 16 days of clinical relevance, counted from the end of exposure.

    PRD 6.1 puts the window after *exposure*, not after the report, so a zone still
    being exposed six hours from now stays relevant for 16 days beyond that. Falling
    back to `now` keeps the window from ever being shorter than the incubation period.
    """
    ends = [w.get("window_hi") for w in (payload.get("zone_windows") or {}).values()
            if isinstance(w, dict) and w.get("window_hi") is not None]
    last = max([dt.datetime.fromtimestamp(float(t), dt.UTC) for t in ends] + [now])
    return last + dt.timedelta(days=CLINICAL_RELEVANCE_DAYS)


# --------------------------------------------------------------------------- transitions


def _transition(ep: dict, target: EpisodeState, *, reason: str, event=None,
                force: bool = False) -> None:
    if not force and not EpisodeState(ep["state"]).can_transition_to(target):
        raise PermissionError(f"cannot move from {ep['state']} to {target.value}")
    now = _now()
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("UPDATE episodes SET state=%s, state_changed_at=%s, version=version+1 "
                    "WHERE episode_id=%s", (target.value, now, ep["episode_id"]))
    store.append(EventEnvelope(
        stream=ep["stream"], catchment_id=settings.catchment_id,
        event_type=EventType.EPISODE_STATE_CHANGED, event_time=now,
        payload={"episode_id": ep["episode_id"], "from": ep["state"],
                 "to": target.value, "reason": reason},
        causation_id=getattr(event, "event_id", None)))


def force_state(episode_id: str, target: str | EpisodeState) -> None:
    """The administrative transition. It cannot reach CONFIRMED (FR-21)."""
    target = EpisodeState(target)
    if target is EpisodeState.CONFIRMED:
        raise PermissionError(
            "CONFIRMED is reachable only through give_signoff: FR-21 requires a named "
            "officer and a positive field or lab result")
    _transition(_episode(episode_id), target, reason="set by an operator")


# --------------------------------------------------------------------------- sign-off


def request_signoff(episode_id: str, reason: str) -> None:
    ep = _episode(episode_id)
    store.append(EventEnvelope(
        stream=ep["stream"], catchment_id=settings.catchment_id,
        event_type=EventType.SIGN_OFF_REQUESTED, event_time=_now(),
        payload={"episode_id": episode_id, "reason": reason}))


def give_signoff(episode_id: str, officer_id: str, field_result_event_id: str | None) -> None:
    """FR-21: CONFIRMED needs a positive field/lab result AND an officer."""
    if not officer_id:
        raise ValueError("CONFIRMED requires a named officer")
    if not field_result_event_id or not _is_positive_result(field_result_event_id):
        raise ValueError("CONFIRMED requires a positive field or lab result")
    ep = _episode(episode_id)
    if not EpisodeState(ep["state"]).can_transition_to(EpisodeState.CONFIRMED):
        raise PermissionError(f"cannot confirm from {ep['state']}")
    store.append(EventEnvelope(
        stream=ep["stream"], catchment_id=settings.catchment_id,
        event_type=EventType.SIGN_OFF_GIVEN, event_time=_now(),
        payload={"episode_id": episode_id, "officer_id": officer_id,
                 "field_result_event_id": field_result_event_id}))
    _transition(ep, EpisodeState.CONFIRMED, reason=f"officer {officer_id} signed off")


def _is_positive_result(event_id: str) -> bool:
    """Is this evidence event a positive result that still stands?

    Fails closed everywhere: an unknown event, a retracted one (GC-5), an unrecognised
    unit or an analyte with no published limit all return False. Sign-off is the last
    gate before anything health-facing is published, so "I could not tell" has to mean
    no.
    """
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT payload FROM events WHERE event_id=%s AND event_type=%s",
                    (event_id, EventType.EVIDENCE_RECORDED.value))
        row = cur.fetchone()
        if row is None:
            return False
        cur.execute("SELECT 1 FROM events WHERE event_type=%s AND payload->>%s=%s LIMIT 1",
                    (EventType.EVIDENCE_RETRACTED.value, "retracts_event_id", str(event_id)))
        if cur.fetchone() is not None:
            return False
    payload = row[0]
    if payload.get("result") == "positive":
        return True
    if payload.get("result") != "quantitative":
        return False
    limit = LAB_POSITIVE_THRESHOLD_PER_100ML.get(ObservationMethod(payload["method"]))
    factor = CFU_PER_100ML_FACTOR.get(payload.get("unit") or "")
    if limit is None or factor is None or payload.get("value") is None:
        return False
    return float(payload["value"]) * factor > limit


# --------------------------------------------------------------------------- timers


def resolve_due_episodes(now: dt.datetime | None = None) -> list[str]:
    """FR-22: close every episode whose clinical-relevance window has elapsed.

    Driven by the durable workflow below, and by the sweep in `timers`, so a missed or
    undelivered DBOS wake-up delays the transition instead of losing it.
    """
    now = now or _now()
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(f"SELECT {','.join(_COLS)} FROM episodes WHERE catchment_id=%s "
                    "AND clinical_window_end <= %s AND state NOT IN ('RESOLVED','REFUTED')",
                    (settings.catchment_id, now))
        due = [dict(zip(_COLS, r, strict=True)) for r in cur.fetchall()]
    resolved = []
    for ep in due:
        if EpisodeState(ep["state"]).can_transition_to(EpisodeState.RESOLVED):
            _transition(ep, EpisodeState.RESOLVED, reason="clinical relevance window elapsed")
            resolved.append(ep["episode_id"])
    return resolved


@DBOS.workflow()
def episode_workflow(catchment_id: str, episode_id: str) -> None:
    """Durable timers: FR-22 (clinical window) and FR-24 (post-episode bioassessment)."""
    ep = _episode(episode_id)
    DBOS.sleep(max((ep["clinical_window_end"] - _now()).total_seconds(), 0.0))
    resolve_due_episodes()
    if _episode(episode_id)["state"] == EpisodeState.CONFIRMED.value:
        DBOS.sleep(14 * 24 * 3600)                    # FR-24: 2-4 weeks later
        from .missions import create_bioassessment_mission
        create_bioassessment_mission(episode_id)


# --------------------------------------------------------------------------- reads


def _episode(episode_id: str) -> dict:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(f"SELECT {','.join(_COLS)} FROM episodes WHERE episode_id=%s", (episode_id,))
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"no such episode: {episode_id}")
    return dict(zip(_COLS, row, strict=True))


def _latest_episode(stream: str) -> dict | None:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(f"SELECT {','.join(_COLS)} FROM episodes WHERE catchment_id=%s "
                    "AND stream=%s ORDER BY opened_at DESC LIMIT 1",
                    (settings.catchment_id, stream))
        row = cur.fetchone()
    return dict(zip(_COLS, row, strict=True)) if row else None


def _update_summary(episode_id: str, payload: dict) -> None:
    top = (payload.get("top_sources") or [[None]])[0]
    summary = {"p_event": payload.get("p_event"),
               "top_source": top[0] if isinstance(top, list | tuple) else None,
               "top_sources": payload.get("top_sources") or [],
               "zone_windows": payload.get("zone_windows") or {}}
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("UPDATE episodes SET summary=%s, latest_fingerprint=%s WHERE episode_id=%s",
                    (Jsonb(summary), payload.get("fingerprint"), episode_id))
