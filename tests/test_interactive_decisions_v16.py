from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from sophyane.interactive_coding_doer import InteractiveCodingDoerRuntime
from sophyane.live_coding_doer import LiveProgressReporter
from sophyane.memory import MemoryStore


def test_shows_candidates_selection_and_code_before_execution(tmp_path: Path) -> None:
    def backend(prompt: str, system: str) -> str:
        if "SOPHYANE_ROLE=VERIFIER" in system:
            return json.dumps(
                {
                    "goal_met": True,
                    "confidence": 1,
                    "missing_requirements": [],
                    "next_instruction": "",
                    "final_answer": "Created and ran selected.py.",
                }
            )
        candidates = [
            {
                "label": "Write documentation only",
                "reason": "Low risk but does not execute code",
                "action": {"type": "write_file", "path": "notes.md", "content": "notes\n"},
            },
            {
                "label": "Create and execute a focused script",
                "reason": "Highest requirement coverage and direct evidence",
                "action": {
                    "type": "batch",
                    "actions": [
                        {"type": "write_file", "path": "selected.py", "content": "print('selected-ok')\n"},
                        {"type": "run_command", "argv": [sys.executable, "selected.py"]},
                    ],
                },
            },
        ]
        return json.dumps(
            {
                "objective": "Create and run selected.py",
                "success_criteria": ["file exists", "command exits zero"],
                "candidates": candidates,
                "selected_index": 1,
                "selection_reason": "It is the only candidate that satisfies creation and execution.",
                "action": candidates[1]["action"],
                "rationale": "Select the best candidate automatically.",
            }
        )

    stream = io.StringIO()
    result = InteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=3,
        progress=LiveProgressReporter(stream=stream, heartbeat_seconds=60),
    ).run("Create selected.py and run it")

    assert result.goal_met
    output = stream.getvalue()
    assert "Choices considered: 2" in output
    assert "Write documentation only" in output
    assert "Create and execute a focused script" in output
    assert "Selected choice 2" in output
    assert "Code to write: selected.py" in output
    assert "print('selected-ok')" in output
    assert result.execution["commands"][-1]["exit_code"] == 0


def test_quota_error_stops_after_one_step_without_verifier_retry(tmp_path: Path) -> None:
    calls = {"count": 0}

    def backend(prompt: str, system: str) -> str:
        calls["count"] += 1
        raise RuntimeError("HTTP 429: insufficient_quota: exceeded your current quota")

    stream = io.StringIO()
    result = InteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=16,
        progress=LiveProgressReporter(stream=stream, heartbeat_seconds=60),
    ).run("Inspect, patch, and run tests")

    assert not result.goal_met
    assert result.stopped_reason == "provider_unavailable"
    assert len(result.steps) == 1
    assert calls["count"] == 1
    output = stream.getvalue()
    assert "Provider unavailable" in output
    assert "steps=1" in output


def test_provider_failure_after_successful_tests_preserves_verified_success(
    tmp_path: Path,
) -> None:
    """A later quota failure cannot erase already-successful test evidence."""

    (tmp_path / "test_calculator.py").write_text(
        "import unittest\n"
        "from calculator import add\n\n"
        "class Tests(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )

    calls = {"planner": 0, "verifier": 0}

    def backend(prompt: str, system: str) -> str:
        if "SOPHYANE_ROLE=VERIFIER" in system:
            calls["verifier"] += 1
            # Deliberately demand another iteration despite mechanically
            # successful tests. The next planner call will lose quota.
            return json.dumps(
                {
                    "goal_met": False,
                    "confidence": 0.5,
                    "missing_requirements": [
                        "Additional confirmation requested"
                    ],
                    "next_instruction": "Continue toward unmet requirements",
                    "final_answer": "",
                }
            )

        calls["planner"] += 1

        if calls["planner"] == 1:
            action = {
                "type": "batch",
                "actions": [
                    {
                        "type": "write_file",
                        "path": "calculator.py",
                        "content": (
                            "def add(a, b):\n"
                            "    return a + b\n"
                        ),
                    },
                    {
                        "type": "run_command",
                        "argv": [
                            sys.executable,
                            "-m",
                            "unittest",
                            "test_calculator.py",
                        ],
                    },
                ],
            }
            return json.dumps(
                {
                    "objective": "Repair calculator.py and run tests",
                    "success_criteria": [
                        "calculator.py is repaired",
                        "tests exit zero",
                    ],
                    "candidates": [
                        {
                            "label": "repair and test",
                            "reason": "Direct verified repair",
                            "action": action,
                        }
                    ],
                    "selected_index": 0,
                    "selection_reason": "Repair and test directly",
                    "action": action,
                    "rationale": "Minimum verified repair",
                }
            )

        raise RuntimeError(
            "HTTP 429: insufficient_quota: exceeded your current quota"
        )

    stream = io.StringIO()

    result = InteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=4,
        progress=LiveProgressReporter(
            stream=stream,
            heartbeat_seconds=60,
        ),
    ).run("Repair calculator.py and run tests")

    assert result.goal_met
    assert result.stopped_reason == (
        "goal_verified_after_provider_failure"
    )
    assert calls["planner"] == 2
    assert calls["verifier"] == 1

    assert result.execution["commands"][-1]["exit_code"] == 0
    assert (
        result.steps[-1].verification["verification_mode"]
        == "provider_failure_test_evidence_recovery"
    )

    assert "provider became unavailable" in result.final_output.lower()
