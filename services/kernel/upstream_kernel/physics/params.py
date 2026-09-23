"""The versioned parameter set.

Everything the forward model needs, in one frozen, content-addressed object. A
posterior fingerprint names a params_version, so changing any number here changes
the hash and makes every snapshot computed under the old numbers identifiable
(GC-6).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

FLOW_CONDITIONS: tuple[str, ...] = ("dry", "wet", "storm")


@dataclass(frozen=True)
class DetectionCurve:
    """P(positive | concentration c) = fp + (1-fp) * logistic((log10 c - log10 c50)/slope)."""

    c50: float
    slope: float
    false_positive: float


@dataclass(frozen=True)
class ParameterSet:
    manning_n: float = 0.035
    hydraulic_radius_m: float = 0.35
    slope_default: float = 0.004
    velocity_multiplier: dict = field(
        default_factory=lambda: {"dry": 0.6, "wet": 1.0, "storm": 1.8})
    velocity_cv: float = 0.30
    # sigma = dispersion_coeff * sqrt(tau), with tau in SECONDS.
    #
    # The unit matters. A coefficient of 0.18 gives sigma ~ 4 s on a nine-minute
    # reach, which is not a travel-time uncertainty anyone would defend. The
    # default below is derived instead from velocity_cv at a reference travel
    # time: coeff = velocity_cv * sqrt(tau_ref) with tau_ref = 1800 s, so a
    # 30-minute reach carries a 30% coefficient of variation and the square-root
    # growth of Fickian dispersion is preserved exactly. Phase 9 recalibrates
    # this against the GC-11 coverage target, which is the real arbiter.
    dispersion_coeff: float = 12.728
    dispersion_ref_tau_s: float = 1800.0
    decay_per_hour: dict = field(default_factory=lambda: {"fecal_indicator": 0.12})
    flow_multiplier: dict = field(
        default_factory=lambda: {"dry": 0.5, "wet": 1.0, "storm": 3.0})
    detection: dict = field(default_factory=lambda: {
        "citizen_visual_olfactory": DetectionCurve(c50=0.30, slope=0.55, false_positive=0.04),
        "citizen_freetext":         DetectionCurve(c50=0.30, slope=0.55, false_positive=0.06),
        "citizen_photo":            DetectionCurve(c50=0.35, slope=0.60, false_positive=0.05),
        "test_strip":               DetectionCurve(c50=0.12, slope=0.40, false_positive=0.03),
        "sensor_turbidity":         DetectionCurve(c50=0.08, slope=0.35, false_positive=0.02),
        "sensor_conductivity":      DetectionCurve(c50=0.10, slope=0.40, false_positive=0.02),
        "sensor_normal_window":     DetectionCurve(c50=0.08, slope=0.35, false_positive=0.02),
        "field_test":               DetectionCurve(c50=0.05, slope=0.30, false_positive=0.01),
        "lab_ecoli":                DetectionCurve(c50=0.02, slope=0.25, false_positive=0.005),
        "lab_enterococci":          DetectionCurve(c50=0.02, slope=0.25, false_positive=0.005),
        "overflow_telemetry":       DetectionCurve(c50=0.01, slope=0.20, false_positive=0.001),
        "bioassessment":            DetectionCurve(c50=0.50, slope=0.80, false_positive=0.10),
    })
    observer_reliability_default: float = 0.7
    version: str = ""

    def __post_init__(self):
        object.__setattr__(self, "version", _hash(self))


def _hash(p: ParameterSet) -> str:
    d = asdict(p)
    d.pop("version", None)
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:16]


def default_params(**overrides) -> ParameterSet:
    return ParameterSet(**overrides)
