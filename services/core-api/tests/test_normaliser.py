import pytest
from pydantic import ValidationError
from upstream_api.ingest.normaliser import (
    GroqNormaliser,
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
    monkeypatch.setattr("upstream_api.config.settings.groq_api_key", "")
    assert isinstance(get_normaliser(), StubNormaliser)


def test_groq_normaliser_pins_the_model_id():
    assert GroqNormaliser.MODEL == "openai/gpt-oss-120b"


def test_groq_normaliser_asks_for_the_schema_and_validates_the_answer(monkeypatch):
    """No paid call: a fake client stands in for the SDK and records the request."""
    monkeypatch.setattr("upstream_api.config.settings.groq_api_key", "test-key")
    sent = {}

    class _Msg:
        content = ('{"method": "citizen_visual_olfactory", "result": "positive", '
                   '"observed_signs": ["sewage_smell"], "confidence": 0.8, '
                   '"rationale": "You noticed a sewage smell."}')

    class _Completions:
        def create(self, **kw):
            sent.update(kw)
            return type("R", (), {"choices": [type("C", (), {"message": _Msg()})()]})()

    n = get_normaliser()
    assert isinstance(n, GroqNormaliser)
    n._client = type("Client", (), {"chat": type("Chat", (), {"completions": _Completions()})()})()
    r = n.propose("strong sewage smell near the outfall")
    assert r.result is ObservationResult.POSITIVE and r.observed_signs == ["sewage_smell"]
    assert sent["model"] == "openai/gpt-oss-120b"
    assert sent["response_format"]["json_schema"]["schema"] == NormalisedReport.model_json_schema()


def test_groq_normaliser_rejects_an_answer_outside_the_schema(monkeypatch):
    monkeypatch.setattr("upstream_api.config.settings.groq_api_key", "test-key")

    class _Completions:
        def create(self, **kw):
            msg = type("M", (), {"content": '{"result": "positive", "confidence": 3}'})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    n = get_normaliser()
    n._client = type("Client", (), {"chat": type("Chat", (), {"completions": _Completions()})()})()
    with pytest.raises(ValidationError):
        n.propose("anything")
