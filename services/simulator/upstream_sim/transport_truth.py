"""The ground-truth plume, computed without any of the kernel's physics code.

If the simulator used the kernel's tables, the evaluation would only prove that
the kernel agrees with itself. So this module walks the network on its own and
draws its own hydraulics per scenario:

- **velocity**: Manning's equation with a roughness drawn per scenario and a
  further per-reach scatter, so the true travel time differs from the kernel's
  single-valued one by the kind of error a real catchment would impose;
- **dispersion**: an advection-dispersion coefficient in m^2/s (Fischer's form),
  not the kernel's seconds-based Fickian scaling;
- **dilution**: flow-weighted at confluences with per-scenario flow noise;
- **die-off**: a first-order rate drawn per scenario.

A release is a rectangular pulse of `duration_s` at the entry node; at a node
downstream it arrives smeared into the difference of two error functions. The
plateau is `mass x dilution x die-off`, the same scale the detection curves are
calibrated in, because the scale is a property of the world, not of either model.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import erf

# The world's hydraulics: medians and the scatter reality puts around them.
MANNING_N = 0.035
HYDRAULIC_RADIUS_M = 0.35
BED_SLOPE = 0.004
VELOCITY_BY_FLOW = {"dry": 0.6, "wet": 1.0, "storm": 1.8}
FLOW_BY_CONDITION = {"dry": 0.5, "wet": 1.0, "storm": 3.0}
ROUGHNESS_LOG_SD = 0.20          # per scenario
REACH_LOG_SD = 0.15              # per reach, per scenario
DISPERSION_M2S = 60.0            # longitudinal dispersion, median
DISPERSION_LOG_SD = 0.5
FLOW_LOG_SD = 0.20
DECAY_PER_HOUR = 0.12
DECAY_LOG_SD = 0.3

EXPOSURE_THRESHOLD_C = 0.05      # a zone is exposed while the true concentration exceeds this


@dataclass
class TruthPlume:
    """Concentration at any node and time, for one scenario's world."""

    entry_idx: int
    t0: float
    duration_s: float
    mass: float
    arrival_s: np.ndarray          # (N,) seconds from release to node; inf if unreachable
    sigma_s: np.ndarray            # (N,) temporal spread at the node
    dilution: np.ndarray           # (N,)
    decay_per_s: float

    def concentration(self, node_idx, t) -> np.ndarray:
        """True relative concentration; broadcasts over node indices and times."""
        node_idx = np.asarray(node_idx)
        t = np.asarray(t, dtype=float)
        tau = self.arrival_s[node_idx]
        reachable = np.isfinite(tau)
        tau_safe = np.where(reachable, tau, 0.0)
        sig = np.maximum(self.sigma_s[node_idx], 1.0)
        rel = t - self.t0 - tau_safe
        # Rectangular release smeared by a Gaussian: the fraction of the release
        # window "on top of" this moment.
        front = 0.5 * (1 + erf(rel / (np.sqrt(2) * sig)))
        back = 0.5 * (1 + erf((rel - self.duration_s) / (np.sqrt(2) * sig)))
        c = self.mass * self.dilution[node_idx] * np.exp(-self.decay_per_s * tau_safe) \
            * (front - back)
        return np.where(reachable, c, 0.0)

    def exposure_interval(self, node_idx: int, *, step_s: float = 60.0,
                          horizon_s: float = 48 * 3600):
        """When the true concentration at a node exceeds the exposure threshold.

        Returns (first, last, peak time) in epoch seconds, or None if it never does.
        """
        if not np.isfinite(self.arrival_s[node_idx]):
            return None
        t = self.t0 + np.arange(0.0, horizon_s, step_s)
        c = self.concentration(np.full(len(t), node_idx), t)
        above = np.flatnonzero(c > EXPOSURE_THRESHOLD_C)
        if len(above) == 0:
            return None
        return float(t[above[0]]), float(t[above[-1]]), float(t[int(np.argmax(c))])


def truth_plume(net, scenario, rng: np.random.Generator) -> TruthPlume:
    """Draw this scenario's hydraulics and route the release down the network."""
    cond = scenario.flow_condition
    n_edges = len(net.edge_length_m)
    roughness = MANNING_N * rng.lognormal(0.0, ROUGHNESS_LOG_SD)
    v_mean = (1.0 / roughness) * HYDRAULIC_RADIUS_M ** (2 / 3) * np.sqrt(BED_SLOPE)
    velocity = v_mean * VELOCITY_BY_FLOW[cond] * rng.lognormal(0.0, REACH_LOG_SD, n_edges)
    flow = np.asarray(net.edge_mean_flow, dtype=float) * FLOW_BY_CONDITION[cond] \
        * rng.lognormal(0.0, FLOW_LOG_SD, n_edges)
    dispersion = DISPERSION_M2S * rng.lognormal(0.0, DISPERSION_LOG_SD)
    decay = DECAY_PER_HOUR * rng.lognormal(0.0, DECAY_LOG_SD) / 3600.0

    n_nodes = len(net.node_ids)
    inflow = np.zeros(n_nodes)
    for e, (_, to) in enumerate(np.asarray(net.edges)):
        inflow[int(to)] += flow[e]

    entry = list(net.node_ids).index(scenario.entry_node)
    arrival = np.full(n_nodes, np.inf)
    sigma = np.zeros(n_nodes)
    dilution = np.zeros(n_nodes)
    arrival[entry], dilution[entry] = 0.0, 1.0

    # Walk the single downstream path. Spread accumulates as a variance in space
    # (2 D t per reach) and is converted to time at the local velocity.
    t_acc, d_acc, var_x, node = 0.0, 1.0, 0.0, entry
    for e in _downstream_edges(net, entry):
        dt_edge = float(net.edge_length_m[e]) / velocity[e]
        t_acc += dt_edge
        var_x += 2.0 * dispersion * dt_edge
        node = int(net.edges[e][1])
        d_acc *= float(flow[e] / inflow[node]) if inflow[node] > 0 else 1.0
        arrival[node] = t_acc
        sigma[node] = np.sqrt(var_x) / velocity[e]
        dilution[node] = d_acc

    return TruthPlume(entry_idx=entry, t0=scenario.start.timestamp(),
                      duration_s=float(scenario.duration_s), mass=float(scenario.mass),
                      arrival_s=arrival, sigma_s=sigma, dilution=dilution, decay_per_s=decay)


def _downstream_edges(net, node: int) -> list[int]:
    """The edge sequence from `node` to the outlet, found by following out-edges.

    Recomputed here from the edge list rather than read from the compiled network's
    `downstream_path`, so a bug in the compiler's path cannot hide itself by
    appearing on both sides of the comparison.
    """
    out_edge: dict[int, int] = {}
    for e, (frm, _) in enumerate(np.asarray(net.edges)):
        out_edge.setdefault(int(frm), e)
    path, seen = [], set()
    while node in out_edge and node not in seen:
        seen.add(node)
        e = out_edge[node]
        path.append(e)
        node = int(net.edges[e][1])
    return path
