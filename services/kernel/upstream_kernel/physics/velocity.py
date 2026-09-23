import numpy as np

from .params import ParameterSet


def edge_velocity(net, params: ParameterSet, flow_condition: str) -> np.ndarray:
    """Manning's equation: v = (1/n) * R^(2/3) * S^(1/2), scaled by the flow condition.

    ASSUMPTION (PRD R4): uniform hydraulic radius and a single default slope. OSM
    carries no reliable channel slope, and a calibrated SWMM model for an arbitrary
    catchment cannot be built in the hackathon window. The posterior only needs
    *relative* travel times with honest uncertainty, which this provides.
    A pilot city with a real SWMM model drops it in via physics/swmm.py without the
    kernel changing.
    """
    slope = np.full(net.edge_length_m.shape, params.slope_default)
    v = (1.0 / params.manning_n) * params.hydraulic_radius_m ** (2 / 3) * np.sqrt(slope)
    return v * params.velocity_multiplier[flow_condition]


def edge_flow(net, params: ParameterSet, flow_condition: str) -> np.ndarray:
    return net.edge_mean_flow * params.flow_multiplier[flow_condition]
