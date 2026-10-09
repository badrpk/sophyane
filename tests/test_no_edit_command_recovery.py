
import json
import pytest
import sophyane.adaptive_execution as ae
from sophyane.rsi.authority import Operation


def action(kind, **fields):
    return json.dumps({"action": {"type": kind, **fields}})


def test_rejected_command_recovers_via_actual_file_read(monkeypatch, tmp_path):
    data = "7\n11\n13\n"
    target = tmp_path / "numbers.txt"
    target.write_text(data)
    calls = []
    executed = []
    real_execute = ae._execute

    def execute(runtime, item, workspace, progress):
        executed.append(item["type"])
        if item["type"] in {"run_command", "command", "shell"}:
            pytest.fail("Rejected command reached execution")
        return real_execute(runtime, item, workspace, progress)

    def ask(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            assert "actual rejection" in prompt.lower()
            assert "read_file" in prompt
            return action("read_file", path="numbers.txt")
        assert len(calls) == 2
        assert data.strip() in prompt
        return action("respond", text="TOTAL=31")

    monkeypatch.setattr(ae, "_execute", execute)
    result = ae.run_adaptive_loop(
        initial_text=action("run_command", command="awk '{s+=$1} END {print s}' numbers.txt"),
        original_request="Calculate the sum of numbers.txt. Do not modify any files.",
        ask=ask, workspace=tmp_path, max_steps=5,
        operation=Operation.READ_ONLY_OPERATION,
    )
    assert "TOTAL=31" in result
    assert not getattr(result, "execution_failed", False)
    assert "read_file" in executed
    assert len(calls) == 2
    assert target.read_text() == data


def test_rejected_command_retries_are_bounded(tmp_path):
    calls = []
    blocked = action("run_command", command="awk '{print $1}' numbers.txt")

    def ask(prompt):
        calls.append(prompt)
        return blocked

    result = ae.run_adaptive_loop(
        initial_text=blocked,
        original_request="Calculate a file total. Do not modify any files.",
        ask=ask, workspace=tmp_path, max_steps=8,
        operation=Operation.READ_ONLY_OPERATION,
    )
    assert len(calls) == 2
    assert getattr(result, "execution_failed", False) is True


def test_write_rejection_does_not_retry(tmp_path):
    def ask(prompt):
        pytest.fail("Rejected write entered command recovery")

    result = ae.run_adaptive_loop(
        initial_text=action("write_file", path="forbidden.txt", content="bad"),
        original_request="Inspect this workspace. Do not modify any files.",
        ask=ask, workspace=tmp_path, max_steps=5,
        operation=Operation.READ_ONLY_OPERATION,
    )
    assert getattr(result, "execution_failed", False) is True
    assert not (tmp_path / "forbidden.txt").exists()
