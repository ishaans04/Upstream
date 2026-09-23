"""GC-5: a retraction excludes an observation from the model without deleting anything.

That distinction is the whole point of belief replay. The event stays in the log, so a
replay to a moment before the retraction still sees the original observation; only the
*view* the model consumes changes.
"""
import datetime as dt
import uuid
from dataclasses import dataclass

from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.evidence_view import build_observations
from upstream_kernel.physics.params import default_params


@dataclass
class FakeEvent:
    seq: int
    event_id: uuid.UUID
    event_type: str
    event_time: dt.datetime
    payload: dict


def _recorded(seq, node="J9", observer="vol-1", method="citizen_visual_olfactory",
              result="positive", **extra):
    return FakeEvent(seq, uuid.uuid4(), "EvidenceRecorded",
                     dt.datetime(2026, 9, 22, 2, tzinfo=dt.UTC),
                     {"node_id": node, "method": method, "result": result,
                      "observer_id": observer, **extra})


def _net():
    return compile_network(*toy_gdfs(), catchment_id="toy")


def test_retracted_observation_is_excluded():
    net, params = _net(), default_params()
    a, b = _recorded(1), _recorded(2, observer="vol-2")
    retraction = FakeEvent(3, uuid.uuid4(), "EvidenceRetracted",
                           dt.datetime(2026, 9, 22, 3, tzinfo=dt.UTC),
                           {"retracts_event_id": str(a.event_id), "reason": "wrong spot",
                            "retracted_by": "officer-1"})
    obs = build_observations([a, b, retraction], net, params)
    assert [o.event_id for o in obs] == [str(b.event_id)]


def test_replay_before_the_retraction_still_sees_the_observation():
    net, params = _net(), default_params()
    a = _recorded(1)
    retraction = FakeEvent(2, uuid.uuid4(), "EvidenceRetracted",
                           dt.datetime(2026, 9, 22, 3, tzinfo=dt.UTC),
                           {"retracts_event_id": str(a.event_id), "reason": "x",
                            "retracted_by": "officer-1"})
    as_of_before = [e for e in (a, retraction) if e.seq <= 1]
    assert len(build_observations(as_of_before, net, params)) == 1
    assert len(build_observations([a, retraction], net, params)) == 0


def test_unknown_node_is_skipped_not_fatal():
    """The network can be recompiled under a running kernel."""
    net, params = _net(), default_params()
    obs = build_observations([_recorded(1, node="NOT_IN_THIS_NETWORK"), _recorded(2)],
                             net, params)
    assert len(obs) == 1


def test_observer_reliability_overrides_the_default():
    net, params = _net(), default_params()
    obs = build_observations([_recorded(1, observer="trusted-officer")], net, params,
                             observer_reliability={"trusted-officer": 0.98})
    assert obs[0].observer_reliability == 0.98
    assert build_observations([_recorded(2)], net, params)[0].observer_reliability == \
        params.observer_reliability_default


def test_sensor_window_bounds_survive_into_the_observation():
    net, params = _net(), default_params()
    start = dt.datetime(2026, 9, 22, 2, 15, tzinfo=dt.UTC)
    end = dt.datetime(2026, 9, 22, 2, 30, tzinfo=dt.UTC)
    ev = _recorded(1, method="sensor_normal_window", result="negative",
                   window_start=start.isoformat(), window_end=end.isoformat())
    o = build_observations([ev], net, params)[0]
    assert o.window_start == start.timestamp()
    assert o.window_end == end.timestamp()
