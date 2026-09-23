"""FR-6: turn raw sensor readings into evidence every 15 minutes.

Two kinds of evidence come out of this job, and the second one matters more:
  * an anomaly ("turbidity spiked at N14"), and
  * a *normal window* ("N14 was normal 02:15-02:30") - negative evidence that rules out
    whole upstream branches for that time slice (PRD 7.2).

Silence from a sensor is not the same as a sensor reporting normal. Only the second is
evidence, which is why the normal window is emitted explicitly rather than inferred from
an absence of anomalies.
"""
from __future__ import annotations

import datetime as dt

from upstream_shared.codes import ObservationMethod
from upstream_shared.evidence import EvidencePayload, ObservationResult

from ..config import settings
from ..db import pool

ANOMALY_SIGMA = 4.0
BASELINE_DAYS = 14


def _is_anomalous(*, parameter: str, value: float, baseline_mean: float,
                  baseline_sd: float) -> bool:
    sd = max(baseline_sd, 1e-6)
    z = (value - baseline_mean) / sd
    # Conductivity *drops* when storm water dilutes sewage; turbidity rises.
    return abs(z) >= ANOMALY_SIGMA if parameter == "conductivity" else z >= ANOMALY_SIGMA


def derive_sensor_evidence(window_start: dt.datetime, window_end: dt.datetime
                           ) -> list[EvidencePayload]:
    out: list[EvidencePayload] = []
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""
            SELECT a.sensor_id, a.node_id, a.parameter, a.mean_value, a.max_value,
                   b.mean_value, b.sd_value
            FROM sensor_15min a
            JOIN LATERAL (
              SELECT avg(mean_value) AS mean_value,
                     coalesce(stddev_samp(mean_value),0) AS sd_value
              FROM sensor_15min h
              WHERE h.sensor_id=a.sensor_id AND h.parameter=a.parameter
                AND h.bucket < %s AND h.bucket > %s - (%s || ' days')::interval
            ) b ON TRUE
            WHERE a.bucket >= %s AND a.bucket < %s AND a.catchment_id = %s
        """, (window_start, window_start, BASELINE_DAYS, window_start, window_end,
              settings.catchment_id))
        for sensor_id, node_id, parameter, _mean_v, max_v, base_mean, base_sd in cur.fetchall():
            if base_mean is None:
                continue
            hit = _is_anomalous(parameter=parameter, value=max_v,
                                baseline_mean=base_mean, baseline_sd=base_sd)
            method = (ObservationMethod.SENSOR_TURBIDITY if parameter == "turbidity"
                      else ObservationMethod.SENSOR_CONDUCTIVITY if parameter == "conductivity"
                      else ObservationMethod.SENSOR_NORMAL_WINDOW)
            out.append(EvidencePayload(
                node_id=node_id,
                method=method if hit else ObservationMethod.SENSOR_NORMAL_WINDOW,
                result=ObservationResult.POSITIVE if hit else ObservationResult.NEGATIVE,
                value=float(max_v), unit="[arb'U]",
                observer_id=sensor_id, observer_type="sensor", snap_distance_m=0.0,
                confirmed_by_observer=True,
                window_start=window_start.isoformat(), window_end=window_end.isoformat()))
    return out
