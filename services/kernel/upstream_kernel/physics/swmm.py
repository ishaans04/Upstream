"""Optional PySWMM seam (PRD 11.2, plan Phase 2 "P1").

The MVP does not use this. It exists so that a pilot city with a calibrated EPA SWMM
model can supply real per-edge velocities without the kernel changing: implement
`velocities_from_swmm` and have `physics.velocity.edge_velocity` defer to it.

Deliberately unimplemented rather than faked - a stub that silently returned Manning
values would hide which numbers a published posterior actually used, and params_version
would not distinguish them (GC-6).
"""
from __future__ import annotations

import numpy as np


def velocities_from_swmm(net, inp_path: str, flow_condition: str) -> np.ndarray:
    """Per-edge velocity (m/s) from a SWMM ensemble run. Not implemented in the MVP."""
    raise NotImplementedError(
        "No calibrated SWMM model is available for this catchment. "
        "The MVP uses the analytic Manning model in physics/velocity.py; "
        "see the 'Stated assumptions' section of the README."
    )
