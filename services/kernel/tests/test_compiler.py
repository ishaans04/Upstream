import pytest
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network


def test_topological_order_puts_sources_first():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    pos = {n: i for i, n in enumerate(net.topo_order)}
    for e_from, e_to in net.edges:
        assert pos[e_from] < pos[e_to]


def test_upstream_mask_is_transitive():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    i = net.node_index
    #   O14 -> J9 -> R3 -> ZoneA_node
    assert net.upstream_mask[i["O14"], i["J9"]]
    assert net.upstream_mask[i["O14"], i["R3"]]       # transitive
    assert not net.upstream_mask[i["R3"], i["O14"]]   # not symmetric
    assert not net.upstream_mask[i["O9"], i["O14"]]   # sibling branches


def test_downstream_path_edges_are_contiguous():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    path = net.downstream_path[net.node_index["O14"]]
    for a, b in zip(path[:-1], path[1:], strict=True):
        assert net.edges[a][1] == net.edges[b][0]


def test_version_is_stable_and_content_addressed():
    a = compile_network(*toy_gdfs(), catchment_id="toy")
    b = compile_network(*toy_gdfs(), catchment_id="toy")
    assert a.version == b.version and len(a.version) == 16


def test_version_changes_when_an_edge_length_changes():
    nodes, edges, outfalls, zones = toy_gdfs()
    a = compile_network(nodes, edges, outfalls, zones, catchment_id="toy")
    edges.loc[0, "length_m"] = edges.loc[0, "length_m"] + 1.0
    b = compile_network(nodes, edges, outfalls, zones, catchment_id="toy")
    assert a.version != b.version


def test_cycles_are_rejected():
    nodes, edges, outfalls, zones = toy_gdfs()
    edges.loc[len(edges)] = {"edge_id": "back", "from_node": "R3", "to_node": "O14",
                             "length_m": 10.0, "mean_flow_m3s": 0.01, "geometry": None}
    with pytest.raises(ValueError, match="cycle"):
        compile_network(nodes, edges, outfalls, zones, catchment_id="toy")
