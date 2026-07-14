from __future__ import annotations

import json
import sys
from pathlib import Path

from sophyane.doer import DoerRuntime
from sophyane.memory import MemoryStore


def test_doer_writes_executes_verifies_and_loops(tmp_path: Path) -> None:
    calls = {"planner": 0, "verifier": 0}

    def backend(prompt: str, system: str) -> str:
        payload = json.loads(prompt)
        if "Independently compare" in system:
            calls["verifier"] += 1
            if calls["verifier"] == 1:
                return json.dumps({
                    "goal_met": False,
                    "confidence": 0.8,
                    "missing_requirements": ["script has not been executed"],
                    "next_instruction": "Run the generated script and verify output.",
                    "final_answer": "",
                })
            command = payload["latest_observation"]["command"]
            assert command["exit_code"] == 0
            assert "18.0 MWh/day" in command["stdout"]
            return json.dumps({
                "goal_met": True,
                "confidence": 1.0,
                "missing_requirements": [],
                "next_instruction": "",
                "final_answer": "Created and verified solar_daily.py; output is 18.0 MWh/day.",
            })

        calls["planner"] += 1
        if calls["planner"] == 1:
            return json.dumps({
                "objective": "Create and run a 3 MW, 6-hour solar calculator",
                "success_criteria": [
                    "solar_daily.py exists",
                    "the script executes successfully",
                    "the output is 18.0 MWh/day",
                ],
                "action": {
                    "type": "write_file",
                    "path": "solar_daily.py",
                    "content": "print('18.0 MWh/day')\n",
                },
                "rationale": "Create the requested artifact first.",
            })
        assert "Run the generated script" in payload["verifier_instruction"]
        return json.dumps({
            "objective": payload["current_objective"],
            "success_criteria": payload["current_success_criteria"],
            "action": {"type": "run_command", "argv": [sys.executable, "solar_daily.py"]},
            "rationale": "Execute and verify the file.",
        })

    result = DoerRuntime(
        backend, MemoryStore(tmp_path / "memory.db"), tmp_path, max_steps=4
    ).run("Create a solar script and verify it")
    assert result.goal_met
    assert result.stopped_reason == "goal_verified"
    assert len(result.steps) == 2
    assert (tmp_path / "solar_daily.py").is_file()
    assert result.execution["verified"]
    assert calls == {"planner": 2, "verifier": 2}


def test_false_permission_request_is_rejected_then_work_continues(tmp_path: Path) -> None:
    planner_calls = 0
    verifier_calls = 0

    def backend(prompt: str, system: str) -> str:
        nonlocal planner_calls, verifier_calls
        payload = json.loads(prompt)
        if "Independently compare" in system:
            verifier_calls += 1
            if verifier_calls < 3:
                return json.dumps({
                    "goal_met": False,
                    "confidence": 1.0,
                    "missing_requirements": ["calculator not yet created and executed"],
                    "next_instruction": "Proceed without permission: create or execute the calculator.",
                    "final_answer": "",
                })
            command = payload["latest_observation"]["command"]
            return json.dumps({
                "goal_met": command["exit_code"] == 0,
                "confidence": 1.0,
                "missing_requirements": [],
                "next_instruction": "",
                "final_answer": "Calculator created, executed and verified.",
            })

        planner_calls += 1
        common = {
            "objective": "Create and execute calculator.py",
            "success_criteria": ["calculator.py exists", "calculator.py exits 0"],
        }
        if planner_calls == 1:
            return json.dumps({
                **common,
                "action": {
                    "type": "ask_user",
                    "prompt": "Paste the exact five-line authorization and approve file creation.",
                },
                "rationale": "invented permission",
            })
        if planner_calls == 2:
            return json.dumps({
                **common,
                "action": {
                    "type": "write_file",
                    "path": "calculator.py",
                    "content": "assert 2 + 2 == 4\nprint('calculator-ok')\n",
                },
                "rationale": "Workspace writes are already authorized.",
            })
        return json.dumps({
            **common,
            "action": {"type": "run_command", "argv": [sys.executable, "calculator.py"]},
            "rationale": "Run the created calculator.",
        })

    result = DoerRuntime(
        backend, MemoryStore(tmp_path / "memory.db"), tmp_path, max_steps=5
    ).run("Create, run, test and verify a Python calculator")
    assert result.goal_met
    assert len(result.steps) == 3
    assert result.steps[0].observation["status"] == "error"
    assert "unnecessary permission request rejected" in result.steps[0].observation["error"]
    assert (tmp_path / "calculator.py").is_file()
    assert result.execution["commands"][-1]["exit_code"] == 0


def test_failed_code_is_rewritten_and_rerun_until_pass(tmp_path: Path) -> None:
    planner_calls = 0
    verifier_calls = 0

    def backend(prompt: str, system: str) -> str:
        nonlocal planner_calls, verifier_calls
        payload = json.loads(prompt)
        if "Independently compare" in system:
            verifier_calls += 1
            observation = payload["latest_observation"]
            if verifier_calls < 4:
                return json.dumps({
                    "goal_met": False,
                    "confidence": 1.0,
                    "missing_requirements": ["program has not passed execution"],
                    "next_instruction": "Use stderr to repair the complete file, then rerun it.",
                    "final_answer": "",
                })
            assert observation["command"]["exit_code"] == 0
            assert "repaired-ok" in observation["command"]["stdout"]
            return json.dumps({
                "goal_met": True,
                "confidence": 1.0,
                "missing_requirements": [],
                "next_instruction": "",
                "final_answer": "Faulty code was automatically repaired and verified.",
            })

        planner_calls += 1
        common = {
            "objective": "Create a working program and repair failures",
            "success_criteria": ["app.py exists", "app.py exits 0", "stdout contains repaired-ok"],
        }
        if planner_calls == 1:
            return json.dumps({
                **common,
                "action": {"type": "write_file", "path": "app.py", "content": "print('broken'\n"},
                "rationale": "Initial generated file.",
            })
        if planner_calls == 2:
            return json.dumps({
                **common,
                "action": {"type": "run_command", "argv": [sys.executable, "app.py"]},
                "rationale": "Run and inspect failure.",
            })
        if planner_calls == 3:
            assert "AUTOMATIC REPAIR REQUIRED" in payload["verifier_instruction"]
            assert "SyntaxError" in payload["verifier_instruction"]
            return json.dumps({
                **common,
                "action": {"type": "write_file", "path": "app.py", "content": "print('repaired-ok')\n"},
                "rationale": "Rewrite complete file using stderr diagnosis.",
            })
        return json.dumps({
            **common,
            "action": {"type": "run_command", "argv": [sys.executable, "app.py"]},
            "rationale": "Verify repaired code.",
        })

    result = DoerRuntime(
        backend, MemoryStore(tmp_path / "memory.db"), tmp_path, max_steps=6
    ).run("Create app.py, run it and automatically fix errors until it works")
    assert result.goal_met
    assert len(result.steps) == 4
    assert result.execution["commands"][0]["exit_code"] != 0
    assert result.execution["commands"][1]["exit_code"] == 0
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('repaired-ok')\n"


def test_doer_retrieves_persistent_memory_for_new_process_style_call(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.db")
    memory.remember("My solar farm target is 3MW at Chakwal with S21 miners.", importance=10)
    observed_context = ""

    def backend(prompt: str, system: str) -> str:
        nonlocal observed_context
        payload = json.loads(prompt)
        if "Independently compare" in system:
            return json.dumps({
                "goal_met": True,
                "confidence": 1.0,
                "missing_requirements": [],
                "next_instruction": "",
                "final_answer": "Your target is 3MW at Chakwal with S21 miners.",
            })
        observed_context = payload["persistent_context"]
        return json.dumps({
            "objective": "Recall the stored solar target",
            "success_criteria": ["Answer matches persistent memory"],
            "action": {"type": "answer", "text": "Your target is 3MW at Chakwal with S21 miners."},
            "rationale": "Persistent memory directly answers the question.",
        })

    result = DoerRuntime(backend, memory, tmp_path).run("What is my solar farm target?")
    assert result.goal_met
    assert "3MW" in result.final_output
    assert "3MW at Chakwal" in observed_context


def test_destructive_command_is_blocked(tmp_path: Path) -> None:
    def backend(prompt: str, system: str) -> str:
        payload = json.loads(prompt)
        if "Independently compare" in system:
            assert payload["latest_observation"]["status"] == "error"
            return json.dumps({
                "goal_met": False,
                "confidence": 1.0,
                "missing_requirements": ["destructive command was blocked"],
                "next_instruction": "Use a safe action instead.",
                "final_answer": "",
            })
        return json.dumps({
            "objective": "Unsafe test",
            "success_criteria": ["Never run destructive commands"],
            "action": {"type": "run_command", "argv": ["rm", "-rf", "."]},
            "rationale": "test",
        })

    result = DoerRuntime(
        backend, MemoryStore(tmp_path / "memory.db"), tmp_path, max_steps=1
    ).run("delete everything")
    assert not result.goal_met
    assert result.steps[0].observation["status"] == "error"
    assert "PermissionError" in result.steps[0].observation["error"]
