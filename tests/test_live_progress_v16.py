from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from sophyane.live_coding_doer import (
    LiveGuardedCodingDoerRuntime,
    LiveProgressReporter,
)
from sophyane.memory import MemoryStore


def test_live_progress_reports_plan_actions_command_and_verification(
    tmp_path: Path,
) -> None:
    calls = {"planner": 0}

    def backend(prompt: str, system: str) -> str:
        if "SOPHYANE_ROLE=VERIFIER" in system:
            return json.dumps(
                {
                    "goal_met": True,
                    "confidence": 1,
                    "missing_requirements": [],
                    "next_instruction": "",
                    "final_answer": "Created and executed demo.py.",
                }
            )
        calls["planner"] += 1
        return json.dumps(
            {
                "objective": "Create and execute demo.py",
                "success_criteria": ["file exists", "command exits zero"],
                "action": {
                    "type": "batch",
                    "actions": [
                        {
                            "type": "write_file",
                            "path": "demo.py",
                            "content": "print('live-ok')\n",
                        },
                        {
                            "type": "run_command",
                            "argv": [sys.executable, "demo.py"],
                        },
                    ],
                },
                "rationale": "Execute safe steps directly.",
            }
        )

    stream = io.StringIO()
    reporter = LiveProgressReporter(
        stream=stream,
        heartbeat_seconds=60,
    )
    result = LiveGuardedCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=3,
        progress=reporter,
    ).run("Create demo.py and run it")

    assert result.goal_met
    output = stream.getvalue()
    assert "Starting autonomous run" in output
    assert "Indexing repository" in output
    assert "selecting the best next safe action" in output
    assert "Selected batch: 2 actions" in output
    assert "write_file: demo.py" in output
    assert "run_command:" in output
    assert "exit=0" in output
    assert "stdout: live-ok" in output
    assert "objective verified" in output
    assert "Run finished: goal_met=True" in output


def test_progress_can_be_disabled(tmp_path: Path) -> None:
    def backend(prompt: str, system: str) -> str:
        if "SOPHYANE_ROLE=VERIFIER" in system:
            return json.dumps(
                {
                    "goal_met": True,
                    "confidence": 1,
                    "missing_requirements": [],
                    "next_instruction": "",
                    "final_answer": "Done.",
                }
            )
        return json.dumps(
            {
                "objective": "Answer",
                "success_criteria": ["answer supplied"],
                "action": {"type": "answer", "text": "Done."},
                "rationale": "No execution requested.",
            }
        )

    stream = io.StringIO()
    result = LiveGuardedCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=1,
        progress=LiveProgressReporter(enabled=False, stream=stream),
    ).run("Explain hello")

    assert result.goal_met
    assert stream.getvalue() == ""
