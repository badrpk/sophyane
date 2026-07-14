from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from sophyane.live_coding_doer import LiveProgressReporter
from sophyane.memory import MemoryStore
from sophyane.strict_interactive_doer import StrictInteractiveCodingDoerRuntime
from sophyane.strict_protocol import parse_and_validate_plan


def test_gemini_style_prose_is_rejected_then_regenerated(tmp_path: Path) -> None:
    calls = {"planner": 0, "verifier": 0}

    def backend(prompt: str, system: str) -> str:
        if "SOPHYANE_ROLE=VERIFIER" in system:
            calls["verifier"] += 1
            return json.dumps({
                "goal_met": True,
                "confidence": 1,
                "missing_requirements": [],
                "next_instruction": "",
                "final_answer": "Created and ran demo.py.",
            })
        calls["planner"] += 1
        if calls["planner"] == 1:
            return """The repository inspection is complete.\n\nNext Steps:\n```bash\necho hello\n```\n<execute_bash>echo hello</execute_bash>"""
        return json.dumps({
            "objective": "Create and run demo.py",
            "success_criteria": ["demo.py exists", "command exits zero"],
            "candidates": [
                {
                    "label": "Write and execute",
                    "action": {
                        "type": "batch",
                        "actions": [
                            {"type": "write_file", "path": "demo.py", "content": "print('ok')\n"},
                            {"type": "run_command", "argv": [sys.executable, "demo.py"]},
                        ],
                    },
                    "reason": "Directly produces execution evidence",
                },
                {
                    "label": "Inspect only",
                    "action": {"type": "search_repository", "query": "demo"},
                    "reason": "Lower evidence value",
                },
            ],
            "selected_index": 0,
            "selection_reason": "The first candidate fully satisfies the request.",
            "action": {
                "type": "batch",
                "actions": [
                    {"type": "write_file", "path": "demo.py", "content": "print('ok')\n"},
                    {"type": "run_command", "argv": [sys.executable, "demo.py"]},
                ],
            },
            "rationale": "Execute the selected safe candidate.",
        })

    stream = io.StringIO()
    runtime = StrictInteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=2,
        protocol_attempts=3,
        progress=LiveProgressReporter(stream=stream, heartbeat_seconds=60),
    )
    result = runtime.run("Create demo.py and run it")

    assert result.goal_met
    assert calls == {"planner": 2, "verifier": 1}
    assert (tmp_path / "demo.py").read_text(encoding="utf-8") == "print('ok')\n"
    output = stream.getvalue()
    assert "Planner protocol rejected" in output
    assert "Requesting strict JSON regeneration automatically" in output
    assert "Choices considered: 2" in output
    assert "Selected choice 1" in output
    assert "Code to write: demo.py" in output


def test_schema_validation_rejects_json_without_action() -> None:
    invalid = json.dumps({
        "objective": "Inspect repository",
        "success_criteria": ["inspection complete"],
    })
    try:
        parse_and_validate_plan(invalid)
    except Exception as error:
        assert "action" in str(error)
    else:
        raise AssertionError("invalid planner JSON was accepted")
