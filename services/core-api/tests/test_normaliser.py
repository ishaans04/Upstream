import pytest
from pydantic import ValidationError
from upstream_api.ingest.normaliser import (
    ClaudeNormaliser,
    NormalisedReport,
    StubNormaliser,
    get_normaliser,
)
from upstream_shared.evidence import ObservationResult


def test_stub_detects_a_negative_report():
    r = StubNormaliser().propose(
        "Had a look at the bridge, water looks completely normal", None, None)
    assert r.result is ObservationResult.NEGATIVE


def test_stub_detects_a_positive_sewage_report():
    r = StubNormaliser().propose("strong sewage smell and grey foam near outfall 14", None, None)
    assert r.result is ObservationResult.POSITIVE
    assert "sewage_smell" in r.observed_signs


def test_normalised_report_rejects_confidence_outside_unit_interval():
    with pytest.raises(ValidationError):
        NormalisedReport(method="citizen_freetext", result="positive", value=None, unit=None,
                         oah_codes=[], observed_signs=[], confidence=1.4, rationale="x")


def test_get_normaliser_falls_back_to_stub_without_an_api_key(monkeypatch):
    monkeypatch.setattr("upstream_api.config.settings.anthropic_api_key", "")
    assert isinstance(get_normaliser(), StubNormaliser)


def test_claude_normaliser_pins_the_model_id():
    assert ClaudeNormaliser.MODEL == "claude-opus-5"
