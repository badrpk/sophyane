"""Host-owned failure classification for continuous RSI recovery."""

from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    RETRYABLE = "RETRYABLE"
    REJECTED = "REJECTED"
    SAFETY_HALT = "SAFETY_HALT"


@dataclass(frozen=True)
class FailureDecision:
    category: FailureClass
    reason: str
    retryable: bool
    halt: bool


_SAFETY_MARKERS = (
    "escape", "unverifiable", "protected", "policy", "approval rule",
    "forged", "boundary", "heartbeat integrity", "candidate changed after",
)
_REJECTION_MARKERS = ("preverification", "reverification", "holdout", "regression")


def classify_failure(
    error: BaseException,
    *,
    phase: str = "",
    isolation_verified: bool = True,
    evidence_verified: bool = True,
) -> FailureDecision:
    """Classify a failure without allowing model output to choose recovery."""
    reason = str(error).strip() or type(error).__name__
    lowered = reason.casefold()
    if not isolation_verified or not evidence_verified:
        return FailureDecision(FailureClass.SAFETY_HALT, reason, False, True)
    if any(marker in lowered for marker in _SAFETY_MARKERS):
        return FailureDecision(FailureClass.SAFETY_HALT, reason, False, True)
    if any(marker in lowered for marker in _REJECTION_MARKERS):
        return FailureDecision(FailureClass.REJECTED, reason, False, False)
    if phase.casefold() in {"candidate", "execution"} and isinstance(error, PermissionError):
        return FailureDecision(FailureClass.SAFETY_HALT, reason, False, True)
    return FailureDecision(FailureClass.RETRYABLE, reason, True, False)
