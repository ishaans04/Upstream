from functools import lru_cache

from upstream_kernel.compile.loader import load_network, snap_point_to_node

from .config import settings


@lru_cache(maxsize=1)
def get_network():
    return load_network(settings.network_artifact)


def snap(lon: float, lat: float) -> tuple[str, float]:
    return snap_point_to_node(get_network(), lon, lat, settings.snap_max_distance_m)
