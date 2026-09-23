"""Episode states and the posterior thresholds that move between them."""
from enum import StrEnum


class EpisodeState(StrEnum):
    SUSPECTED = "SUSPECTED"
    PROBABLE = "PROBABLE"
    CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"
    RESOLVED = "RESOLVED"

    def can_transition_to(self, other: "EpisodeState") -> bool:
        return other in _ALLOWED[self]


# PRD 6.3 state diagram, exactly. SUSPECTED cannot jump straight to CONFIRMED:
# confirmation requires passing through PROBABLE, which is what forces a second
# independent piece of evidence before anything health-facing is published.
_ALLOWED: dict[EpisodeState, set[EpisodeState]] = {
    EpisodeState.SUSPECTED: {EpisodeState.PROBABLE, EpisodeState.REFUTED},
    EpisodeState.PROBABLE: {EpisodeState.CONFIRMED, EpisodeState.REFUTED, EpisodeState.RESOLVED},
    EpisodeState.CONFIRMED: {EpisodeState.RESOLVED},
    EpisodeState.RESOLVED: set(),
    EpisodeState.REFUTED: set(),
}

THRESHOLD_SUSPECTED = 0.50   # PRD 6.3, configurable; tuned in Phase 9
THRESHOLD_PROBABLE = 0.90
THRESHOLD_REFUTED = 0.10
