"""Mission lifecycle: create, assign, notify, expire, re-plan (FR-15, FR-17, FR-23, FR-24).

PROBE says where a sample would be worth taking; this turns that into a time-boxed
errand for a named person, and afterwards tells them what their trip actually changed
(G7, PRD 16). The measurement is the honest part: the effect is computed from the two
posterior snapshots either side of the evidence, so it can come out negative, and when
it does the volunteer is told the field widened rather than being congratulated.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid

from dbos import DBOS
from upstream_shared.codes import ObservationMethod
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.mission import MissionSpec, MissionStatus, ProbeMode

from ..config import settings
from ..db import pool
from ..eventlog import store
from ..network import get_network
from ..push import send_push
from ..routing import assign_missions
from . import timers

log = logging.getLogger(__name__)

BIOASSESSMENT_DELAY_DAYS = 14        # FR-24: two to four weeks after the episode
BIOASSESSMENT_WINDOW_DAYS = 14
OPEN_STATUSES = (MissionStatus.CREATED.value, MissionStatus.ACCEPTED.value)

_MISSION_COLS = ("mission_id", "episode_id", "node_id", "window_start", "window_end",
                 "methods", "mode", "assignee_id", "assignee_type", "status",
                 "expected_gain", "realised_gain", "created_at")


# --------------------------------------------------------------------------- creation


def create_missions_from_probe(episode_id: str, candidates: list[dict]) -> list[MissionSpec]:
    """FR-15/FR-17: turn PROBE candidates into assigned, time-boxed missions."""
    located = _with_locations(candidates)
    if not located:
        return []
    volunteers = _available_volunteers()
    pairs = assign_missions(located, volunteers, now=dt.datetime.now(dt.UTC))
    by_id = {c["candidate_id"]: c for c in located}

    specs = []
    for cand_id, vol_id in pairs:
        c = by_id[cand_id]
        mission_id = f"M-{uuid.uuid4().hex[:4].upper()}"
        summary = (f"Check {c['node_id']} between {_hhmm(c['window_start'])} and "
                   f"{_hhmm(c['window_end'])}: {', '.join(c['methods'])}. "
                   f"{c.get('expected_effect', '')}".strip())
        spec = MissionSpec(mission_id=mission_id, episode_id=episode_id,
                           node_id=c["node_id"], window_start=_dt(c["window_start"]),
                           window_end=_dt(c["window_end"]),
                           methods=[ObservationMethod(m) for m in c["methods"]],
                           mode=ProbeMode(c["mode"]), expected_gain=float(c["ec2_gain"]),
                           human_summary=summary)
        _insert_mission(spec, vol_id)
        store.append(EventEnvelope(
            stream=_stream_for(episode_id), catchment_id=settings.catchment_id,
            event_type=EventType.MISSION_CREATED, event_time=dt.datetime.now(dt.UTC),
            payload={"mission_id": mission_id, "episode_id": episode_id,
                     "node_id": c["node_id"], "assignee": vol_id,
                     "expected_gain": float(c["ec2_gain"])}))
        send_push(vol_id, "Upstream mission nearby", summary, f"/missions/{mission_id}")
        timers.start(mission_deadline_workflow, mission_id)
        specs.append(spec)
    return specs


def _with_locations(candidates: list[dict]) -> list[dict]:
    """Give each candidate the lon/lat the router needs.

    PROBE works in node indices and never emits a coordinate, but `assign_missions`
    cannot walk anyone to a node id. A candidate naming a node that is not in the
    compiled network is dropped rather than guessed at - sending someone to a place we
    cannot locate is worse than sending nobody.
    """
    net = get_network()
    out = []
    for c in candidates:
        idx = net.node_index.get(c["node_id"])
        if idx is None:
            log.warning("probe candidate %s names an unknown node %s; skipping",
                        c.get("candidate_id"), c["node_id"])
            continue
        lon, lat = net.lonlat[idx]
        out.append({**c, "lonlat": (float(lon), float(lat))})
    return out


def _available_volunteers() -> list[dict]:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT volunteer_id, ST_X(ST_Centroid(coarse_area)),
                              ST_Y(ST_Centroid(coarse_area)), available_from, available_to,
                              reliability
                       FROM volunteers
                       WHERE coarse_area IS NOT NULL AND available_from IS NOT NULL
                         AND available_to >= now()""")
        return [{"volunteer_id": r[0], "lonlat": (r[1], r[2]), "available_from": r[3],
                 "available_to": r[4], "reliability": r[5]} for r in cur.fetchall()]


def _insert_mission(spec: MissionSpec, volunteer_id: str | None) -> None:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO missions (mission_id,episode_id,node_id,window_start,
                       window_end,methods,mode,assignee_id,assignee_type,status,
                       expected_gain) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (spec.mission_id, spec.episode_id, spec.node_id, spec.window_start,
                     spec.window_end, [m.value for m in spec.methods], spec.mode.value,
                     volunteer_id, "volunteer" if volunteer_id else None,
                     MissionStatus.CREATED.value, spec.expected_gain))


def create_bioassessment_mission(episode_id: str) -> str:
    """FR-24: a macroinvertebrate survey some weeks after the episode.

    Unassigned on purpose. A bioassessment is a scheduled survey rather than an errand
    someone has to run tonight, so it goes on the board for whoever is qualified.
    """
    start = dt.datetime.now(dt.UTC) + dt.timedelta(days=BIOASSESSMENT_DELAY_DAYS)
    spec = MissionSpec(
        mission_id=f"M-{uuid.uuid4().hex[:4].upper()}", episode_id=episode_id,
        node_id=_episode_node(episode_id),
        window_start=start, window_end=start + dt.timedelta(days=BIOASSESSMENT_WINDOW_DAYS),
        methods=[ObservationMethod.BIOASSESSMENT], mode=ProbeMode.PROTECT, expected_gain=0.0,
        human_summary=(f"Bioassessment survey for episode {episode_id}: "
                       "macroinvertebrate sampling to measure recovery."))
    _insert_mission(spec, None)
    store.append(EventEnvelope(
        stream=_stream_for(episode_id), catchment_id=settings.catchment_id,
        event_type=EventType.MISSION_CREATED, event_time=dt.datetime.now(dt.UTC),
        payload={"mission_id": spec.mission_id, "episode_id": episode_id,
                 "node_id": spec.node_id, "assignee": None, "expected_gain": 0.0,
                 "kind": "bioassessment"}))
    return spec.mission_id


# --------------------------------------------------------------------------- lifecycle


def accept_mission(mission_id: str, volunteer_id: str) -> None:
    m = _mission(mission_id)
    if m["status"] not in OPEN_STATUSES:
        raise ValueError(f"mission {mission_id} is {m['status']}, not open")
    if m["window_end"] <= dt.datetime.now(dt.UTC):
        raise ValueError(f"mission {mission_id} has expired")
    _set_status(mission_id, MissionStatus.ACCEPTED, assignee_id=volunteer_id)
    store.append(EventEnvelope(
        stream=_stream_for(m["episode_id"]), catchment_id=settings.catchment_id,
        event_type=EventType.MISSION_ACCEPTED, event_time=dt.datetime.now(dt.UTC),
        payload={"mission_id": mission_id, "volunteer_id": volunteer_id}))


def decline_mission(mission_id: str, volunteer_id: str) -> None:
    m = _mission(mission_id)
    _set_status(mission_id, MissionStatus.DECLINED, assignee_id=None)
    _replan(m["episode_id"])


def complete_mission(mission_id: str, evidence_event_id: str) -> None:
    """G7: record what the contribution actually changed, measured from two snapshots."""
    m = _mission(mission_id)
    realised = _realised_gain(evidence_event_id)
    _set_status(mission_id, MissionStatus.COMPLETED, realised_gain=realised)
    store.append(EventEnvelope(
        stream=_stream_for(m["episode_id"]), catchment_id=settings.catchment_id,
        event_type=EventType.MISSION_COMPLETED, event_time=dt.datetime.now(dt.UTC),
        payload={"mission_id": mission_id, "evidence_event_id": evidence_event_id,
                 "realised_gain": realised}))


# --------------------------------------------------------------------------- expiry


def expire_due_missions(now: dt.datetime | None = None) -> list[str]:
    """FR-23: a sample that did not come back inside its window expires, and we re-plan."""
    now = now or dt.datetime.now(dt.UTC)
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(f"SELECT {','.join(_MISSION_COLS)} FROM missions "
                    "WHERE window_end <= %s AND status = ANY(%s)", (now, list(OPEN_STATUSES)))
        due = [dict(zip(_MISSION_COLS, r, strict=True)) for r in cur.fetchall()]
    expired = []
    for m in due:
        _set_status(m["mission_id"], MissionStatus.EXPIRED)
        store.append(EventEnvelope(
            stream=_stream_for(m["episode_id"]), catchment_id=settings.catchment_id,
            event_type=EventType.MISSION_EXPIRED, event_time=now,
            payload={"mission_id": m["mission_id"], "episode_id": m["episode_id"],
                     "node_id": m["node_id"]}))
        expired.append(m["mission_id"])
    for episode_id in dict.fromkeys(m["episode_id"] for m in due):
        _replan(episode_id)
    return expired


@DBOS.workflow()
def mission_deadline_workflow(mission_id: str) -> None:
    """The punctual half of FR-23; `expire_due_missions` is the certain half."""
    m = _mission(mission_id)
    DBOS.sleep(max((m["window_end"] - dt.datetime.now(dt.UTC)).total_seconds(), 0.0))
    expire_due_missions()


def _replan(episode_id: str) -> None:
    """Plan again from the newest snapshot's PROBE candidates, skipping live nodes.

    An expired mission means nobody went, so the node is still worth visiting - but
    re-issuing a mission for a node that already has an open one would stack duplicates
    on the same volunteer every sweep.
    """
    candidates = _latest_probe_candidates()
    if not candidates:
        log.info("no probe candidates to re-plan episode %s from", episode_id)
        return
    busy = _nodes_with_open_missions(episode_id)
    fresh = [c for c in candidates if c["node_id"] not in busy]
    if fresh:
        create_missions_from_probe(episode_id, fresh)


def _nodes_with_open_missions(episode_id: str) -> set[str]:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT node_id FROM missions WHERE episode_id=%s AND status=ANY(%s)",
                    (episode_id, list(OPEN_STATUSES)))
        return {r[0] for r in cur.fetchall()}


# --------------------------------------------------------------------------- feedback


def get_mission_feedback(mission_id: str) -> dict:
    """What this trip actually changed, in the volunteer's words (G7, PRD 16)."""
    m = _mission(mission_id)
    gain = m["realised_gain"]
    return {"mission_id": mission_id, "status": m["status"], "realised_gain": gain,
            "expected_gain": m["expected_gain"], "effect": _effect_sentence(mission_id, gain)}


def _effect_sentence(mission_id: str, gain: float | None) -> str:
    if gain is None:
        return "This mission has not been completed yet."
    before, after = _snapshots_for(mission_id)
    if before is None or after is None:
        return "Recorded. The effect will be measurable once belief is recomputed."
    n_before, n_after = _live_sources(before), _live_sources(after)
    if gain <= 0:
        return ("Recorded, and it widened the field rather than narrowing it: "
                f"{n_after} possible sources are still in play, against {n_before} before. "
                "That is still worth knowing.")
    if n_after < n_before:
        return (f"Your sample ruled out {n_before - n_after} of {n_before} possible sources. "
                f"{n_after} remain.")
    return (f"Your sample ruled out none outright, but it sharpened the case against "
            f"{n_after} remaining sources.")


LIVE_SOURCE_THRESHOLD = 0.01


def _live_sources(marginals: dict) -> int:
    """How many real entry points still hold meaningful probability."""
    return sum(1 for k, v in marginals.items()
               if not k.startswith("__") and float(v) >= LIVE_SOURCE_THRESHOLD)


def decision_uncertainty(marginals: dict) -> float:
    """1 - sum p^2 over the mutually exclusive outcomes: EC2's edge weight (PRD 7.5).

    The same quantity PROBE maximises the expected reduction of, so a mission's realised
    gain is measured on the scale its expected gain was promised in.
    """
    p = [float(v) for v in marginals.values()]
    total = sum(p) or 1.0
    return 1.0 - sum((x / total) ** 2 for x in p)


def _realised_gain(evidence_event_id: str) -> float | None:
    before, after = _snapshots_around(evidence_event_id)
    if before is None or after is None:
        return None
    return decision_uncertainty(before) - decision_uncertainty(after)


def _snapshots_around(evidence_event_id: str) -> tuple[dict | None, dict | None]:
    """The belief either side of one piece of evidence, found by its sequence number."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT seq, stream FROM events WHERE event_id=%s", (evidence_event_id,))
        row = cur.fetchone()
        if row is None:
            return None, None
        seq, stream = row
        cur.execute("""SELECT source_marginals FROM posterior_snapshots
                       WHERE catchment_id=%s AND stream=%s AND as_of_seq < %s
                       ORDER BY as_of_seq DESC LIMIT 1""",
                    (settings.catchment_id, stream, seq))
        before = cur.fetchone()
        cur.execute("""SELECT source_marginals FROM posterior_snapshots
                       WHERE catchment_id=%s AND stream=%s AND as_of_seq >= %s
                       ORDER BY as_of_seq DESC LIMIT 1""",
                    (settings.catchment_id, stream, seq))
        after = cur.fetchone()
    return (before[0] if before else None), (after[0] if after else None)


def _snapshots_for(mission_id: str) -> tuple[dict | None, dict | None]:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT payload->>'evidence_event_id' FROM events
                       WHERE event_type=%s AND payload->>'mission_id'=%s
                       ORDER BY seq DESC LIMIT 1""",
                    (EventType.MISSION_COMPLETED.value, mission_id))
        row = cur.fetchone()
    return _snapshots_around(row[0]) if row and row[0] else (None, None)


def _latest_probe_candidates() -> list[dict]:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT probe_candidates FROM posterior_snapshots
                       WHERE catchment_id=%s ORDER BY ts DESC LIMIT 1""",
                    (settings.catchment_id,))
        row = cur.fetchone()
    return list(row[0]) if row and row[0] else []


# --------------------------------------------------------------------------- reads


def _mission(mission_id: str) -> dict:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(f"SELECT {','.join(_MISSION_COLS)} FROM missions WHERE mission_id=%s",
                    (mission_id,))
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"no such mission: {mission_id}")
    return dict(zip(_MISSION_COLS, row, strict=True))


def _set_status(mission_id: str, status: MissionStatus, *, realised_gain: float | None = None,
                assignee_id: str | None = None) -> None:
    sets = ["status=%s"]
    args: list = [status.value]
    if realised_gain is not None:
        sets.append("realised_gain=%s")
        args.append(realised_gain)
    if assignee_id is not None:
        sets += ["assignee_id=%s", "assignee_type='volunteer'"]
        args.append(assignee_id)
    args.append(mission_id)
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(f"UPDATE missions SET {','.join(sets)} WHERE mission_id=%s", args)


def _episode_node(episode_id: str) -> str:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT summary->>'top_source' FROM episodes WHERE episode_id=%s",
                    (episode_id,))
        row = cur.fetchone()
    net = get_network()
    top = row[0] if row else None
    return top if top in net.node_index else net.entry_nodes[0]


def _stream_for(episode_id: str) -> str:
    """The stream an episode lives on, so sim work never writes into the live log."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT stream FROM episodes WHERE episode_id=%s", (episode_id,))
        row = cur.fetchone()
    return row[0] if row else "live"


def _dt(epoch: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(float(epoch), dt.UTC)


def _hhmm(epoch: float) -> str:
    return _dt(epoch).strftime("%H:%M")
