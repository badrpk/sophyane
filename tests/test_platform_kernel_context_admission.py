from __future__ import annotations

from pathlib import Path

from sophyane.platform_kernel import (
    AgentSpec,
    SubAgentRuntime,
)
from sophyane.providers.base import ProviderCapabilities


def test_legacy_unknown_capacity_preserves_full_context(
    tmp_path: Path,
) -> None:
    seen: list[str] = []

    runtime = SubAgentRuntime(
        lambda prompt, system: seen.append(prompt) or "OK",
        tmp_path,
    )

    context = (
        "CONTEXT_BEGIN_"
        + ("X" * 12000)
        + "_CONTEXT_END"
    )

    result = runtime.run(
        AgentSpec(
            "tester",
            "test",
        ),
        "inspect project",
        context,
    )

    assert result.ok
    assert len(seen) == 1

    prompt = seen[0]

    assert "inspect project" in prompt
    assert "CONTEXT_BEGIN_" in prompt
    assert "_CONTEXT_END" in prompt


def test_provider_managed_context_preserves_full_context(
    tmp_path: Path,
) -> None:
    seen: list[str] = []

    runtime = SubAgentRuntime(
        lambda prompt, system: seen.append(prompt) or "OK",
        tmp_path,
        capabilities=ProviderCapabilities(
            provider_managed_context=True,
            provider_managed_output=True,
        ),
    )

    context = (
        "MANAGED_BEGIN_"
        + ("M" * 15000)
        + "_MANAGED_END"
    )

    result = runtime.run(
        AgentSpec(
            "browser",
            "analysis",
        ),
        "analyze complete artifact",
        context,
    )

    assert result.ok

    prompt = seen[0]

    assert "MANAGED_BEGIN_" in prompt
    assert "_MANAGED_END" in prompt
    assert "analyze complete artifact" in prompt


def test_bounded_provider_drops_optional_context_but_keeps_task(
    tmp_path: Path,
) -> None:
    seen: list[str] = []

    runtime = SubAgentRuntime(
        lambda prompt, system: seen.append(prompt) or "OK",
        tmp_path,
        capabilities=ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        ),
    )

    context = (
        "OPTIONAL_BEGIN_"
        + ("O" * 9000)
        + "_OPTIONAL_END"
    )

    task = (
        "TASK_BEGIN_"
        + ("T" * 700)
        + "_TASK_END"
    )

    result = runtime.run(
        AgentSpec(
            "local",
            "coder",
        ),
        task,
        context,
    )

    assert result.ok

    prompt = seen[0]

    assert "TASK_BEGIN_" in prompt
    assert "_TASK_END" in prompt
    assert "OPTIONAL_BEGIN_" not in prompt
    assert "_OPTIONAL_END" not in prompt


def test_capability_resolver_is_evaluated_per_run(
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    managed = [True]

    def capabilities() -> ProviderCapabilities:
        if managed[0]:
            return ProviderCapabilities(
                provider_managed_context=True,
            )

        return ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        )

    runtime = SubAgentRuntime(
        lambda prompt, system: seen.append(prompt) or "OK",
        tmp_path,
        capabilities=capabilities,
    )

    context = (
        "DYNAMIC_BEGIN_"
        + ("D" * 8000)
        + "_DYNAMIC_END"
    )

    runtime.run(
        AgentSpec(
            "dynamic",
            "analysis",
        ),
        "keep this task",
        context,
    )

    managed[0] = False

    runtime.run(
        AgentSpec(
            "dynamic",
            "analysis",
        ),
        "keep this task",
        context,
    )

    assert "DYNAMIC_BEGIN_" in seen[0]
    assert "_DYNAMIC_END" in seen[0]

    assert "DYNAMIC_BEGIN_" not in seen[1]
    assert "_DYNAMIC_END" not in seen[1]

    assert "keep this task" in seen[0]
    assert "keep this task" in seen[1]


def test_invalid_capability_resolver_is_conservative(
    tmp_path: Path,
) -> None:
    seen: list[str] = []

    runtime = SubAgentRuntime(
        lambda prompt, system: seen.append(prompt) or "OK",
        tmp_path,
        capabilities=lambda: {
            "context_window_tokens": 1,
        },
    )

    context = (
        "UNKNOWN_BEGIN_"
        + ("U" * 7000)
        + "_UNKNOWN_END"
    )

    result = runtime.run(
        AgentSpec(
            "unknown",
            "analysis",
        ),
        "preserve request",
        context,
    )

    assert result.ok
    assert "UNKNOWN_BEGIN_" in seen[0]
    assert "_UNKNOWN_END" in seen[0]
