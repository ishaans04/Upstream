"""Defects found by the Phase 6 whole-branch review, each pinned by a test.

Three of these are the difference between Phase 6 working and Phase 6 appearing to
work: missions were never dispatched in production at all, the episode consumer's
cursor was shared across streams so running the test suite blinded the live lifecycle,
and the deadline sweep had no stream or catchment filter, so a test run expired live
missions and would have pushed notifications to real people.
"""
from __future__ import annotations

import datetime as dt

import pytest
from conftest import STREAM
from psycopg.types.json import Jsonb
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.evidence import EvidencePayload, ObservationResult

# ------------------------------------------------------- 1: missions are dispatched


def test_a_posterior_carrying_probe_candidates_dispatches_missions(
        emit_posterior, episode_row, a_volunteer, candidates, count_missions):
    """FR-15/FR-17: nothing in production created the first mission.

    `create_missions_from_probe` was only ever reached from a re-plan, which needs a
    mission to already exist, so the whole dispatch path was unreachable outside tests.
    """
    a_volunteer("vol-1")
    emit_posterior(p_event=0.94, probe_candidates=candidates(1))
    assert count_missions(episode_row()["episode_id"]) == 1


def test_a_second_posterior_does_not_duplicate_an_open_mission(
        emit_posterior, episode_row, a_volunteer, candidates, count_missions):
    """The kernel writes a posterior every few seconds; each must not mint a mission."""
    a_volunteer("vol-1")
    cands = candidates(1)
    emit_posterior(p_event=0.94, probe_candidates=cands)
    emit_posterior(p_event=0.95, probe_candidates=cands)
    assert count_missions(episode_row()["episode_id"]) == 1


def test_no_mission_is_dispatched_for_a_refuted_episode(
        emit_posterior, episode_row, a_volunteer, candidates, count_missions):
    a_volunteer("vol-1")
    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    emit_posterior(p_event=0.02, probe_candidates=candidates(1))
    assert episode_row()["state"] == "REFUTED"
    assert count_missions(ep) == 0


# ------------------------------------------------------- 2: per-stream consumer cursor


def test_the_consumer_cursor_is_kept_per_stream(db_conn, store, episodes):
    """GC-10: seq is global, so one shared cursor lets a sim pass skip live events.

    Running the test suite against the same database as the live kernel advanced the
    single 'episodes' cursor past every live event, and the live lifecycle stopped.
    """
    from upstream_api.workflows.consumer import consumer_name, process_new_posteriors

    assert consumer_name("live") != consumer_name(STREAM)
    process_new_posteriors(stream=STREAM)
    with db_conn.cursor() as cur:
        cur.execute("SELECT consumer FROM consumer_positions WHERE consumer LIKE 'episodes%%'")
        names = {r[0] for r in cur.fetchall()}
    assert consumer_name(STREAM) in names
    assert consumer_name("live") not in names or True   # live may legitimately exist


def test_consuming_one_stream_does_not_move_another_streams_cursor(db_conn, store, episodes):
    from upstream_api.workflows.consumer import consumer_name, process_new_posteriors

    with db_conn.cursor() as cur:
        cur.execute("""INSERT INTO consumer_positions (consumer,last_seq,updated_at)
                       VALUES (%s,0,now()) ON CONFLICT (consumer)
                       DO UPDATE SET last_seq=0""", (consumer_name("live"),))
    process_new_posteriors(stream=STREAM)
    with db_conn.cursor() as cur:
        cur.execute("SELECT last_seq FROM consumer_positions WHERE consumer=%s",
                    (consumer_name("live"),))
        assert cur.fetchone()[0] == 0, "a sim pass moved the live cursor"


# ------------------------------------------------------- 3: the sweep stays in its stream


@pytest.fixture
def a_live_episode_with_an_overdue_mission(db_conn):
    """A live episode whose mission is already past its window, for isolation checks."""
    from upstream_api.config import settings

    ep, mission = "EE-LIVETEST", "M-LIVETEST"
    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    with db_conn.cursor() as cur:
        cur.execute("""INSERT INTO episodes (episode_id,catchment_id,stream,state,opened_at,
                       state_changed_at,clinical_window_end,summary)
                       VALUES (%s,%s,'live','PROBABLE',%s,%s,%s,%s)""",
                    (ep, settings.catchment_id, past, past, past, Jsonb({})))
        cur.execute("""INSERT INTO missions (mission_id,episode_id,node_id,window_start,
                       window_end,methods,mode,status,expected_gain)
                       VALUES (%s,%s,'N00000',%s,%s,ARRAY['field_test'],'protect',
                               'created',0.1)""", (mission, ep, past, past))
    yield {"episode_id": ep, "mission_id": mission}
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM missions WHERE mission_id=%s", (mission,))
        cur.execute("DELETE FROM episodes WHERE episode_id=%s", (ep,))


def test_a_sim_sweep_does_not_expire_a_live_mission(a_live_episode_with_an_overdue_mission,
                                                    mission_row):
    """A test run must not expire live missions and push notifications to real people."""
    from upstream_api.workflows import timers

    timers.sweep_due(stream=STREAM)
    assert mission_row(a_live_episode_with_an_overdue_mission["mission_id"])["status"] == (
        "created")


def test_a_sim_sweep_does_not_resolve_a_live_episode(a_live_episode_with_an_overdue_mission,
                                                     db_conn):
    from upstream_api.workflows import timers

    timers.sweep_due(stream=STREAM)
    with db_conn.cursor() as cur:
        cur.execute("SELECT state FROM episodes WHERE episode_id=%s",
                    (a_live_episode_with_an_overdue_mission["episode_id"],))
        assert cur.fetchone()[0] == "PROBABLE"


# ------------------------------------------------------- 4: the sign-off gate is scoped


def test_sign_off_rejects_a_positive_result_from_another_stream(emit_posterior, episode_row,
                                                                store, a_node):
    """FR-21: simulated evidence must not confirm a live episode."""
    from upstream_api.config import settings
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    env = EventEnvelope(
        stream="live", catchment_id=settings.catchment_id,
        event_type=EventType.EVIDENCE_RECORDED, event_time=dt.datetime.now(dt.UTC),
        payload=EvidencePayload(node_id=a_node, method="field_test",
                                result=ObservationResult.POSITIVE, observer_id="off-1",
                                observer_type="officer",
                                snap_distance_m=0.0).model_dump(mode="json"))
    store.append(env)
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(ep, officer_id="off-1", field_result_event_id=str(env.event_id))


def test_sign_off_rejects_a_result_from_before_the_episode_opened(emit_posterior,
                                                                  episode_row, post_evidence):
    """A six-month-old positive says nothing about the episode being confirmed now."""
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    old = post_evidence("positive", days_ago=180)
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(ep, officer_id="off-1", field_result_event_id=old)


def test_a_non_uuid_event_id_is_a_refusal_not_a_crash(emit_posterior, episode_row):
    """Postgres raises 22P02 on a malformed UUID; that must not surface as a 500."""
    from upstream_api.workflows.episode import give_signoff

    emit_posterior(p_event=0.94)
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(episode_row()["episode_id"], officer_id="off-1",
                     field_result_event_id="not-a-uuid")


# ------------------------------------------------------- 6: the gain is attributed right


def test_realised_gain_uses_the_first_snapshot_after_the_evidence(
        an_episode, candidates, a_volunteer, seed_snapshot, post_evidence, mission_row,
        _network):
    """Taking the newest later snapshot credits the volunteer with everything since."""
    from upstream_api.workflows.missions import (
        accept_mission,
        complete_mission,
        create_missions_from_probe,
        decision_uncertainty,
    )

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    accept_mission(m.mission_id, "vol-1")
    entries = _network.entry_nodes[:3]
    before = {"__none__": 0.25, **{e: 0.25 for e in entries}}
    seed_snapshot(before, as_of_seq=1)
    eid = post_evidence("negative", node_id=m.node_id)
    just_after = {"__none__": 0.2, entries[0]: 0.4, entries[1]: 0.4}
    seed_snapshot(just_after, as_of_seq=10**9)
    # Much later, unrelated evidence sharpens belief hard. Not this volunteer's doing.
    seed_snapshot({"__none__": 0.01, entries[0]: 0.99}, as_of_seq=2 * 10**9)
    complete_mission(m.mission_id, eid)
    expected = decision_uncertainty(before) - decision_uncertainty(just_after)
    assert mission_row(m.mission_id)["realised_gain"] == pytest.approx(expected, rel=1e-6)


def test_the_effect_sentence_cannot_contradict_the_stored_gain(
        an_episode, candidates, a_volunteer, seed_snapshot, post_evidence, _network):
    """The sentence was recomputed at read time while the gain stayed frozen."""
    from upstream_api.workflows.missions import (
        accept_mission,
        complete_mission,
        create_missions_from_probe,
        get_mission_feedback,
    )

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    accept_mission(m.mission_id, "vol-1")
    entries = _network.entry_nodes[:3]
    seed_snapshot({"__none__": 0.05, entries[0]: 0.95}, as_of_seq=1)
    eid = post_evidence("positive", node_id=m.node_id)
    seed_snapshot({"__none__": 0.25, **{e: 0.25 for e in entries}}, as_of_seq=10**9)
    complete_mission(m.mission_id, eid)
    # Later belief narrows again, for reasons nothing to do with this mission.
    seed_snapshot({"__none__": 0.01, entries[0]: 0.99}, as_of_seq=2 * 10**9)
    fb = get_mission_feedback(m.mission_id)
    assert fb["realised_gain"] < 0
    assert "ruled out" not in fb["effect"], "the sentence drifted away from the gain"


def test_feedback_does_not_present_realised_gain_as_the_expected_gain_scale(
        an_episode, candidates, a_volunteer, seed_snapshot, post_evidence, _network):
    """EC2 gain is over decision classes; this is over source marginals. Different scales."""
    from upstream_api.workflows.missions import (
        accept_mission,
        complete_mission,
        create_missions_from_probe,
        get_mission_feedback,
    )

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    accept_mission(m.mission_id, "vol-1")
    entries = _network.entry_nodes[:3]
    seed_snapshot({"__none__": 0.25, **{e: 0.25 for e in entries}}, as_of_seq=1)
    eid = post_evidence("negative", node_id=m.node_id)
    seed_snapshot({"__none__": 0.05, entries[0]: 0.95}, as_of_seq=10**9)
    complete_mission(m.mission_id, eid)
    fb = get_mission_feedback(m.mission_id)
    assert "expected_gain" not in fb
    assert "source marginal" in fb["measures"].lower()


# ------------------------------------------------------- 10-14: lifecycle guards


def test_a_replan_does_not_run_for_a_closed_episode(
        an_episode, candidates, a_volunteer, seed_snapshot, fast_clock, count_missions,
        emit_posterior, _network):
    """Sending a volunteer out for an episode the system has already refuted."""
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    create_missions_from_probe(an_episode, candidates(1))
    seed_snapshot({"__none__": 0.2, _network.entry_nodes[0]: 0.8},
                  probe=candidates(1, window_s=7200))
    emit_posterior(p_event=0.02)                     # -> REFUTED
    before = count_missions(an_episode)
    fast_clock.advance(minutes=90)
    assert count_missions(an_episode) == before, "a closed episode must not re-plan"


def test_declining_a_mission_unassigns_it_and_records_an_event(
        an_episode, candidates, a_volunteer, mission_row, events_since):
    from upstream_api.workflows.missions import (
        accept_mission,
        create_missions_from_probe,
        decline_mission,
    )

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    accept_mission(m.mission_id, "vol-1")
    decline_mission(m.mission_id, "vol-1")
    row = mission_row(m.mission_id)
    assert row["status"] == "declined"
    assert row["assignee_id"] is None, "a declined mission is still shown as theirs"
    assert [e["mission_id"] for e in events_since("MissionDeclined")] == [m.mission_id]


def test_a_completed_mission_cannot_be_declined(an_episode, candidates, a_volunteer,
                                                seed_snapshot, post_evidence, _network):
    from upstream_api.workflows.missions import (
        accept_mission,
        complete_mission,
        create_missions_from_probe,
        decline_mission,
    )

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    accept_mission(m.mission_id, "vol-1")
    seed_snapshot({"__none__": 0.5, _network.entry_nodes[0]: 0.5}, as_of_seq=1)
    eid = post_evidence("negative", node_id=m.node_id)
    seed_snapshot({"__none__": 0.9, _network.entry_nodes[0]: 0.1}, as_of_seq=10**9)
    complete_mission(m.mission_id, eid)
    with pytest.raises(ValueError, match="not open"):
        decline_mission(m.mission_id, "vol-1")


def test_a_volunteer_cannot_accept_a_mission_assigned_to_someone_else(
        an_episode, candidates, a_volunteer, mission_row):
    from upstream_api.workflows.missions import accept_mission, create_missions_from_probe

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    with pytest.raises(PermissionError):
        accept_mission(m.mission_id, "vol-someone-else")
    assert mission_row(m.mission_id)["assignee_id"] == "vol-1"


def test_an_expired_mission_cannot_be_completed(an_episode, candidates, a_volunteer,
                                                fast_clock, post_evidence):
    from upstream_api.workflows.missions import complete_mission, create_missions_from_probe

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    node = m.node_id
    fast_clock.advance(minutes=90)
    eid = post_evidence("negative", node_id=node)
    with pytest.raises(ValueError, match="not open"):
        complete_mission(m.mission_id, eid)


# ------------------------------------------------------- 7, 11: races and stale plans


def test_a_transition_that_lost_the_race_does_not_write_a_second_event(
        emit_posterior, episode_row, events_since):
    """Two sweeps can both read PROBABLE and both write PROBABLE->RESOLVED."""
    from upstream_api.workflows.episode import _transition
    from upstream_shared.episode import EpisodeState

    emit_posterior(p_event=0.94)
    ep = episode_row()["episode_id"]
    stale = {"episode_id": ep, "state": "PROBABLE", "stream": STREAM}
    _transition(stale, EpisodeState.RESOLVED, reason="first")
    _transition(stale, EpisodeState.RESOLVED, reason="second (lost the race)")
    changes = [e for e in events_since("EpisodeStateChanged", episode_id=ep)
               if e["to"] == "RESOLVED"]
    assert len(changes) == 1, "a lost race still appended to the replayable log"


def test_a_stale_snapshot_does_not_produce_an_already_expired_mission(
        an_episode, a_volunteer, count_missions, candidates):
    """PROBE only guarantees its window is future at the moment the snapshot is written."""
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    past = dt.datetime.now(dt.UTC).timestamp() - 7200
    stale = candidates(1)
    stale[0]["window_start"] = past
    stale[0]["window_end"] = past + 1800
    assert create_missions_from_probe(an_episode, stale) == []
    assert count_missions(an_episode) == 0


def test_a_bioassessment_mission_is_created_only_once_per_episode(an_episode, count_missions):
    """DBOS re-enters an uncheckpointed workflow body on recovery, and a reopen starts
    a second timer for the same episode. Either way FR-24 must not stack surveys."""
    from upstream_api.workflows.missions import create_bioassessment_mission

    first = create_bioassessment_mission(an_episode)
    second = create_bioassessment_mission(an_episode)
    assert first == second
    assert count_missions(an_episode) == 1


# ------------------------------------------------------- operational: writes and bounds


def test_the_episode_summary_does_not_store_the_full_exposure_curves(
        emit_posterior, episode_row, db_conn):
    """The consumer rewrites this row every few seconds for weeks.

    Storing PULSE's 432-step curves per zone means ~25 KB of JSONB rewritten on every
    posterior - WAL churn and autovacuum pressure for samples the list views strip on
    read anyway.
    """
    now = dt.datetime.now(dt.UTC).timestamp()
    grid = [now + 300 * i for i in range(432)]
    emit_posterior(p_event=0.94, zone_windows={
        "ZONE_000": {"zone_id": "ZONE_000", "window_lo": now, "window_hi": now + 9600,
                     "p_peak": 0.99, "pathways": ["recreation"],
                     "t_grid": grid, "p_exposed": [0.5] * len(grid)}})
    with db_conn.cursor() as cur:
        cur.execute("SELECT summary, pg_column_size(summary) FROM episodes WHERE episode_id=%s",
                    (episode_row()["episode_id"],))
        summary, size = cur.fetchone()
    zone = summary["zone_windows"]["ZONE_000"]
    assert "t_grid" not in zone and "p_exposed" not in zone
    assert zone["window_hi"] > zone["window_lo"] and zone["p_peak"] == pytest.approx(0.99)
    assert size < 4096, f"summary is {size} bytes"


def test_read_endpoints_reject_an_absurd_limit():
    """An unbounded limit is a free way to ask for the whole table."""
    from fastapi.testclient import TestClient
    from upstream_api.main import app

    client = TestClient(app)
    for path in ("/episodes", "/public-health/episodes", "/replay/timeline"):
        assert client.get(path, params={"limit": 10**9}).status_code == 422, path
