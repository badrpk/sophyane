from pathlib import Path

from sophyane import adaptive_execution as adaptive
from sophyane.rsi.authority import Operation


def test_last_observation_final_response_is_delivered(tmp_path: Path):
    target = tmp_path / "guardrails.txt"
    target.write_text("SSRF protection: partial\n", encoding="utf-8")
    before = target.read_bytes()
    calls = []

    def ask(prompt):
        calls.append(prompt)
        assert "SSRF protection: partial" in prompt
        return (
            '{"action":{"type":"respond",'
            '"message":"Verified finding: SSRF protection is partial."}}'
        )

    result = adaptive.run_adaptive_loop(
        initial_text='{"action":{"type":"read_file","path":"guardrails.txt"}}',
        original_request="Audit whether Sophyane enforces SSRF protection.",
        ask=ask,
        workspace=tmp_path,
        max_steps=1,
        operation=Operation.READ_ONLY_OPERATION,
    )

    assert len(calls) == 1
    assert "Verified finding: SSRF protection is partial." in str(result)
    assert "\n\nExecution evidence:\n" in str(result)
    assert "Stopped after bounded execution loop" not in str(result)
    assert not isinstance(result, adaptive._UnresolvedExecutionResult)
    assert target.read_bytes() == before


def test_last_observation_rejects_another_inspection(tmp_path: Path):
    target = tmp_path / "guardrails.txt"
    target.write_text("SSRF protection: partial\n", encoding="utf-8")
    before = target.read_bytes()
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return '{"action":{"type":"read_file","path":"guardrails.txt"}}'

    result = adaptive.run_adaptive_loop(
        initial_text='{"action":{"type":"read_file","path":"guardrails.txt"}}',
        original_request="Audit whether Sophyane enforces SSRF protection.",
        ask=ask,
        workspace=tmp_path,
        max_steps=1,
        operation=Operation.READ_ONLY_OPERATION,
    )

    assert len(calls) == 1
    assert isinstance(result, adaptive._UnresolvedExecutionResult)
    assert "after the last read-only observation.\n\n" in str(result)
    assert "SSRF protection: partial" in str(result)
    assert target.read_bytes() == before
