from __future__ import annotations

import json
import sys
from pathlib import Path

from sophyane.guarded_coding_doer import GuardedCodingDoerRuntime
from sophyane.memory import MemoryStore


def test_execution_goal_rejects_menu_and_continues(tmp_path: Path) -> None:
    calls = {"planner": 0, "verifier": 0}

    def backend(prompt: str, system: str) -> str:
        payload = json.loads(prompt)
        if "SOPHYANE_ROLE=VERIFIER" in system:
            calls["verifier"] += 1
            latest = payload["latest_observation"]
            if latest.get("status") == "error":
                return json.dumps({
                    "goal_met": False,
                    "confidence": 1,
                    "missing_requirements": ["Concrete execution evidence is still missing"],
                    "next_instruction": "Apply the safe patch and run tests without asking permission.",
                    "final_answer": "",
                })
            return json.dumps({
                "goal_met": True,
                "confidence": 1,
                "missing_requirements": [],
                "next_instruction": "",
                "final_answer": "Patch applied and tests passed.",
            })

        calls["planner"] += 1
        if calls["planner"] == 1:
            return json.dumps({
                "objective": "Apply a maintainability patch and verify it",
                "success_criteria": ["file changed", "tests pass"],
                "action": {
                    "type": "answer",
                    "text": "Choose A/B/C. A apply patch, B run tests, C archive files. Which should I do?",
                },
                "rationale": "Ask the user to choose.",
            })
        return json.dumps({
            "objective": "Apply a maintainability patch and verify it",
            "success_criteria": ["file changed", "tests pass"],
            "action": {
                "type": "batch",
                "actions": [
                    {"type": "write_file", "path": "maintainability.txt", "content": "fixed\n"},
                    {
                        "type": "run_command",
                        "argv": [sys.executable, "-c", "assert open('maintainability.txt').read() == 'fixed\\n'"],
                    },
                ],
            },
            "rationale": "Execute the best safe option directly.",
        })

    result = GuardedCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=4,
    ).run(
        "Inspect this repository, apply the smallest precise patch, run tests, repair failures automatically, and report evidence."
    )

    assert result.goal_met
    assert calls["planner"] == 2
    assert (tmp_path / "maintainability.txt").read_text(encoding="utf-8") == "fixed\n"
    assert result.execution["commands"][-1]["exit_code"] == 0
    assert result.steps[0].observation["status"] == "error"
    assert "prose-only" in result.steps[0].observation["error"]


def test_verifier_cannot_complete_execution_goal_without_execution(tmp_path: Path) -> None:
    def backend(prompt: str, system: str) -> str:
        if "SOPHYANE_ROLE=VERIFIER" in system:
            return json.dumps({
                "goal_met": True,
                "confidence": 1,
                "missing_requirements": [],
                "next_instruction": "",
                "final_answer": "Done without execution.",
            })
        return json.dumps({
            "objective": "Modify and test repository",
            "success_criteria": ["patch applied", "tests pass"],
            "action": {"type": "answer", "text": "I recommend a patch."},
            "rationale": "prose",
        })

    result = GuardedCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=1,
    ).run("Apply a patch and run tests")

    assert not result.goal_met
    assert result.steps[0].verification["goal_met"] is False
