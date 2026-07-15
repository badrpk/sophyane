from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from sophyane.cli_entry import _runtime_identity
from sophyane.live_coding_doer import LiveProgressReporter
from sophyane.memory import MemoryStore
from sophyane.strict_interactive_doer import StrictInteractiveCodingDoerRuntime
from sophyane.strict_protocol import parse_and_validate_plan
from sophyane.version import __version__


def test_version_and_runtime_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        "sophyane.cli_entry.load_config",
        lambda: {"provider": "gemini", "model": "gemini-test"},
    )
    assert __version__ == "16.4.0"
    identity = _runtime_identity()
    assert "Sophyane 16.4.0" in identity
    assert "provider: gemini" in identity
    assert "model: gemini-test" in identity


def test_common_gemini_action_and_check_forms_are_normalized() -> None:
    plan = parse_and_validate_plan(json.dumps({
        "objective": "Run self-test",
        "success_criteria": ["command exits zero", "SELF-TEST PASSED appears"],
        "deterministic_checks": [
            {"command": "grep -q 'SELF-TEST PASSED' stdout", "expected_exit_code": 0}
        ],
        "action": {
            "action": "run_command",
            "command": "python sophyane-9.0.7.py self-test",
        },
    }))
    assert plan["action"]["type"] == "run_command"
    assert plan["action"]["argv"] == ["python", "sophyane-9.0.7.py", "self-test"]
    assert plan["deterministic_checks"] == [
        {"type": "stdout_contains", "text": "SELF-TEST PASSED"}
    ]


def test_verified_self_test_finishes_after_one_step(tmp_path: Path) -> None:
    calls = {"planner": 0, "verifier": 0}

    def backend(prompt: str, system: str) -> str:
        if "SOPHYANE_ROLE=VERIFIER" in system:
            calls["verifier"] += 1
            # Reproduce a hesitant verifier: mechanical evidence must still win.
            return json.dumps({
                "goal_met": False,
                "confidence": 0.4,
                "missing_requirements": ["unsure"],
                "next_instruction": "rerun",
                "final_answer": "",
            })
        calls["planner"] += 1
        return json.dumps({
            "objective": "Run self-test",
            "success_criteria": ["exit zero", "SELF-TEST PASSED appears"],
            "deterministic_checks": [
                {"command": "grep -q 'SELF-TEST PASSED' stdout", "expected_exit_code": 0}
            ],
            "candidates": [{
                "label": "Run test",
                "reason": "direct evidence",
                "action": {
                    "action": "run_command",
                    "argv": [sys.executable, "-c", "print('SELF-TEST PASSED')"],
                },
            }],
            "selected_index": 0,
            "selection_reason": "direct",
            "action": {
                "action": "run_command",
                "argv": [sys.executable, "-c", "print('SELF-TEST PASSED')"],
            },
        })

    stream = io.StringIO()
    result = StrictInteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=6,
        progress=LiveProgressReporter(stream=stream, heartbeat_seconds=60),
    ).run("run and verify self-test")

    assert result.goal_met
    assert result.stopped_reason == "goal_verified"
    assert len(result.steps) == 1
    assert calls == {"planner": 1, "verifier": 1}
    assert result.execution["commands"][-1]["exit_code"] == 0
    assert "SELF-TEST PASSED" in result.execution["commands"][-1]["stdout"]
