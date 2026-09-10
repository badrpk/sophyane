from __future__ import annotations

import json
from pathlib import Path

from sophyane.live_coding_doer import LiveProgressReporter
from sophyane.memory import MemoryStore
from sophyane.strict_interactive_doer import (
    StrictInteractiveCodingDoerRuntime,
)


def _runtime(
    tmp_path: Path,
    backend,
) -> StrictInteractiveCodingDoerRuntime:
    return StrictInteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=1,
        protocol_attempts=1,
        progress=LiveProgressReporter(
            heartbeat_seconds=60,
        ),
    )


def _exact_prompt() -> str:
    return (
        "Create exactly one file:\n\n"
        "research/dependency_graph.md\n\n"
        "Success means only that "
        "research/dependency_graph.md "
        "is created and is nonempty."
    )


def _r4_error() -> dict[str, object]:
    return {
        "status": "error",
        "error": (
            "ProtocolError: strict planner failed "
            "for exact single-file contract "
            "'research/dependency_graph.md'; "
            "generic artifact fallback is not permitted"
        ),
        "repair_required": True,
    }


def test_full_runtime_exact_planner_failure_uses_one_backend_call(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def backend(prompt: str, system: str) -> str:
        role = (
            "VERIFIER"
            if "SOPHYANE_ROLE=VERIFIER" in system
            else "PLANNER"
        )
        calls.append(role)

        if role == "PLANNER":
            raise TimeoutError("simulated planner timeout")

        raise AssertionError(
            "semantic verifier must not be called"
        )

    runtime = _runtime(tmp_path, backend)
    result = runtime.run(_exact_prompt())

    assert calls == ["PLANNER"]
    assert result.goal_met is False

    assert (
        result.steps[-1]
        .verification["verification_mode"]
        == "deterministic_exact_single_file_prewrite_failure"
    )

    assert not (
        tmp_path
        / "research"
        / "dependency_graph.md"
    ).exists()

    assert runtime.executor.report.files == []
    assert runtime.executor.report.commands == []


def test_unrelated_error_still_reaches_semantic_verifier(
    tmp_path: Path,
) -> None:
    calls = 0

    def backend(prompt: str, system: str) -> str:
        nonlocal calls
        calls += 1
        return json.dumps({
            "goal_met": False,
            "confidence": 1,
            "missing_requirements": ["incomplete"],
            "next_instruction": "",
            "final_answer": "",
        })

    runtime = _runtime(tmp_path, backend)

    verdict = runtime._verify(
        _exact_prompt(),
        "",
        [],
        [],
        {
            "status": "error",
            "error": "ValueError: unrelated failure",
            "repair_required": True,
        },
    )

    assert calls == 1
    assert verdict["goal_met"] is False


def test_non_exact_prompt_still_reaches_semantic_verifier(
    tmp_path: Path,
) -> None:
    calls = 0

    def backend(prompt: str, system: str) -> str:
        nonlocal calls
        calls += 1
        return json.dumps({
            "goal_met": False,
            "confidence": 1,
            "missing_requirements": ["incomplete"],
            "next_instruction": "",
            "final_answer": "",
        })

    runtime = _runtime(tmp_path, backend)

    verdict = runtime._verify(
        "Create research/dependency_graph.md",
        "",
        [],
        [],
        _r4_error(),
    )

    assert calls == 1
    assert verdict["goal_met"] is False


def test_existing_target_prevents_negative_short_circuit(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "research"
        / "dependency_graph.md"
    )
    target.parent.mkdir(parents=True)
    target.write_text(
        "already present\n",
        encoding="utf-8",
    )

    calls = 0

    def backend(prompt: str, system: str) -> str:
        nonlocal calls
        calls += 1
        return json.dumps({
            "goal_met": False,
            "confidence": 1,
            "missing_requirements": ["semantic review required"],
            "next_instruction": "",
            "final_answer": "",
        })

    runtime = _runtime(tmp_path, backend)

    verdict = runtime._verify(
        _exact_prompt(),
        "",
        [],
        [],
        _r4_error(),
    )

    assert calls == 1
    assert (
        verdict.get("verification_mode")
        != "deterministic_exact_single_file_prewrite_failure"
    )
