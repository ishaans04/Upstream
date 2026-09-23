"""Turn the raw event list into the observation set the model consumes.

GC-5: retracted evidence is excluded here. The events themselves are never deleted, so a
belief replay to a moment before the retraction still sees the original observation.
"""
from __future__ import annotations

import datetime as dt

from .model.likelihood import Observation


def _as_epoch(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, int | float):
        return float(v)
    try:
        return dt.datetime.fromisoformat(str(v)).timestamp()
    except ValueError:
        return None


def build_observations(events, net, params, observer_reliability: dict[str, float] | None = None
                       ) -> list[Observation]:
    reliability = observer_reliability or {}
    retracted: set[str] = {str(e.payload["retracts_event_id"])
                           for e in events if e.event_type == "EvidenceRetracted"}
    out: list[Observation] = []
    for e in events:
        if e.event_type != "EvidenceRecorded" or str(e.event_id) in retracted:
            continue
        p = e.payload
        node = p["node_id"]
        if node not in net.node_index:
            continue                                  # network changed under us; skip cleanly
        out.append(Observation(
            event_id=str(e.event_id), node_idx=net.node_index[node],
            t_obs=e.event_time.timestamp(), method=p["method"], result=p["result"],
            value=p.get("value"),
            observer_reliability=reliability.get(p["observer_id"],
                                                 params.observer_reliability_default),
            # Sensor "normal for this window" evidence carries its own bounds; keeping
            # them lets a consumer reason about the slice, not just the instant.
            window_start=_as_epoch(p.get("window_start")),
            window_end=_as_epoch(p.get("window_end"))))
    return out
