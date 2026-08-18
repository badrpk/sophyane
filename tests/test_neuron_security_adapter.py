from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sophyane import neuron_security
from sophyane.neuron_security import (
    NeuronSecurityDecision,
    NeuronSecurityUnavailable,
)


def test_authorize_shell_builds_restricted_shell_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["request"] = json.loads(kwargs["input"])
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "decision": "REQUIRE_REVIEW",
                    "risk": 0.25,
                    "reasons": ["restricted_resource_requires_review"],
                    "classifier_version": "prompt-security-api-v1",
                    "policy_version": "1",
                }
            ),
        )

    monkeypatch.setattr(neuron_security.subprocess, "run", fake_run)

    result = neuron_security.authorize_shell("git status")

    assert captured["request"] == {
        "operation": "authorize_action",
        "source_text": "git status",
        "action_type": "shell_process",
        "resource_sensitivity": "restricted",
        "context": {
            "source_repo": "sophyane",
            "component": "agent_runtime.safe_shell",
        },
    }
    assert result.decision is NeuronSecurityDecision.REQUIRE_REVIEW
    assert result.risk == 0.25


def test_authorize_shell_rejects_invalid_backend_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        neuron_security.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not-json"),
    )

    with pytest.raises(NeuronSecurityUnavailable):
        neuron_security.authorize_shell("git status")


def test_authorize_shell_fails_closed_when_backend_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise OSError("missing backend")

    monkeypatch.setattr(neuron_security.subprocess, "run", fail)

    with pytest.raises(NeuronSecurityUnavailable):
        neuron_security.authorize_shell("git status")
