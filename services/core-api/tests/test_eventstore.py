import datetime as dt

import pytest
from upstream_api.eventlog import PostgresEventStore
from upstream_shared.events import EventEnvelope, EventType

pytestmark = pytest.mark.integration


def _env(**kw):
    base = dict(stream="sim", catchment_id="t1", event_type=EventType.EVIDENCE_RECORDED,
                event_time=dt.datetime.now(dt.UTC), payload={"node_id": "J4"})
    return EventEnvelope(**(base | kw))


def test_append_then_read_from(store: PostgresEventStore):
    s1 = store.append(_env())
    s2 = store.append(_env())
    got = store.read_from(s1 - 1, catchment_id="t1", stream="sim")
    assert [e.seq for e in got][-2:] == [s1, s2]


def test_read_from_filters_by_stream(store):
    store.append(_env(stream="sim"))
    store.append(_env(stream="live"))
    got = store.read_from(0, catchment_id="t1", stream="sim")
    assert all(e.stream == "sim" for e in got)


def test_read_as_of_is_the_belief_replay_primitive(store):
    s1 = store.append(_env(payload={"n": 1}))
    store.append(_env(payload={"n": 2}))
    got = store.read_as_of(catchment_id="t1", stream="sim", as_of_seq=s1)
    assert all(e.seq <= s1 for e in got)


def test_late_arriving_event_keeps_its_event_time(store):
    """GC-4: a lab result from three days ago gets seq=now but event_time=then."""
    then = dt.datetime.now(dt.UTC) - dt.timedelta(days=3)
    seq = store.append(_env(event_time=then))
    e = [x for x in store.read_from(seq - 1, catchment_id="t1", stream="sim") if x.seq == seq][0]
    assert e.event_time == then and e.recorded_at > then
