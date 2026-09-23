"""AI normaliser - GC-8: proposes structured fields, never decides anything.

The model output is schema-constrained with the Anthropic SDK's `messages.parse`, so the
result is a validated Pydantic object or an exception, never free-form prose we have to
guess at. The citizen confirms every field before an EvidenceRecorded event is appended.
"""
from __future__ import annotations

import base64
from typing import Protocol

from pydantic import BaseModel, Field
from upstream_shared.codes import ObservationMethod
from upstream_shared.evidence import ObservationResult

from ..config import settings


class NormalisedReport(BaseModel):
    method: ObservationMethod
    result: ObservationResult
    value: float | None = None
    unit: str | None = None
    oah_codes: list[str] = Field(default_factory=list)
    observed_signs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


SYSTEM = """You structure citizen reports about an urban stream for a One Health system.

You do NOT decide whether pollution happened. You only turn what the person wrote or
photographed into fields, and you say plainly when you are unsure.

Rules:
- "looks normal", "nothing unusual", "all clear", "checked, fine" -> result = "negative".
  Negative reports are valuable; never discard them.
- A described smell, colour, foam, sewage debris, fish distress -> result = "positive".
- A numeric test-strip or meter reading -> result = "quantitative", with value and a UCUM unit.
- observed_signs uses these tokens only: sewage_smell, chemical_smell, grey_foam, white_foam,
  discolouration, oil_sheen, sewage_debris, dead_fish, turbid, clear_water, normal_smell.
- confidence is your own confidence in the extraction, not in whether pollution exists.
- rationale is ONE short sentence, written for the person who filed the report to confirm.
"""


class Normaliser(Protocol):
    def propose(self, free_text: str, photo_bytes: bytes | None,
                photo_media_type: str | None) -> NormalisedReport: ...


class ClaudeNormaliser:
    MODEL = "claude-opus-5"

    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def propose(self, free_text, photo_bytes=None, photo_media_type=None) -> NormalisedReport:
        content: list[dict] = []
        if photo_bytes:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": photo_media_type or "image/jpeg",
                "data": base64.b64encode(photo_bytes).decode()}})
        content.append({"type": "text", "text": free_text or "(photo only, no text)"})
        resp = self._client.messages.parse(
            model=self.MODEL,
            # Thinking is on by default for this model, and its tokens come out of
            # max_tokens. A small ceiling here truncates the structured output rather
            # than producing a short one.
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_format=NormalisedReport,
        )
        return resp.parsed_output


_POSITIVE = {"sewage": "sewage_smell", "smell": "sewage_smell", "foam": "grey_foam",
             "grey": "discolouration", "brown": "discolouration", "oil": "oil_sheen",
             "dead fish": "dead_fish", "cloudy": "turbid", "murky": "turbid",
             "debris": "sewage_debris"}
_NEGATIVE = ("looks normal", "nothing unusual", "all clear", "looks fine",
             "no smell", "water is clear", "seems normal")


class StubNormaliser:
    """Deterministic keyword fallback.

    Used in tests and whenever no API key is configured, so the whole pipeline stays
    demonstrable offline and CI never makes a paid network call.
    """

    def propose(self, free_text, photo_bytes=None, photo_media_type=None) -> NormalisedReport:
        text = (free_text or "").lower()
        if any(p in text for p in _NEGATIVE):
            return NormalisedReport(
                method=ObservationMethod.CITIZEN_VISUAL_OLFACTORY,
                result=ObservationResult.NEGATIVE, observed_signs=["clear_water"],
                confidence=0.6, rationale="Report says the water looks normal.")
        signs = sorted({v for k, v in _POSITIVE.items() if k in text})
        if signs:
            return NormalisedReport(
                method=ObservationMethod.CITIZEN_VISUAL_OLFACTORY,
                result=ObservationResult.POSITIVE, observed_signs=signs,
                confidence=0.55,
                rationale=f"Report mentions {', '.join(signs).replace('_', ' ')}.")
        return NormalisedReport(
            method=ObservationMethod.CITIZEN_FREETEXT,
            result=ObservationResult.NEGATIVE, observed_signs=[],
            confidence=0.2,
            rationale="No recognisable pollution sign; please confirm or correct.")


def get_normaliser() -> Normaliser:
    return ClaudeNormaliser() if settings.anthropic_api_key else StubNormaliser()
