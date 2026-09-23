import datetime as dt

import numpy as np
import pytest
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.model.hypotheses import KIND_DIFFUSE, KIND_NONE, KIND_POINT, build_grid
from upstream_kernel.model.priors import PriorInputs, log_prior
from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params


def setup(cond="dry", dry_h=48.0):
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    end = dt.datetime(2026, 9, 22, 6, tzinfo=dt.UTC)
    g = build_grid(net, horizon_start=end - dt.timedelta(hours=6), horizon_end=end)
    B = int((g.horizon_end - g.horizon_start) // g.bin_s)
    inputs = PriorInputs(
        flow_condition_by_bin=np.full(B, FLOW_CONDITIONS.index(cond), dtype=np.int8),
        antecedent_dry_h=np.full(B, dry_h),
        past_episode_count=np.zeros(len(net.entry_idx), dtype=np.int32),
        ecology_pressure=np.zeros(len(net.entry_idx)))
    return net, g, inputs


def test_prior_is_normalised():
    net, g, inp = setup()
    lp = log_prior(net, g, inp, default_params())
    assert float(np.exp(lp).sum()) == pytest.approx(1.0, rel=1e-9)


def test_storm_raises_cso_prior_relative_to_dry():
    """PRD 7.9 role 1: overflows mostly activate during heavy rain."""
    net, g, dry = setup("dry")
    _, _, storm = setup("storm")
    k_cso = net.entry_nodes.index("O14")     # source_type == 'cso'

    def cso_mass(inp):
        lp = log_prior(net, g, inp, default_params())
        return float(np.exp(lp)[(g.kind == KIND_POINT) & (g.entry_k == k_cso)].sum())

    assert cso_mass(storm) > 3 * cso_mass(dry)


def test_dry_weather_event_points_away_from_cso():
    """PRD 7.9 role 1, converse: a dry-weather event suggests a misconnection."""
    net, g, dry = setup("dry")
    lp = np.exp(log_prior(net, g, dry, default_params()))
    k_cso = net.entry_nodes.index("O14")
    k_storm = net.entry_nodes.index("O9")
    assert lp[(g.entry_k == k_cso)].sum() < lp[(g.entry_k == k_storm)].sum() * 3


def test_first_flush_raises_the_diffuse_hypothesis():
    """PRD 7.9 role 3: first rain after a dry spell washes streets."""
    net, g, wet_after_dry = setup("storm", dry_h=72.0)
    _, _, wet_after_wet = setup("storm", dry_h=1.0)

    def diffuse(inp):
        return float(np.exp(log_prior(net, g, inp, default_params()))[g.kind == KIND_DIFFUSE].sum())

    assert diffuse(wet_after_dry) > diffuse(wet_after_wet)


def test_no_event_holds_most_of_the_prior_mass():
    net, g, inp = setup()
    p = np.exp(log_prior(net, g, inp, default_params()))
    assert p[g.kind == KIND_NONE][0] > 0.9


def test_recurring_source_history_raises_that_entry_prior():
    net, g, inp = setup()
    k = net.entry_nodes.index("O9")
    boosted = PriorInputs(inp.flow_condition_by_bin, inp.antecedent_dry_h,
                          np.array([0, 6], dtype=np.int32), inp.ecology_pressure)
    base = np.exp(log_prior(net, g, inp, default_params()))
    more = np.exp(log_prior(net, g, boosted, default_params()))
    assert more[g.entry_k == k].sum() > base[g.entry_k == k].sum()


def test_a_storm_makes_an_event_more_likely_overall():
    """PRD 7.9 role 1 is about more than which source: storms make spills likelier.

    If the no-event prior were pinned to a constant, the model could only ever argue
    about *which* source given an event, never that an event is more probable at all.
    """
    net, g, dry = setup("dry")
    _, _, storm = setup("storm")
    p_none_dry = float(np.exp(log_prior(net, g, dry, default_params()))[g.kind == KIND_NONE][0])
    p_none_storm = float(np.exp(log_prior(net, g, storm, default_params()))[g.kind == KIND_NONE][0])
    assert p_none_storm < p_none_dry
