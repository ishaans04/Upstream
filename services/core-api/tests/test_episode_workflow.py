"""Task 6.1: the episode state machine (FR-20..FR-22, PRD 6.3).

Everything here runs on `stream='sim'` so the live catchment's real episodes are
never touched. The fixtures clean up only the sim rows they created; the event log
itself is append-only (GC-5) and is never deleted from - event assertions are
scoped by sequence number instead.
"""
from __future__ import annotations

import datetime as dt

import pytest
from upstream_shared.codes import ObservationMethod
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.evidence import EvidencePayload, ObservationResult

STREAM = "sim"


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def episodes(_pool, db_conn):
    """Isolate the sim stream, and give the test a handle on its own episodes."""
    from upstream_api.config import settings

    def _purge():
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM missions WHERE episode_id IN "
                        "(SELECT episode_id FROM episodes WHERE stream=%s AND catchment_id=%s)",
                        (STREAM, settings.catchment_id))
            cur.execute("DELETE FROM episodes WHERE stream=%s AND catchment_id=%s",
                        (STREAM, settings.catchment_id))

    _purge()
    yield
    _purge()


@pytest.fixture
def seq0(db_conn):
    """The log's high-water mark before the test, so event counts are scoped to it."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT coalesce(max(seq), 0) FROM events")
        return cur.fetchone()[0]


@pytest.fixture
def emit_posterior(store, episodes):
    """Append a PosteriorComputed event exactly as the kernel writes it, then consume it."""
    from upstream_api.config import settings
    from upstream_api.workflows.episode import on_posterior_computed

    def _emit(p_event: float, zone_windows: dict | None = None, *, fingerprint: str = "fp-test"):
        env = EventEnvelope(
            stream=STREAM, catchment_id=settings.catchment_id,
            event_type=EventType.POSTERIOR_COMPUTED,
            event_time=dt.datetime.now(dt.UTC),
            payload={"fingerprint": fingerprint, "p_event": p_event, "as_of_seq": 0,
                     "top_sources": [], "est_start": [None, None],
                     "zone_windows": zone_windows or {}, "probe_candidates": []})
        seq = store.append(env)
        stored = store.read_from(seq - 1, catchment_id=settings.catchment_id,
                                 stream=STREAM, limit=1)[0]
        on_posterior_computed(stored)
        return stored

    return _emit


@pytest.fixture
def episode_row(db_conn):
    from upstream_api.config import settings

    cols = ("episode_id", "state", "opened_at", "state_changed_at", "clinical_window_end")

    def _get(episode_id: str | None = None):
        with db_conn.cursor() as cur:
            if episode_id:
                cur.execute(f"SELECT {','.join(cols)} FROM episodes WHERE episode_id=%s",
                            (episode_id,))
            else:
                cur.execute(f"SELECT {','.join(cols)} FROM episodes WHERE stream=%s "
                            "AND catchment_id=%s ORDER BY opened_at DESC LIMIT 1",
                            (STREAM, settings.catchment_id))
            row = cur.fetchone()
        return dict(zip(cols, row, strict=True)) if row else None

    return _get


@pytest.fixture
def post_evidence(store, a_node):
    """Append one piece of evidence and return its event id."""
    from upstream_api.config import settings

    def _post(result: str, *, method=ObservationMethod.FIELD_TEST, value=None, unit=None,
              days_ago: float = 0.0, node_id: str | None = None) -> str:
        payload = EvidencePayload(
            node_id=node_id or a_node, method=method, result=ObservationResult(result),
            value=value, unit=unit, observer_id="off-1", observer_type="officer",
            snap_distance_m=0.0)
        env = EventEnvelope(
            stream=STREAM, catchment_id=settings.catchment_id,
            event_type=EventType.EVIDENCE_RECORDED,
            event_time=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
            payload=payload.model_dump(mode="json"))
        store.append(env)
        return str(env.event_id)

    return _post


@pytest.fixture
def events_since(db_conn, seq0):
    def _q(event_type: str, episode_id: str | None = None) -> list[dict]:
        sql = "SELECT payload FROM events WHERE seq > %s AND event_type=%s"
        args: list = [seq0, event_type]
        if episode_id:
            sql += " AND payload->>'episode_id' = %s"
            args.append(episode_id)
        with db_conn.cursor() as cur:
            cur.execute(sql + " ORDER BY seq", args)
            return [r[0] for r in cur.fetchall()]

    return _q


@pytest.fixture
def fast_clock(db_conn):
    """Make time appear to pass by moving the deadlines back, not the clock forward.

    The durable timer sleeps for 16 days (FR-22) and no test can wait for it. Patching
    the clock forward was the obvious alternative and it is wrong: every event the
    transition writes would then be stamped in the future, which FR-5 rejects outright
    - correctly, because a real system's clock never jumps. Ageing the episode instead
    puts the sweep in exactly the state it would be in on the day, and every event it
    writes still carries a truthful `event_time`.
    """
    import upstream_api.workflows.episode as ep
    from upstream_api.config import settings

    class _Clock:
        def advance(self, **kw):
            delta = dt.timedelta(**kw)
            with db_conn.cursor() as cur:
                cur.execute("UPDATE episodes SET opened_at=opened_at-%s, "
                            "state_changed_at=state_changed_at-%s, "
                            "clinical_window_end=clinical_window_end-%s "
                            "WHERE stream=%s AND catchment_id=%s",
                            (delta, delta, delta, STREAM, settings.catchment_id))
            ep.resolve_due_episodes()

    return _Clock()


# --------------------------------------------------------------------------- tests


def test_episode_opens_as_suspected_above_threshold(emit_posterior, episode_row):
    emit_posterior(p_event=0.62)
    assert episode_row()["state"] == "SUSPECTED"


def test_episode_does_not_open_below_threshold(emit_posterior, episode_row):
    emit_posterior(p_event=0.30)
    assert episode_row() is None


def test_suspected_advances_to_probable(emit_posterior, episode_row):
    emit_posterior(p_event=0.62)
    emit_posterior(p_event=0.94)
    assert episode_row()["state"] == "PROBABLE"


def test_probable_cannot_jump_straight_to_confirmed_without_signoff(emit_posterior, episode_row):
    from upstream_api.workflows.episode import force_state

    emit_posterior(p_event=0.94)
    with pytest.raises(PermissionError):
        force_state(episode_row()["episode_id"], "CONFIRMED")


def test_confirmed_requires_both_a_positive_field_result_and_an_officer(
        emit_posterior, episode_row, post_evidence):
    """FR-21."""
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(ep, officer_id="off-1", field_result_event_id=None)
    eid = post_evidence("positive")
    give_signoff(ep, officer_id="off-1", field_result_event_id=eid)
    assert episode_row(ep)["state"] == "CONFIRMED"


def test_a_negative_field_result_cannot_confirm_an_episode(
        emit_posterior, episode_row, post_evidence):
    """FR-21: the result has to be positive, not merely present."""
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    eid = post_evidence("negative")
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(ep, officer_id="off-1", field_result_event_id=eid)
    assert episode_row(ep)["state"] == "PROBABLE"


def test_a_lab_result_over_the_bathing_water_limit_confirms_an_episode(
        emit_posterior, episode_row, post_evidence):
    """FR-21 says "field or lab result", and every lab result is quantitative."""
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    eid = post_evidence("quantitative", method=ObservationMethod.LAB_ECOLI,
                        value=9000.0, unit="{CFU}/mL")
    give_signoff(ep, officer_id="off-1", field_result_event_id=eid)
    assert episode_row(ep)["state"] == "CONFIRMED"


def test_a_lab_result_under_the_bathing_water_limit_does_not_confirm(
        emit_posterior, episode_row, post_evidence):
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    eid = post_evidence("quantitative", method=ObservationMethod.LAB_ECOLI,
                        value=1.0, unit="{CFU}/mL")          # 100 CFU/100 mL, under 900
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(ep, officer_id="off-1", field_result_event_id=eid)


def test_a_lab_result_in_an_unrecognised_unit_does_not_confirm(
        emit_posterior, episode_row, post_evidence):
    """Fail closed: an unconvertible unit must never be read as "over the limit"."""
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    eid = post_evidence("quantitative", method=ObservationMethod.LAB_ECOLI,
                        value=9000.0, unit="mg/L")
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(ep, officer_id="off-1", field_result_event_id=eid)


def test_retracted_evidence_cannot_confirm_an_episode(
        emit_posterior, episode_row, post_evidence, store):
    """GC-5: a retraction is a new event, and sign-off has to honour it."""
    from upstream_api.config import settings
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    eid = post_evidence("positive")
    store.append(EventEnvelope(
        stream=STREAM, catchment_id=settings.catchment_id,
        event_type=EventType.EVIDENCE_RETRACTED, event_time=dt.datetime.now(dt.UTC),
        payload={"retracts_event_id": eid, "reason": "wrong node", "retracted_by": "off-1"}))
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(ep, officer_id="off-1", field_result_event_id=eid)


def test_falling_probability_refutes_the_episode(emit_posterior, episode_row):
    emit_posterior(p_event=0.62)
    emit_posterior(p_event=0.05)
    assert episode_row()["state"] == "REFUTED"


def test_state_change_emits_an_event_with_old_and_new_state(emit_posterior, events_since):
    emit_posterior(p_event=0.62)
    emit_posterior(p_event=0.94)
    e = events_since("EpisodeStateChanged")[-1]
    assert e["from"] == "SUSPECTED" and e["to"] == "PROBABLE"


def test_clinical_window_is_set_from_the_exposure_window_plus_incubation(
        emit_posterior, episode_row):
    """FR-22 + PRD 7.6: relevance lasts about 16 days after exposure."""
    now = dt.datetime.now(dt.UTC).timestamp()
    windows = {"ZONE_000": {"zone_id": "ZONE_000", "window_lo": now, "window_hi": now + 9600,
                            "p_peak": 0.99, "pathways": ["recreation"]}}
    emit_posterior(p_event=0.94, zone_windows=windows)
    ep = episode_row()
    assert (ep["clinical_window_end"] - ep["opened_at"]).days >= 14


def test_the_clinical_window_runs_from_the_end_of_exposure_not_from_the_report(
        emit_posterior, episode_row):
    """A zone still exposed in six hours stays clinically relevant 16 days after that."""
    later = dt.datetime.now(dt.UTC) + dt.timedelta(hours=6)
    windows = {"ZONE_000": {"zone_id": "ZONE_000", "window_lo": later.timestamp(),
                            "window_hi": later.timestamp() + 3600, "p_peak": 0.99,
                            "pathways": ["recreation"]}}
    emit_posterior(p_event=0.94, zone_windows=windows)
    ep = episode_row()
    assert (ep["clinical_window_end"] - ep["opened_at"]) > dt.timedelta(days=16)


def test_resolved_after_the_clinical_window_elapses(emit_posterior, episode_row, fast_clock):
    emit_posterior(p_event=0.94)
    fast_clock.advance(days=17)
    assert episode_row()["state"] == "RESOLVED"


def test_the_clinical_window_does_not_resolve_an_episode_early(
        emit_posterior, episode_row, fast_clock):
    emit_posterior(p_event=0.94)
    fast_clock.advance(days=15)
    assert episode_row()["state"] == "PROBABLE"


def test_late_evidence_can_reopen_a_resolved_episode_history_preserved(
        emit_posterior, episode_row, post_evidence, events_since, fast_clock):
    """PRD 6.3: any later evidence can reopen an episode; the history is preserved."""
    emit_posterior(p_event=0.94)
    fast_clock.advance(days=17)
    ep = episode_row()["episode_id"]
    post_evidence("quantitative", method=ObservationMethod.LAB_ECOLI, value=9000.0,
                  unit="{CFU}/mL", days_ago=16)
    emit_posterior(p_event=0.97)
    assert len(events_since("EpisodeStateChanged", episode_id=ep)) >= 3
    assert episode_row(ep)["state"] == "PROBABLE"


def test_reopening_reuses_the_episode_rather_than_opening_a_second_one(
        emit_posterior, episode_row, db_conn, fast_clock):
    from upstream_api.config import settings

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    fast_clock.advance(days=17)
    emit_posterior(p_event=0.97)
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM episodes WHERE stream=%s AND catchment_id=%s",
                    (STREAM, settings.catchment_id))
        assert cur.fetchone()[0] == 1
    assert episode_row()["episode_id"] == ep


def test_sign_off_request_is_recorded_as_an_event(emit_posterior, episode_row, events_since):
    from upstream_api.workflows.episode import request_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    request_signoff(ep, reason="two independent positives")
    assert events_since("SignOffRequested", episode_id=ep)[-1]["reason"] == (
        "two independent positives")


# --------------------------------------------------------------- the consumer itself


@pytest.fixture
def consumer_at_now(db_conn):
    """Park the episode consumer at the end of the log, and restore it afterwards."""
    from upstream_api.workflows.consumer import CONSUMER

    with db_conn.cursor() as cur:
        cur.execute("SELECT last_seq FROM consumer_positions WHERE consumer=%s", (CONSUMER,))
        row = cur.fetchone()
        before = row[0] if row else None
        cur.execute("SELECT coalesce(max(seq),0) FROM events")
        cur.execute("""INSERT INTO consumer_positions (consumer,last_seq,updated_at)
                       VALUES (%s,(SELECT coalesce(max(seq),0) FROM events),now())
                       ON CONFLICT (consumer) DO UPDATE SET last_seq=EXCLUDED.last_seq""",
                    (CONSUMER,))
    yield
    with db_conn.cursor() as cur:
        if before is None:
            cur.execute("DELETE FROM consumer_positions WHERE consumer=%s", (CONSUMER,))
        else:
            cur.execute("UPDATE consumer_positions SET last_seq=%s WHERE consumer=%s",
                        (before, CONSUMER))


def _append_posterior(store, p_event: float, stream: str = STREAM):
    from upstream_api.config import settings

    return store.append(EventEnvelope(
        stream=stream, catchment_id=settings.catchment_id,
        event_type=EventType.POSTERIOR_COMPUTED, event_time=dt.datetime.now(dt.UTC),
        payload={"fingerprint": "fp-consumer", "p_event": p_event, "as_of_seq": 0,
                 "top_sources": [], "est_start": [None, None],
                 "zone_windows": {}, "probe_candidates": []}))


def test_the_consumer_opens_an_episode_from_a_posterior_it_has_not_seen(
        store, episodes, episode_row, consumer_at_now):
    from upstream_api.workflows.consumer import process_new_posteriors

    _append_posterior(store, 0.62)
    assert process_new_posteriors(stream=STREAM) == 1
    assert episode_row()["state"] == "SUSPECTED"


def test_the_consumer_does_not_process_the_same_posterior_twice(
        store, episodes, events_since, consumer_at_now):
    """Without a durable position a restart would replay the whole log as new belief."""
    from upstream_api.workflows.consumer import process_new_posteriors

    _append_posterior(store, 0.94)
    assert process_new_posteriors(stream=STREAM) == 1
    assert process_new_posteriors(stream=STREAM) == 0
    assert len(events_since("EpisodeOpened")) == 1


def test_the_consumer_ignores_events_that_are_not_posteriors(
        store, episodes, episode_row, post_evidence, consumer_at_now):
    from upstream_api.workflows.consumer import process_new_posteriors

    post_evidence("positive")
    assert process_new_posteriors(stream=STREAM) == 0
    assert episode_row() is None
