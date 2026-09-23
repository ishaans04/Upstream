"""The .npz artefact must survive a round trip unchanged.

Phase 1's exit criterion is that `load_network(...).version` is stable across
builds. That only means anything if loading actually reproduces the arrays the
compiler produced, so this checks the whole structure, not just the hash.
"""
import numpy as np
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.compile.loader import load_network, save_network


def test_save_load_roundtrip_preserves_version_and_arrays(tmp_path):
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    path = str(tmp_path / "network.npz")
    save_network(net, path)
    back = load_network(path)

    assert back.version == net.version
    assert back.catchment_id == net.catchment_id
    assert back.node_ids == net.node_ids
    assert back.node_index == net.node_index
    assert back.entry_nodes == net.entry_nodes
    assert back.entry_source_type == net.entry_source_type
    assert back.zone_ids == net.zone_ids
    assert back.zone_pathways == net.zone_pathways

    for field in ("node_type", "lonlat", "edges", "edge_length_m", "edge_mean_flow",
                  "topo_order", "upstream_mask", "entry_idx", "entry_base_rate",
                  "zone_node_idx", "zone_population"):
        np.testing.assert_array_equal(getattr(back, field), getattr(net, field), err_msg=field)

    assert back.downstream_path.keys() == net.downstream_path.keys()
    for k, v in net.downstream_path.items():
        np.testing.assert_array_equal(back.downstream_path[k], v)


def test_version_is_reproducible_across_two_builds(tmp_path):
    a = compile_network(*toy_gdfs(), catchment_id="toy")
    b = compile_network(*toy_gdfs(), catchment_id="toy")
    pa, pb = str(tmp_path / "a.npz"), str(tmp_path / "b.npz")
    save_network(a, pa)
    save_network(b, pb)
    assert load_network(pa).version == load_network(pb).version
