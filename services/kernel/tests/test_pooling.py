"""PRD 7.7: misconnections and overflows recur at the same place; pool closed episodes."""
import datetime as dt
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
from psycopg.types.json import Jsonb
from upstream_kernel.pooling import (
    MIN_EPISODES,
    ClosedEpisode,
    closed_episodes,
    past_episode_counts,
    pool_episodes,
)

T0 = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
NET = SimpleNamespace(
    entry_nodes=("O1", "O2", "O3", "O4", "O5", "O6"),
    entry_source_type=("cso", "misconnection", "storm_outfall", "industrial", "cso", "unknown"),
    entry_base_rate=np.array([0.004, 0.002, 0.002, 0.002, 0.004, 0.002]),
)


def ep(n: int, marginals: dict, days: int = 0) -> ClosedEpisode:
    return ClosedEpisode(episode_id=f"EE-{n}", opened_at=T0 + dt.timedelta(days=days),
                         marginals={"__none__": 0.0, **marginals})


# An inconclusive episode: the evidence leans to O2 over two neighbours with the same
# base rate, but only half the belief is on it (a citizen-driven episode, PRD 7.7).
def unclear(n: int, days: int = 0) -> ClosedEpisode:
    return ep(n, {"O2": 0.5, "O3": 0.25, "O4": 0.25}, days)


def four_unclear() -> list[ClosedEpisode]:
    return [unclear(k + 1, 30 * k) for k in range(4)]


def test_repeated_episodes_at_one_point_raise_its_pooled_probability():
    rs = pool_episodes(four_unclear(), NET)
    assert rs[0].entry_id == "O2" and rs[0].pooled_probability > 0.5
    assert rs[0].episode_count == 4
    assert rs[0].first_seen == T0 and rs[0].last_seen == T0 + dt.timedelta(days=90)


def test_pooling_sharpens_localisation_beyond_any_single_episode():
    episodes = four_unclear()
    single = max(e.event_marginals()["O2"] for e in episodes)
    assert pool_episodes(episodes, NET)[0].pooled_probability > single


def test_one_unrelated_episode_does_not_erase_a_recurring_source():
    """A product of posteriors would: one episode elsewhere puts ~0 on O2."""
    episodes = [*four_unclear(), ep(9, {"O6": 1.0}, 120)]
    assert pool_episodes(episodes, NET)[0].entry_id == "O2"


def test_a_single_episode_is_not_a_recurring_source():
    assert pool_episodes([ep(1, {"O1": 0.99, "O2": 0.01})], NET) == []
    assert MIN_EPISODES >= 2


def test_episodes_that_disagree_report_nothing():
    spread = [ep(k, {NET.entry_nodes[k % 6]: 1.0}, k) for k in range(6)]
    assert pool_episodes(spread, NET) == []


def test_report_suggests_an_inspection_not_an_accusation():
    """GC-12 / PRD 14.4: recommendations, never accusations."""
    r = pool_episodes(four_unclear(), NET)[0]
    text = r.suggested_action.lower()
    assert "inspect" in text
    assert not any(w in text for w in ("responsible", "polluter", "blame", "culprit", "fault"))


def test_soft_counts_are_the_expected_number_of_episodes_from_each_point():
    counts = past_episode_counts([unclear(1), unclear(2), ep(3, {"O1": 1.0})], NET)
    assert counts[NET.entry_nodes.index("O2")] == pytest.approx(1.0)
    assert counts[NET.entry_nodes.index("O1")] == pytest.approx(1.0)
    assert counts.sum() == pytest.approx(3.0)


def test_updated_priors_feed_back_into_the_next_posterior():
    """Pooled history raises the prior on the point that keeps recurring (PRD 7.9 role 3)."""
    from test_priors import setup
    from upstream_kernel.model.hypotheses import KIND_POINT
    from upstream_kernel.model.priors import PriorInputs, log_prior
    from upstream_kernel.physics.params import default_params

    net, g, before = setup("wet")
    history = [ep(k, {"O14": 0.9, "O9": 0.1}, 30 * k) for k in range(3)]
    after = PriorInputs(before.flow_condition_by_bin, before.antecedent_dry_h,
                        past_episode_counts(history, net), before.ecology_pressure)
    k = net.entry_nodes.index("O14")

    def mass(inp):
        p = np.exp(log_prior(net, g, inp, default_params()))
        return float(p[(g.kind == KIND_POINT) & (g.entry_k == k)].sum())

    assert mass(after) > mass(before)


# ------------------------------------------------------------------ from the database


@pytest.fixture
def seeded(db_conn):
    """Episodes in a catchment of their own, each with the snapshot it closed on."""
    catchment = f"test-pool-{uuid.uuid4().hex[:8]}"
    rows = [("CONFIRMED", "sim"), ("RESOLVED", "sim"), ("REFUTED", "sim"),
            ("PROBABLE", "sim"), ("CONFIRMED", "live")]
    ids = []
    with db_conn.cursor() as cur:
        for n, (state, stream) in enumerate(rows):
            eid, fp = f"EE-P{uuid.uuid4().hex[:6]}", f"sha256:pool-{uuid.uuid4().hex}"
            cur.execute("""INSERT INTO posterior_snapshots (ts,fingerprint,catchment_id,stream,
                           as_of_seq,network_version,kernel_version,params_version,p_event,
                           source_marginals,zone_windows,probe_candidates,explanation)
                           VALUES (now(),%s,%s,%s,%s,'n','test','p',0.99,%s,'{}','[]','{}')""",
                        (fp, catchment, stream, n, Jsonb({"__none__": 0.01, "O2": 0.99})))
            cur.execute("""INSERT INTO episodes (episode_id,catchment_id,stream,state,opened_at,
                           state_changed_at,latest_fingerprint)
                           VALUES (%s,%s,%s,%s,now(),now(),%s)""",
                        (eid, catchment, stream, state, fp))
            ids.append(eid)
    yield catchment, ids
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM episodes WHERE catchment_id=%s", (catchment,))
        cur.execute("DELETE FROM posterior_snapshots WHERE catchment_id=%s", (catchment,))


def test_only_closed_episodes_of_this_catchment_and_stream_are_pooled(db_conn, seeded):
    """REFUTED says nothing happened, an open episode is not finished, and a simulated
    episode must never shape live priors (GC-10)."""
    catchment, ids = seeded
    got = closed_episodes(db_conn, catchment, "sim")
    assert sorted(e.episode_id for e in got) == sorted(ids[:2])
    assert got[0].event_marginals()["O2"] == pytest.approx(1.0)
    assert [e.episode_id for e in closed_episodes(db_conn, catchment, "live")] == [ids[4]]


def test_the_worker_takes_its_history_from_pooling_on_its_own_stream(kernel_worker, db_conn):
    """The worker counted every closed episode in the database, of any catchment or
    stream, by its top source: a simulated incident raised live priors (GC-10)."""
    net = kernel_worker.net
    entry = net.entry_nodes[0]
    K = len(net.entry_idx)
    made = []
    with db_conn.cursor() as cur:
        for stream in ("sim", "live"):
            eid, fp = f"EE-W{uuid.uuid4().hex[:6]}", f"sha256:pool-{uuid.uuid4().hex}"
            cur.execute("""INSERT INTO posterior_snapshots (ts,fingerprint,catchment_id,stream,
                           as_of_seq,network_version,kernel_version,params_version,p_event,
                           source_marginals,zone_windows,probe_candidates,explanation)
                           VALUES (now(),%s,%s,%s,0,'n','test','p',0.99,%s,'{}','[]','{}')""",
                        (fp, kernel_worker.catchment_id, stream,
                         Jsonb({"__none__": 0.01, entry: 0.99})))
            cur.execute("""INSERT INTO episodes (episode_id,catchment_id,stream,state,opened_at,
                           state_changed_at,latest_fingerprint)
                           VALUES (%s,%s,%s,'CONFIRMED',now(),now(),%s)""",
                        (eid, kernel_worker.catchment_id, stream, fp))
            made.append(eid)
    try:
        counts = kernel_worker._past_episode_counts(K)
        assert counts[0] == pytest.approx(1.0), "one sim episode, the live one not counted"
        assert counts.sum() == pytest.approx(1.0)
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM episodes WHERE episode_id = ANY(%s)", (made,))
