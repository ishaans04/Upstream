import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon


def toy_gdfs():
    """O14 and O9 are two outfalls feeding J9; J9 -> R3 -> ZA (Zone A node)."""
    pts = {"O14": (0.0, 0.0), "O9": (0.01, 0.0), "J9": (0.005, -0.01),
           "R3": (0.005, -0.02), "ZA": (0.005, -0.03), "ZB": (0.005, -0.04)}
    nodes = gpd.GeoDataFrame(
        {"node_id": list(pts),
         "node_type": ["outfall", "outfall", "junction", "reach_point", "reach_point", "reach_point"],
         "geometry": [Point(*v) for v in pts.values()]}, crs="EPSG:4326")
    links = [("e1", "O14", "J9", 300.0, 0.02), ("e2", "O9", "J9", 250.0, 0.02),
             ("e3", "J9", "R3", 400.0, 0.05), ("e4", "R3", "ZA", 350.0, 0.06),
             ("e5", "ZA", "ZB", 500.0, 0.06)]
    edges = gpd.GeoDataFrame(
        {"edge_id": [x[0] for x in links], "from_node": [x[1] for x in links],
         "to_node": [x[2] for x in links], "length_m": [x[3] for x in links],
         "mean_flow_m3s": [x[4] for x in links],
         "geometry": [LineString([pts[x[1]], pts[x[2]]]) for x in links]}, crs="EPSG:4326")
    outfalls = gpd.GeoDataFrame(
        {"outfall_id": ["O14", "O9"], "node_id": ["O14", "O9"],
         "source_type": ["cso", "storm_outfall"], "base_rate": [0.004, 0.001],
         "is_synthetic": [False, False],
         "geometry": [Point(*pts["O14"]), Point(*pts["O9"])]}, crs="EPSG:4326")

    def box(c, d=0.002):
        x, y = c
        return Polygon([(x - d, y - d), (x + d, y - d), (x + d, y + d), (x - d, y + d)])

    zones = gpd.GeoDataFrame(
        {"zone_id": ["ZONE_A", "ZONE_B"], "node_id": ["ZA", "ZB"],
         "name": ["Park play area", "Dog walking path"],
         "pathways": [["recreation"], ["animal_contact", "floodwater"]],
         "population_upper_bound": [400, 250],
         "geometry": [box(pts["ZA"]), box(pts["ZB"])]}, crs="EPSG:4326")
    return nodes, edges, outfalls, zones


def line_network_gdfs(n_nodes: int = 400, n_entries: int = 40):
    """A straight chain of n_nodes with n_entries evenly spaced outfalls.

    Used by the Phase 4 latency test to reach PRD scale (40 entries) without needing the
    real catchment. Geometry is a synthetic meridian line; only topology and lengths matter.
    """
    ids = [f"N{i:04d}" for i in range(n_nodes)]
    coords = {n: (0.0, -0.0005 * i) for i, n in enumerate(ids)}
    entry_ids = [ids[i] for i in range(0, n_nodes, max(n_nodes // n_entries, 1))][:n_entries]
    nodes = gpd.GeoDataFrame(
        {"node_id": ids,
         "node_type": ["outfall" if n in entry_ids else "reach_point" for n in ids],
         "geometry": [Point(*coords[n]) for n in ids]}, crs="EPSG:4326")
    edges = gpd.GeoDataFrame(
        {"edge_id": [f"e{i}" for i in range(n_nodes - 1)],
         "from_node": ids[:-1], "to_node": ids[1:],
         "length_m": [250.0] * (n_nodes - 1),
         "mean_flow_m3s": [0.05] * (n_nodes - 1),
         "geometry": [LineString([coords[a], coords[b]])
                      for a, b in zip(ids[:-1], ids[1:], strict=True)]}, crs="EPSG:4326")
    outfalls = gpd.GeoDataFrame(
        {"outfall_id": entry_ids, "node_id": entry_ids,
         "source_type": ["cso"] * n_entries, "base_rate": [0.002] * n_entries,
         "is_synthetic": [True] * n_entries,
         "geometry": [Point(*coords[n]) for n in entry_ids]}, crs="EPSG:4326")

    def box(c, d=0.0002):
        x, y = c
        return Polygon([(x - d, y - d), (x + d, y - d), (x + d, y + d), (x - d, y + d)])

    zone_nodes = ids[-3:]
    zones = gpd.GeoDataFrame(
        {"zone_id": [f"ZONE_{i}" for i in range(3)], "node_id": zone_nodes,
         "name": [f"Zone {i}" for i in range(3)],
         "pathways": [["recreation"]] * 3, "population_upper_bound": [300] * 3,
         "geometry": [box(coords[n]) for n in zone_nodes]}, crs="EPSG:4326")
    return nodes, edges, outfalls, zones
