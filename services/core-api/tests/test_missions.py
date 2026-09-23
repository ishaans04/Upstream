"""Task 6.2: mission lifecycle, push, expiry and re-planning (FR-15, FR-17, FR-23, FR-24).

Same isolation as the episode tests: everything is on `stream='sim'` and the fixtures
clean up only their own rows.
"""
from __future__ import annotations

import datetime as dt

import pytest

# --------------------------------------------------------------------------- creation


def test_mission_created_from_top_probe_candidate(an_episode, candidates, a_volunteer,
                                                  mission_row):
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    cands = candidates(1)
    specs = create_missions_from_probe(an_episode, cands)
    assert specs, "a candidate inside an available volunteer's area must produce a mission"
    assert specs[0].node_id == cands[0]["node_id"]
    assert "Check" in specs[0].human_summary
    assert mission_row(specs[0].mission_id)["status"] == "created"


def test_mission_creation_emits_an_event(an_episode, candidates, a_volunteer, events_since):
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    specs = create_missions_from_probe(an_episode, candidates(1))
    created = events_since("MissionCreated")
    assert [e["mission_id"] for e in created] == [specs[0].mission_id]


def test_no_mission_is_created_when_nobody_is_available(an_episode, candidates, a_volunteer,
                                                        count_missions):
    """FR-16: a mission nobody can reach in time is not a mission."""
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-busy", available=False)
    assert create_missions_from_probe(an_episode, candidates(1)) == []
    assert count_missions(an_episode) == 0


def test_a_candidate_whose_node_is_not_in_the_network_is_skipped(an_episode, a_volunteer,
                                                                 count_missions):
    """The node id has to resolve to a place on the map before anyone can be sent there."""
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    now = dt.datetime.now(dt.UTC).timestamp()
    bogus = [{"candidate_id": "NOWHERE@1", "node_id": "NOT-A-NODE", "window_start": now,
              "window_end": now + 3600, "methods": ["field_test"], "mode": "protect",
              "ec2_gain": 0.5, "gain_per_cost": 1e-4, "walk_cost_s": 60.0,
              "expected_effect": "x"}]
    assert create_missions_from_probe(an_episode, bogus) == []
    assert count_missions(an_episode) == 0


# --------------------------------------------------------------------------- lifecycle


def test_accepting_a_mission_records_the_volunteer(an_episode, candidates, a_volunteer,
                                                   mission_row):
    from upstream_api.workflows.missions import accept_mission, create_missions_from_probe

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    accept_mission(m.mission_id, "vol-1")
    row = mission_row(m.mission_id)
    assert row["status"] == "accepted" and row["assignee_id"] == "vol-1"


def test_an_expired_mission_cannot_be_accepted(an_episode, candidates, a_volunteer, fast_clock):
    from upstream_api.workflows.missions import accept_mission, create_missions_from_probe

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    fast_clock.advance(minutes=90)
    with pytest.raises(ValueError, match="expired"):
        accept_mission(m.mission_id, "vol-1")


def test_mission_expires_and_triggers_a_replan(an_episode, candidates, a_volunteer,
                                               mission_row, count_missions, events_since,
                                               seed_snapshot, fast_clock, _network):
    """FR-23: re-plan PROBE if a requested sample is not returned within its window."""
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    # The re-plan reads the newest snapshot's probe_candidates, so there has to be one.
    seed_snapshot({"__none__": 0.2, _network.entry_nodes[0]: 0.8},
                  probe=candidates(1, window_s=7200))
    fast_clock.advance(minutes=90)
    assert mission_row(m.mission_id)["status"] == "expired"
    assert len(events_since("MissionExpired")) == 1
    assert count_missions(an_episode) > 1, "a replacement must be planned"


def test_a_completed_mission_does_not_expire(an_episode, candidates, a_volunteer,
                                             mission_row, seed_snapshot, fast_clock,
                                             post_evidence, _network):
    from upstream_api.workflows.missions import (
        accept_mission,
        complete_mission,
        create_missions_from_probe,
    )

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    accept_mission(m.mission_id, "vol-1")
    seed_snapshot({"__none__": 0.5, _network.entry_nodes[0]: 0.5}, as_of_seq=1)
    eid = post_evidence("negative", node_id=m.node_id)
    seed_snapshot({"__none__": 0.9, _network.entry_nodes[0]: 0.1}, as_of_seq=10**9)
    complete_mission(m.mission_id, eid)
    fast_clock.advance(minutes=90)
    assert mission_row(m.mission_id)["status"] == "completed"


# --------------------------------------------------------------------------- feedback


def test_completing_a_mission_records_its_realised_gain(an_episode, candidates, a_volunteer,
                                                        mission_row, seed_snapshot,
                                                        post_evidence, _network):
    from upstream_api.workflows.missions import (
        accept_mission,
        complete_mission,
        create_missions_from_probe,
    )

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    accept_mission(m.mission_id, "vol-1")
    entries = _network.entry_nodes[:3]
    seed_snapshot({"__none__": 0.25, **{e: 0.25 for e in entries}}, as_of_seq=1)
    eid = post_evidence("negative", node_id=m.node_id)
    seed_snapshot({"__none__": 0.1, entries[0]: 0.9}, as_of_seq=10**9)
    complete_mission(m.mission_id, eid)
    assert mission_row(m.mission_id)["realised_gain"] is not None


def test_volunteer_sees_the_measured_effect_of_their_contribution(
        an_episode, candidates, a_volunteer, seed_snapshot, post_evidence, _network):
    """G7 + PRD 16: 'your sample eliminated two of three suspects'."""
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
    assert "ruled out" in fb["effect"]
    assert fb["realised_gain"] > 0, "a negative check upstream must shrink the hypothesis set"


def test_a_contribution_that_widened_the_field_is_not_reported_as_ruling_anything_out(
        an_episode, candidates, a_volunteer, seed_snapshot, post_evidence, _network):
    """Honesty over flattery: belief that spread out must not read as progress."""
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
    fb = get_mission_feedback(m.mission_id)
    assert fb["realised_gain"] < 0
    assert "ruled out" not in fb["effect"]


# --------------------------------------------------------------------------- FR-24


def test_bioassessment_mission_scheduled_after_a_confirmed_episode(an_episode, mission_row):
    from upstream_api.workflows.missions import create_bioassessment_mission

    mid = create_bioassessment_mission(an_episode)
    assert mission_row(mid)["methods"] == ["bioassessment"]


def test_the_bioassessment_window_is_open_for_weeks_not_minutes(an_episode, mission_row):
    """FR-24: a macroinvertebrate survey is a season's work, not a 40-minute errand."""
    from upstream_api.workflows.missions import create_bioassessment_mission

    row = mission_row(create_bioassessment_mission(an_episode))
    assert row["window_end"] - row["window_start"] >= dt.timedelta(days=7)


# --------------------------------------------------------------------------- push


def test_push_is_not_sent_when_the_volunteer_has_no_subscription(a_volunteer):
    from upstream_api.push import send_push

    a_volunteer("vol-no-sub")
    send_push("vol-no-sub", "t", "b", "/")          # must not raise


def test_push_to_an_unknown_volunteer_does_not_raise():
    from upstream_api.push import send_push

    send_push("vol-does-not-exist", "t", "b", "/")


@pytest.fixture
def vapid_configured(monkeypatch):
    """Configure VAPID so `send_push` actually attempts delivery.

    Without this the key check short-circuits and a "push failed" test would pass
    without a push ever having been tried.
    """
    from upstream_api.config import settings

    monkeypatch.setattr(settings, "vapid_private_key", "not-a-real-key", raising=False)
    monkeypatch.setattr(settings, "vapid_subject", "mailto:test@example.org", raising=False)


def test_a_failing_push_reports_failure_rather_than_raising(a_volunteer, vapid_configured):
    from upstream_api.push import send_push

    a_volunteer("vol-1", push={"endpoint": "https://push.invalid/nope",
                               "keys": {"p256dh": "not-a-key", "auth": "nope"}})
    assert send_push("vol-1", "t", "b", "/") is False


def test_a_failing_push_does_not_fail_the_mission(an_episode, candidates, a_volunteer,
                                                  count_missions, vapid_configured):
    """A push service outage must not cost us the mission it was announcing."""
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1", push={"endpoint": "https://push.invalid/nope", "keys":
                               {"p256dh": "not-a-key", "auth": "nope"}})
    specs = create_missions_from_probe(an_episode, candidates(1))
    assert specs and count_missions(an_episode) == 1


def test_a_replan_reads_only_its_own_streams_belief(an_episode, candidates, a_volunteer,
                                                    mission_row, count_missions,
                                                    seed_snapshot, fast_clock, _network,
                                                    db_conn):
    """GC-10: the live kernel writes constantly; a sim episode must not re-plan from it.

    Without a stream filter the newest snapshot in the catchment wins, so whichever
    stream wrote last decides where a volunteer is sent.
    """
    from upstream_api.config import settings
    from upstream_api.workflows.missions import create_missions_from_probe

    a_volunteer("vol-1")
    m = create_missions_from_probe(an_episode, candidates(1))[0]
    seed_snapshot({"__none__": 0.2, _network.entry_nodes[0]: 0.8},
                  probe=candidates(1, window_s=7200))
    # A later snapshot on the *live* stream, with no candidates to re-plan from.
    # `seed_snapshot`'s teardown removes it: kernel_version='test' marks it as ours.
    with db_conn.cursor() as cur:
        cur.execute("""INSERT INTO posterior_snapshots (ts,fingerprint,episode_id,
            catchment_id,stream,as_of_seq,network_version,kernel_version,params_version,
            p_event,source_marginals,zone_windows,probe_candidates,explanation)
            VALUES (now()+interval '1 hour','sha256:live-newer',NULL,%s,'live',1,
                    'net','test','params',0.5,'{}','{}','[]','{}')""",
                    (settings.catchment_id,))
    fast_clock.advance(minutes=90)
    assert mission_row(m.mission_id)["status"] == "expired"
    assert count_missions(an_episode) > 1, "the sim episode must re-plan from the sim belief"
