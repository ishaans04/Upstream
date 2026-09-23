import datetime as dt

import numpy as np
import pytest
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.model.hypotheses import KIND_NONE, KIND_POINT, build_grid
from upstream_kernel.model.likelihood import Observation, log_likelihood
from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params
from upstream_kernel.physics.tables import build_tables


@pytest.fixture
def ctx():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    params = default_params()
    tables = build_tables(net, params)
    end = dt.datetime(2026, 9, 22, 3, tzinfo=dt.UTC)
    grid = build_grid(net, horizon_start=end - dt.timedelta(hours=3), horizon_end=end)
    return net, params, tables, grid, FLOW_CONDITIONS.index("wet")


def _obs(net, node, t, result, method="citizen_visual_olfactory"):
    return Observation(event_id="e", node_idx=net.node_index[node], t_obs=t,
                       method=method, result=result, value=None,
                       observer_reliability=0.9, window_start=None, window_end=None)


def test_positive_report_favours_upstream_sources_at_the_right_time(ctx):
    net, params, tables, grid, f = ctx
    # An observation at ZA that should be explained by an O14 release ~1 travel time earlier.
    k = net.entry_nodes.index("O14")
    j = net.node_index["ZA"]
    tau = float(tables.tau[f, k, j])
    t_obs = grid.horizon_end - 600
    ll = np.asarray(log_likelihood(_obs(net, "ZA", t_obs, "positive"), grid, tables, f, params))
    fits = ((grid.kind == KIND_POINT) & (grid.entry_k == k)
            & (np.abs(grid.t0 - (t_obs - tau)) < 2 * grid.bin_s))
    assert ll[fits].mean() > ll[grid.kind == KIND_NONE][0]


def test_negative_report_eliminates_hypotheses_whose_plume_should_be_passing(ctx):
    """PRD 7.2: 'checked, looks normal' rules out whole upstream branches.

    The mask has to mean what it says. A window of +/- one bin around the ideal start
    also catches hypotheses that begin *after* the observation, whose plume has not
    arrived yet and which a negative report rightly does not penalise - averaging those
    in halves the apparent effect. Only releases that started before the observation
    should have been visible.

    Measured margins with the current detection curves: mean 0.97 nats below the
    no-event hypothesis, strongest fit 1.21 nats. Phase 9 recalibrates the curves
    against the coverage target, so these thresholds guard the shape of the effect,
    not its exact size.
    """
    net, params, tables, grid, f = ctx
    k = net.entry_nodes.index("O14")
    j = net.node_index["J9"]
    tau = float(tables.tau[f, k, j])
    t_obs = grid.horizon_end - 1200
    ll = np.asarray(log_likelihood(_obs(net, "J9", t_obs, "negative"), grid, tables, f, params))
    ideal = t_obs - tau
    overhead = (grid.entry_k == k) & (grid.t0 <= ideal) & (grid.t0 > ideal - grid.bin_s)
    none = ll[grid.kind == KIND_NONE][0]

    assert overhead.sum() > 0
    assert ll[overhead].mean() < none - 0.7
    assert ll[overhead].min() < none - 1.0


def test_negative_report_does_not_penalise_unrelated_branches(ctx):
    net, params, tables, grid, f = ctx
    t_obs = grid.horizon_end - 1200
    ll = np.asarray(log_likelihood(_obs(net, "J9", t_obs, "negative"), grid, tables, f, params))
    k_other = net.entry_nodes.index("O9")
    tau_other = float(tables.tau[f, k_other, net.node_index["J9"]])

    # "Far in time" has to account for the release still running. A three-hour spill
    # that began three hours ago is still passing the node, so it is not unrelated -
    # and the model is right to penalise it. Restrict to hypotheses whose plume has
    # finished passing, with a margin of several dispersion widths on the trailing edge.
    sigma = float(tables.sigma[f, k_other, net.node_index["J9"]])
    finished = (grid.entry_k == k_other) & (
        grid.t0 + grid.duration_s + tau_other + 8 * sigma < t_obs)
    assert finished.sum() > 0
    assert ll[finished].mean() == pytest.approx(ll[grid.kind == KIND_NONE][0], abs=0.15)


def test_a_still_running_release_is_penalised_by_a_negative_report(ctx):
    """The converse of the test above, which is what makes that one meaningful.

    A long release that began hours ago is still flowing past the node, so a negative
    report there is evidence against it - being old is not the same as being over.
    """
    net, params, tables, grid, f = ctx
    t_obs = grid.horizon_end - 1200
    ll = np.asarray(log_likelihood(_obs(net, "J9", t_obs, "negative"), grid, tables, f, params))
    k_other = net.entry_nodes.index("O9")
    tau_other = float(tables.tau[f, k_other, net.node_index["J9"]])
    still_running = ((grid.entry_k == k_other)
                     & (grid.t0 + tau_other < t_obs)
                     & (grid.t0 + grid.duration_s + tau_other > t_obs))
    assert still_running.sum() > 0
    assert ll[still_running].mean() < ll[grid.kind == KIND_NONE][0] - 0.5


def test_far_downstream_positive_counts_for_less_than_a_near_one(ctx):
    """Dilution and decay mean a distant report is weaker evidence, automatically."""
    net, params, tables, grid, f = ctx
    k = net.entry_nodes.index("O14")
    t = grid.horizon_end - 600
    near = np.asarray(log_likelihood(_obs(net, "J9", t, "positive"), grid, tables, f, params))
    far = np.asarray(log_likelihood(_obs(net, "ZB", t, "positive"), grid, tables, f, params))

    def spread(a):
        return a[grid.entry_k == k].max() - a[grid.kind == KIND_NONE][0]

    assert spread(near) > spread(far)


def test_false_positive_rate_keeps_likelihood_finite_everywhere(ctx):
    net, params, tables, grid, f = ctx
    ll = np.asarray(log_likelihood(_obs(net, "ZB", grid.horizon_start + 60, "positive"),
                                   grid, tables, f, params))
    assert np.all(np.isfinite(ll))


def test_low_reliability_observer_moves_the_posterior_less(ctx):
    net, params, tables, grid, f = ctx
    t = grid.horizon_end - 600
    good = _obs(net, "J9", t, "positive")
    weak = Observation(**{**good.__dict__, "observer_reliability": 0.3})
    a = np.asarray(log_likelihood(good, grid, tables, f, params))
    b = np.asarray(log_likelihood(weak, grid, tables, f, params))
    assert (a.max() - a.min()) > (b.max() - b.min())


def test_quantitative_lab_value_uses_a_lognormal_likelihood(ctx):
    net, params, tables, grid, f = ctx
    o = Observation(event_id="e", node_idx=net.node_index["R3"], t_obs=grid.horizon_end - 600,
                    method="lab_ecoli", result="quantitative", value=2400.0,
                    observer_reliability=1.0, window_start=None, window_end=None)
    ll = np.asarray(log_likelihood(o, grid, tables, f, params))
    assert np.all(np.isfinite(ll)) and ll.std() > 0
