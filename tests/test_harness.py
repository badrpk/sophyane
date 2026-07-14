from __future__ import annotations

import pytest

from sophyane.harness import (
    AgentHarness,
    ContextManager,
    Guardrails,
    ModelRegistry,
    ToolRegistry,
    VerificationResult,
)


def test_tool_registry_registers_and_invokes() -> None:
    tools = ToolRegistry()
    tools.register("add", lambda left, right: left + right)
    assert tools.names() == ("add",)
    assert tools.invoke("add", left=20, right=22) == 42


def test_model_registry_falls_back() -> None:
    models = ModelRegistry()
    models.register("broken", lambda prompt, system: (_ for _ in ()).throw(RuntimeError("down")), priority=1)
    models.register("working", lambda prompt, system: "ok", priority=2)
    name, output = models.generate("hello")
    assert (name, output) == ("working", "ok")


def test_context_manager_enforces_budget() -> None:
    context = ContextManager(max_chars=20)
    context.add("user", "1234567890")
    context.add("assistant", "abcdefghij")
    assert len(context.render()) <= 25
    assert "1234567890" not in context.render()


def test_guardrails_block_dangerous_text_and_tools() -> None:
    guardrails = Guardrails()
    assert not guardrails.check_text("rm -rf /").allowed
    tools = ToolRegistry()
    tools.register("shell", lambda command: command, dangerous=True)
    harness = AgentHarness(ModelRegistry(), tools=tools)
    with pytest.raises(PermissionError):
        harness.invoke_tool("shell", command="echo hi")
    assert harness.invoke_tool("shell", approved=True, command="echo hi") == "echo hi"


def test_agent_loop_repairs_after_failed_verification() -> None:
    calls = {"count": 0}

    def backend(prompt: str, system: str) -> str:
        calls["count"] += 1
        return "wrong" if calls["count"] == 1 else "answer=42"

    models = ModelRegistry()
    models.register("test-model", backend)
    harness = AgentHarness(models, max_iterations=3)
    result = harness.run(
        "calculate",
        lambda output: VerificationResult("answer=42" in output, "expected answer=42"),
    )
    assert result.verified is True
    assert result.iterations == 2
    assert [item["step"] for item in result.trace] == ["model", "verify", "model", "verify"]


def test_agent_loop_stops_when_verification_never_passes() -> None:
    models = ModelRegistry()
    models.register("bad", lambda prompt, system: "still wrong")
    result = AgentHarness(models, max_iterations=2).run(
        "task", lambda output: VerificationResult(False, "failed")
    )
    assert result.verified is False
    assert result.iterations == 2
