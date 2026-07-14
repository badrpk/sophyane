from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from sophyane.coding_runtime import (
    DependencyAdvisor,
    MechanicalVerifier,
    PatchEngine,
    RepositoryIndex,
    TaskQueue,
)
from sophyane.memory import MemoryStore
from sophyane.v16_doer import CodingDoerRuntime


def test_repository_index_symbols_search_and_context(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "import json\n\nclass Inventory:\n    def total(self):\n        return 42\n",
        encoding="utf-8",
    )
    (tmp_path / "test_app.py").write_text(
        "def test_total():\n    assert True\n",
        encoding="utf-8",
    )
    snapshot = RepositoryIndex(tmp_path).build()
    assert "app.py" in snapshot.files
    assert "test_app.py" in snapshot.tests
    assert any(
        item.name == "Inventory" and item.kind == "class"
        for item in snapshot.symbols
    )
    index = RepositoryIndex(tmp_path)
    index.build()
    assert index.search("Inventory total")
    assert "class Inventory" in index.context("Inventory")


def test_precise_patch_preserves_unrelated_content(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text(
        "HEADER = 1\n\ndef value():\n    return 1\n\nFOOTER = 2\n",
        encoding="utf-8",
    )
    evidence = PatchEngine(tmp_path).replace_exact(
        "module.py",
        "return 1",
        "return 42",
    )
    text = path.read_text(encoding="utf-8")
    assert "HEADER = 1" in text and "FOOTER = 2" in text
    assert "return 42" in text
    assert len(evidence["sha256"]) == 64


def test_task_queue_respects_dependencies() -> None:
    queue = TaskQueue(
        [
            {"id": "schema", "objective": "Create schema"},
            {
                "id": "api",
                "objective": "Create API",
                "depends_on": ["schema"],
            },
        ]
    )
    assert [task.id for task in queue.ready()] == ["schema"]
    queue.complete("schema", {"ok": True})
    assert [task.id for task in queue.ready()] == ["api"]


def test_mechanical_verifier_is_authoritative(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("verified", encoding="utf-8")
    verifier = MechanicalVerifier(tmp_path)
    result = verifier.verify(
        [
            {"type": "file_exists", "path": "result.txt"},
            {"type": "contains", "path": "result.txt", "text": "verified"},
        ]
    )
    assert result["passed"]
    failed = verifier.verify(
        [{"type": "file_exists", "path": "missing.txt"}]
    )
    assert not failed["passed"]


def test_dependency_advisor_extracts_missing_module() -> None:
    result = DependencyAdvisor.diagnose(
        "ModuleNotFoundError: No module named 'requests'"
    )
    assert result is not None
    assert result["module"] == "requests"
    assert result["suggested_argv"][-1] == "requests"


def test_role_markers_are_unambiguous() -> None:
    planner = CodingDoerRuntime._system("planner")
    verifier = CodingDoerRuntime._system("verifier")
    assert "SOPHYANE_ROLE=PLANNER" in planner
    assert "SOPHYANE_ROLE=VERIFIER" in verifier
    assert "SOPHYANE_ROLE=VERIFIER" not in planner


def test_batched_write_run_and_verify(tmp_path: Path) -> None:
    calls = {"planner": 0, "verifier": 0}

    def backend(prompt: str, system: str) -> str:
        payload = json.loads(prompt)
        if "SOPHYANE_ROLE=VERIFIER" in system:
            calls["verifier"] += 1
            observations = payload["latest_observation"].get(
                "observations",
                [],
            )
            command = observations[-1]["observation"]["command"]
            assert command["exit_code"] == 0
            return json.dumps(
                {
                    "goal_met": True,
                    "confidence": 1,
                    "missing_requirements": [],
                    "next_instruction": "",
                    "final_answer": (
                        "Created and tested calculator.py in one batch."
                    ),
                }
            )
        assert "SOPHYANE_ROLE=PLANNER" in system
        calls["planner"] += 1
        return json.dumps(
            {
                "objective": "Create and test calculator",
                "success_criteria": [
                    "calculator.py exists",
                    "script exits zero",
                ],
                "action": {
                    "type": "batch",
                    "actions": [
                        {
                            "type": "write_file",
                            "path": "calculator.py",
                            "content": "assert 2 + 2 == 4\nprint('ok')\n",
                        },
                        {
                            "type": "run_command",
                            "argv": [sys.executable, "calculator.py"],
                        },
                    ],
                },
                "rationale": (
                    "Independent safe steps can execute together."
                ),
            }
        )

    runtime = CodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=3,
    )
    result = runtime.run("Create and test a calculator")
    assert result.goal_met
    assert len(result.steps) == 1
    assert (tmp_path / "calculator.py").is_file()
    assert result.execution["commands"][0]["exit_code"] == 0
    assert calls == {"planner": 1, "verifier": 1}
    repository = result.execution["repository"]
    assert repository["files"]


def test_batch_stops_on_failure_and_reports_dependency(tmp_path: Path) -> None:
    def backend(prompt: str, system: str) -> str:
        if "SOPHYANE_ROLE=VERIFIER" in system:
            return json.dumps(
                {
                    "goal_met": False,
                    "confidence": 1,
                    "missing_requirements": ["dependency missing"],
                    "next_instruction": (
                        "Install or replace dependency safely"
                    ),
                    "final_answer": "",
                }
            )
        assert "SOPHYANE_ROLE=PLANNER" in system
        return json.dumps(
            {
                "objective": "diagnose",
                "success_criteria": ["command succeeds"],
                "action": {
                    "type": "run_command",
                    "argv": [
                        sys.executable,
                        "-c",
                        "import package_that_does_not_exist_123",
                    ],
                },
                "rationale": "exercise diagnostics",
            }
        )

    result = CodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        max_steps=1,
    ).run("diagnose missing dependency")
    observation = result.steps[0].observation
    assert observation["status"] == "command_failed"
    assert (
        observation["dependency_diagnosis"]["kind"]
        == "missing_python_dependency"
    )


def test_patch_engine_rejects_ambiguous_match(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text(
        "x = 1\nx = 1\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        PatchEngine(tmp_path).replace_exact(
            "x.py",
            "x = 1",
            "x = 2",
        )
