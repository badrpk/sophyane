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
