import datetime as dt

import numpy as np
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.model.hypotheses import KIND_DIFFUSE, KIND_NONE, KIND_POINT, build_grid


def _grid(hours=24):
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    end = dt.datetime(2026, 9, 22, 6, tzinfo=dt.UTC)
    return net, build_grid(net, horizon_start=end - dt.timedelta(hours=hours), horizon_end=end)


def test_grid_size_is_entries_times_bins_times_durations_plus_two():
    net, g = _grid()
    expected = len(net.entry_nodes) * 96 * 3 + 2      # 24 h / 15 min = 96 bins
    assert g.H == expected


def test_exactly_one_none_and_one_diffuse_hypothesis():
    _, g = _grid()
    assert int((g.kind == KIND_NONE).sum()) == 1
    assert int((g.kind == KIND_DIFFUSE).sum()) == 1
    assert int((g.kind == KIND_POINT).sum()) == g.H - 2


def test_start_times_lie_inside_the_horizon():
    _, g = _grid()
    pts = g.kind == KIND_POINT
    assert g.t0[pts].min() >= g.horizon_start
    assert g.t0[pts].max() < g.horizon_end


def test_longer_durations_release_more_mass():
    _, g = _grid()
    pts = g.kind == KIND_POINT
    by_dur = {float(d): g.mass[pts][g.duration_s[pts] == d][0]
              for d in np.unique(g.duration_s[pts])}
    ks = sorted(by_dur)
    assert by_dur[ks[0]] < by_dur[ks[1]] < by_dur[ks[2]]


def test_prd_scale_is_about_eleven_thousand_hypotheses():
    """PRD 7.2: 40 entries x 96 bins x 3 durations ~ 11,500."""

    class FakeNet:
        entry_nodes = tuple(f"O{i}" for i in range(40))
        entry_idx = np.arange(40, dtype=np.int32)

    end = dt.datetime(2026, 9, 22, 6, tzinfo=dt.UTC)
    g = build_grid(FakeNet(), horizon_start=end - dt.timedelta(hours=24), horizon_end=end)
    assert 11_000 <= g.H <= 12_000


def test_the_none_hypothesis_carries_no_mass_and_no_start():
    """'Nothing happened' must be a real, evaluable hypothesis, not a leftover slot."""
    _, g = _grid()
    none = g.kind == KIND_NONE
    assert float(g.mass[none][0]) == 0.0
    assert np.isnan(g.t0[none][0])
    assert int(g.entry_k[none][0]) == -1


def test_the_diffuse_hypothesis_spans_the_whole_horizon():
    """Diffuse runoff is weak but everywhere, so it has no single entry node."""
    _, g = _grid()
    dif = g.kind == KIND_DIFFUSE
    assert int(g.entry_k[dif][0]) == -1
    assert float(g.t0[dif][0]) == g.horizon_start
    assert float(g.duration_s[dif][0]) == g.horizon_end - g.horizon_start
    assert 0.0 < float(g.mass[dif][0]) < 1.0
