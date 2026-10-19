from __future__ import annotations

from types import SimpleNamespace

from sophyane import agent_runtime
from sophyane.neuron_security import (
    NeuronSecurityDecision,
    NeuronSecurityResult,
    NeuronSecurityUnavailable,
)


def test_safe_shell_blocks_neuron_block(monkeypatch):
    monkeypatch.setattr(
        agent_runtime,
        "authorize_shell",
        lambda command: NeuronSecurityResult(
            decision=NeuronSecurityDecision.BLOCK,
            risk=0.9,
            reasons=("semantic: instruction supersession",),
        ),
    )
    monkeypatch.setattr(
        agent_runtime,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("command must not execute")
        ),
    )

    output = agent_runtime.safe_shell("git status")

    assert "rejected by Neuron security" in output
    assert "BLOCK" in output


def test_safe_shell_fails_closed_when_neuron_unavailable(monkeypatch):
    def unavailable(command):
        raise NeuronSecurityUnavailable("backend unavailable")

    monkeypatch.setattr(agent_runtime, "authorize_shell", unavailable)
    monkeypatch.setattr(
        agent_runtime,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("command must not execute")
        ),
    )

    output = agent_runtime.safe_shell("git status")

    assert "Shell command rejected" in output
    assert "backend unavailable" in output


def test_safe_shell_review_preserves_human_confirmation(monkeypatch):
    monkeypatch.setattr(
        agent_runtime,
        "authorize_shell",
        lambda command: NeuronSecurityResult(
            decision=NeuronSecurityDecision.REQUIRE_REVIEW,
            risk=0.25,
            reasons=("restricted_resource_requires_review",),
        ),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    monkeypatch.setattr(
        agent_runtime,
        "run_command",
        lambda arguments, timeout=30: "$ git status\n[exit code: 0]",
    )

    output = agent_runtime.safe_shell("git status")

    assert "[exit code: 0]" in output
