from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any


class NeuronSecurityDecision(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"
    ISOLATE = "ISOLATE"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class NeuronSecurityResult:
    decision: NeuronSecurityDecision
    risk: float
    reasons: tuple[str, ...] = ()
    classifier_version: str = "unknown"
    policy_version: str = "unknown"


class NeuronSecurityUnavailable(RuntimeError):
    """Raised when the configured Neuron security backend cannot be used."""


def _command() -> list[str]:
    configured = os.getenv("SOPHYANE_NEURON_SECURITY_COMMAND", "").strip()
    if configured:
        return configured.split()
    return ["neuron-security"]


def _parse_result(payload: dict[str, Any]) -> NeuronSecurityResult:
    try:
        decision = NeuronSecurityDecision(str(payload["decision"]).upper())
        risk = float(payload.get("risk", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        raise NeuronSecurityUnavailable(
            "Neuron security returned an invalid response."
        ) from exc

    reasons_raw = payload.get("reasons", [])
    if not isinstance(reasons_raw, list):
        reasons_raw = []

    return NeuronSecurityResult(
        decision=decision,
        risk=max(0.0, min(1.0, risk)),
        reasons=tuple(str(item) for item in reasons_raw),
        classifier_version=str(payload.get("classifier_version", "unknown")),
        policy_version=str(payload.get("policy_version", "unknown")),
    )


def authorize_shell(source_text: str, timeout: int = 5) -> NeuronSecurityResult:
    """Authorize a shell action through the local Neuron security facade.

    The adapter does not implement prompt-security logic. It sends a structured
    authorization request to a local Neuron consumer interface and validates the
    normalized response.
    """

    request = {
        "operation": "authorize_action",
        "source_text": source_text,
        "action_type": "shell_process",
        "resource_sensitivity": "restricted",
        "context": {
            "source_repo": "sophyane",
            "component": "agent_runtime.safe_shell",
        },
    }

    try:
        completed = subprocess.run(
            _command(),
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NeuronSecurityUnavailable(
            "Neuron security backend is unavailable."
        ) from exc

    if completed.returncode != 0:
        raise NeuronSecurityUnavailable(
            "Neuron security backend rejected the request transport."
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise NeuronSecurityUnavailable(
            "Neuron security returned invalid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise NeuronSecurityUnavailable(
            "Neuron security returned an invalid response object."
        )

    return _parse_result(payload)
