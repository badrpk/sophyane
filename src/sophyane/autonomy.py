"""Bounded autonomy and approval-timeout policy for Sophyane v13."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class RiskLevel(str, Enum):
    SAFE = "safe"
    REVIEW = "review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    risk: RiskLevel
    reason: str
    source: str
    waited_seconds: float = 0.0


class AutonomyPolicy:
    """Classify actions and auto-continue safe actions after a timeout.

    Auto-approval never applies to destructive, privileged, secret-reading,
    network-pipe, or workspace-escape actions.
    """

    BLOCKED_PATTERNS = (
        r"\brm\s+-rf\s+/(?:\s|$)",
        r"\bmkfs\b",
        r"\bdd\s+if=.*\s+of=/dev/",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bchmod\s+-R\s+777\s+/",
        r"(?:^|\s)(?:sudo|su)(?:\s|$)",
        r"curl\b.*\|\s*(?:ba)?sh\b",
        r"wget\b.*\|\s*(?:ba)?sh\b",
        r"\.ssh/(?:id_rsa|id_ed25519)",
        r"(?:printenv|env)\b.*(?:KEY|TOKEN|SECRET|PASSWORD)",
    )

    REVIEW_PATTERNS = (
        r"\bpip\s+install\b",
        r"\bnpm\s+install\b",
        r"\bdocker\s+(?:run|build|compose)\b",
        r"\bgit\s+push\b",
        r"\bcurl\b",
        r"\bwget\b",
    )

    def __init__(
        self,
        *,
        workspace: Path | str | None = None,
        confirmation_timeout: float = 10.0,
        auto_continue_safe: bool = True,
    ) -> None:
        self.workspace = Path(workspace or Path.cwd()).resolve()
        self.confirmation_timeout = max(0.0, float(confirmation_timeout))
        self.auto_continue_safe = bool(auto_continue_safe)

    def classify(self, action: str, *, target: Path | str | None = None) -> tuple[RiskLevel, str]:
        text = action.strip()
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, text, flags=re.I):
                return RiskLevel.BLOCKED, f"blocked dangerous pattern: {pattern}"

        if target is not None:
            candidate = Path(target).expanduser().resolve()
            try:
                candidate.relative_to(self.workspace)
            except ValueError:
                return RiskLevel.BLOCKED, "target escapes configured workspace"

        for pattern in self.REVIEW_PATTERNS:
            if re.search(pattern, text, flags=re.I):
                return RiskLevel.REVIEW, f"external or installation action: {pattern}"

        return RiskLevel.SAFE, "scoped low-risk action"

    def decide(
        self,
        action: str,
        *,
        target: Path | str | None = None,
        confirmer: Callable[[str, float], bool | None] | None = None,
    ) -> ApprovalDecision:
        risk, reason = self.classify(action, target=target)
        if risk is RiskLevel.BLOCKED:
            return ApprovalDecision(False, risk, reason, "guardrail")

        started = time.monotonic()
        response: bool | None = None
        if confirmer is not None:
            response = confirmer(action, self.confirmation_timeout)

        if response is True:
            return ApprovalDecision(True, risk, reason, "human", time.monotonic() - started)
        if response is False:
            return ApprovalDecision(False, risk, "human denied action", "human", time.monotonic() - started)

        # A missing response may auto-continue only for SAFE actions.
        if risk is RiskLevel.SAFE and self.auto_continue_safe:
            elapsed = time.monotonic() - started
            remaining = self.confirmation_timeout - elapsed
            if remaining > 0:
                time.sleep(remaining)
            return ApprovalDecision(
                True,
                risk,
                "no response before timeout; safe action auto-approved",
                "timeout",
                time.monotonic() - started,
            )

        return ApprovalDecision(
            False,
            risk,
            "explicit approval required; timeout cannot approve this risk level",
            "timeout",
            time.monotonic() - started,
        )


AUTONOMOUS_WORKER_POLICY = """
Execution policy:
- Continue autonomously on safe, workspace-scoped file writes, linting, tests,
  compilation, formatting, and non-destructive repair steps.
- When confirmation is requested for a safe action and no response arrives within
  10 seconds, proceed automatically and record timeout_auto_approved in the trace.
- Never auto-approve destructive, privileged, secret-reading, credential-printing,
  workspace-escape, or untrusted download-and-execute actions.
- Continue generate -> execute -> verify -> repair until the stated requirements
  pass objective checks, or until a configured hard iteration/resource limit is
  reached. Never claim success without verification evidence.
""".strip()
