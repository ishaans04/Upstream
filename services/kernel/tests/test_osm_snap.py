import pytest
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.compile.loader import snap_point_to_node


def test_snaps_to_nearest_node_within_tolerance():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    node_id, dist_m = snap_point_to_node(net, lon=0.0001, lat=0.0001, max_m=100)
    assert node_id == "O14" and dist_m < 100


def test_rejects_points_outside_tolerance():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    with pytest.raises(ValueError, match="too far"):
        snap_point_to_node(net, lon=5.0, lat=45.0, max_m=150)
