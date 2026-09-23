import datetime as dt

import pytest
from upstream_api.ingest.sensor_job import _is_anomalous, derive_sensor_evidence
from upstream_shared.evidence import ObservationResult


def test_anomaly_detected_on_turbidity_spike():
    assert _is_anomalous(parameter="turbidity", value=180.0, baseline_mean=20.0, baseline_sd=5.0)


def test_normal_reading_is_not_an_anomaly():
    assert not _is_anomalous(parameter="turbidity", value=22.0, baseline_mean=20.0,
                             baseline_sd=5.0)


def test_conductivity_anomaly_is_two_sided():
    """Conductivity *drops* when storm water dilutes sewage; turbidity only rises."""
    assert _is_anomalous(parameter="conductivity", value=5.0, baseline_mean=100.0,
                         baseline_sd=10.0)
    assert not _is_anomalous(parameter="turbidity", value=5.0, baseline_mean=100.0,
                             baseline_sd=10.0)


@pytest.mark.integration
def test_quiet_sensor_emits_negative_window_evidence(seeded_normal_sensor):
    """FR-6 + PRD 7.2: 'sensor normal for these 15 minutes' is evidence, not silence."""
    evs = derive_sensor_evidence(window_start=seeded_normal_sensor["start"],
                                 window_end=seeded_normal_sensor["end"])
    evs = [e for e in evs if e.observer_id == seeded_normal_sensor["sensor_id"]]
    assert evs and all(e.result is ObservationResult.NEGATIVE for e in evs)
    assert all(e.method == "sensor_normal_window" for e in evs)


@pytest.mark.integration
def test_negative_window_evidence_carries_its_window(seeded_normal_sensor):
    """The window bounds are what let the kernel rule out a time slice, not just a node."""
    evs = [e for e in derive_sensor_evidence(window_start=seeded_normal_sensor["start"],
                                             window_end=seeded_normal_sensor["end"])
           if e.observer_id == seeded_normal_sensor["sensor_id"]]
    assert evs
    for e in evs:
        assert e.window_start and e.window_end
        assert dt.datetime.fromisoformat(e.window_start) == seeded_normal_sensor["start"]


@pytest.mark.integration
def test_spiking_sensor_emits_positive_evidence(seeded_spiking_sensor):
    evs = derive_sensor_evidence(window_start=seeded_spiking_sensor["start"],
                                 window_end=seeded_spiking_sensor["end"])
    evs = [e for e in evs if e.observer_id == seeded_spiking_sensor["sensor_id"]]
    assert any(e.result is ObservationResult.POSITIVE for e in evs)
