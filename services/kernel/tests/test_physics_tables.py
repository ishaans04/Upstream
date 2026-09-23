import numpy as np
import pytest
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params
from upstream_kernel.physics.tables import build_tables


@pytest.fixture
def net():
    return compile_network(*toy_gdfs(), catchment_id="toy")


def test_travel_time_increases_downstream(net):
    t = build_tables(net, default_params())
    f = FLOW_CONDITIONS.index("dry")
    k = net.entry_nodes.index("O14")
    i = net.node_index
    assert t.tau[f, k, i["J9"]] < t.tau[f, k, i["R3"]] < t.tau[f, k, i["ZA"]]


def test_unreachable_nodes_are_infinite(net):
    t = build_tables(net, default_params())
    f = 0
    k = net.entry_nodes.index("O14")
    assert np.isinf(t.tau[f, k, net.node_index["O9"]])   # sibling branch, not downstream
    assert not t.reachable[f, k, net.node_index["O9"]]


def test_storm_flow_is_faster_than_dry(net):
    t = build_tables(net, default_params())
    k = net.entry_nodes.index("O14")
    j = net.node_index["ZA"]
    assert t.tau[FLOW_CONDITIONS.index("storm"), k, j] < t.tau[FLOW_CONDITIONS.index("dry"), k, j]


def test_dispersion_grows_with_sqrt_of_travel_time(net):
    t = build_tables(net, default_params())
    f = 0
    k = net.entry_nodes.index("O14")
    i = net.node_index
    r = t.sigma[f, k, i["ZA"]] / t.sigma[f, k, i["J9"]]
    r_expected = np.sqrt(t.tau[f, k, i["ZA"]] / t.tau[f, k, i["J9"]])
    assert r == pytest.approx(r_expected, rel=1e-9)


def test_dilution_decreases_downstream_and_is_bounded(net):
    t = build_tables(net, default_params())
    f = 0
    k = net.entry_nodes.index("O14")
    i = net.node_index
    d = t.dilution[f, k]
    assert 0 < d[i["ZA"]] <= d[i["J9"]] <= 1.0


def test_params_version_is_content_addressed():
    a, b = default_params(), default_params()
    assert a.version == b.version
    c = default_params(velocity_cv=0.5)
    assert c.version != a.version
