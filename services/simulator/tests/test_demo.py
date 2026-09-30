"""The demo driver picks an incident worth watching, the same one every time."""
import datetime as dt

from upstream_sim.demo import EXPOSURE_THRESHOLD_C, pick_scenario

NOW = dt.datetime(2026, 9, 30, 5, 0, tzinfo=dt.UTC)          # 10:30 in Delhi


def plume_now(plume, node):
    return plume.concentration(node, NOW.timestamp() + 600)


def test_the_pick_is_deterministic_safe_and_ends_on_a_credible_report(net):
    a = pick_scenario(net, 7, NOW)
    b = pick_scenario(net, 7, NOW)
    sc, _, reports = a
    assert sc.scenario_id == b[0].scenario_id
    assert [r["node_id"] for r in reports] == [r["node_id"] for r in b[2]]
    assert sc.flow_condition != "storm", "no mission may go out in a storm (PRD 7.5)"
    last = reports[-1]
    assert last["result"] == "positive" and last["true_concentration"] > EXPOSURE_THRESHOLD_C
    source = net.node_index[sc.entry_node]
    assert plume_now(a[1], source) > EXPOSURE_THRESHOLD_C, "still under way when checked"
    assert all(r["observed_at"] <= NOW for r in reports)


def test_the_pick_carries_enough_credible_reports_to_open_an_episode(net):
    """One positive among negatives leaves the belief near its prior (about 5%), no
    episode opens and no mission goes out: nothing for the audience to watch."""
    from upstream_sim.demo import MAX_REPLAY, MIN_CREDIBLE_POSITIVES

    for seed in (7, 20260930):
        _, _, reports = pick_scenario(net, seed, NOW)
        credible = [r for r in reports if r["result"] == "positive"
                    and r["true_concentration"] > EXPOSURE_THRESHOLD_C]
        assert len(credible) >= MIN_CREDIBLE_POSITIVES
        assert len(reports) <= MAX_REPLAY


def test_ending_the_demo_takes_only_its_volunteers_off_duty(owner_dsn):
    """Demo volunteers sit beside every outfall for hours and would win the test suite's
    missions; ending the demo frees the network without touching anyone else."""
    import psycopg
    from upstream_sim.demo import end_demo

    box = "POLYGON((77.2 28.5,77.21 28.5,77.21 28.51,77.2 28.51,77.2 28.5))"
    now = dt.datetime.now(dt.UTC)
    ids = ("vol-sim-99", "vol-real-99")
    with psycopg.connect(owner_dsn, autocommit=True) as c, c.cursor() as cur:
        for vid in ids:
            cur.execute("""INSERT INTO volunteers (volunteer_id,display_name,coarse_area,
                           available_from,available_to,reliability)
                           VALUES (%s,%s,ST_GeomFromText(%s,4326),%s,%s,0.8)
                           ON CONFLICT (volunteer_id) DO UPDATE SET
                             available_from=EXCLUDED.available_from,
                             available_to=EXCLUDED.available_to""",
                        (vid, vid, box, now - dt.timedelta(hours=1), now + dt.timedelta(hours=8)))
        try:
            assert end_demo(owner_dsn) >= 1
            cur.execute("""SELECT volunteer_id, available_to <= now() FROM volunteers
                           WHERE volunteer_id = ANY(%s)""", (list(ids),))
            assert dict(cur.fetchall()) == {"vol-sim-99": True, "vol-real-99": False}
        finally:
            cur.execute("DELETE FROM volunteers WHERE volunteer_id = ANY(%s)", (list(ids),))


def test_downstream_nodes_follow_the_edges_not_the_edge_numbers(net):
    """`downstream_path` holds edge indices; reading them as nodes put the demo's
    sensor and zones in the wrong places and the true plume nowhere near them."""
    from upstream_sim.demo_scenario import downstream_nodes

    k = int(net.entry_idx[0])
    nodes = downstream_nodes(net, k)
    assert nodes, "an outfall drains somewhere"
    assert all(net.upstream_mask[k, n] for n in nodes)
    assert int(net.edges[net.downstream_path[k][0]][0]) == k


def test_the_demo_source_has_a_rival_upstream_and_zones_below(net):
    """PRD 10.5's story needs an outfall whose reports cannot be told from a rival's."""
    from upstream_sim.demo_scenario import choose_cast

    source, zones = choose_cast(net)
    k = net.node_index[source]
    assert net.entry_source_type[net.entry_nodes.index(source)] == "cso"
    assert any(net.upstream_mask[int(r), k] for r in net.entry_idx if int(r) != k)
    assert zones and all(
        net.upstream_mask[k, int(net.zone_node_idx[net.zone_ids.index(z)])] for z in zones)
