import json
from pathlib import Path

import pytest

from sophyane import adaptive_execution as adaptive
from sophyane.rsi.authority import Operation


@pytest.mark.parametrize(
    "provider_reply",
    [
        '{"action":{"type":"write_file","path":"guardrails.txt","content":"COMPROMISED"}}',
        '{"action":{"type":"read_file","path":"guardrails.txt"}}',
        '{"action":{"type":"respond","message":',
    ],
    ids=["mutation", "additional-read", "malformed-json"],
)
def test_final_boundary_rejects_noncompletion(
    tmp_path: Path, provider_reply: str
):
    target = tmp_path / "guardrails.txt"
    target.write_text("SSRF protection: partial\n", encoding="utf-8")
    before = target.read_bytes()
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return provider_reply

    result = adaptive.run_adaptive_loop(
        initial_text=json.dumps({
            "action": {
                "type": "read_file",
                "path": "guardrails.txt",
            }
        }),
        original_request="Audit whether Sophyane enforces SSRF protection.",
        ask=ask,
        workspace=tmp_path,
        max_steps=1,
        operation=Operation.READ_ONLY_OPERATION,
    )

    assert len(calls) == 1
    assert isinstance(result, adaptive._UnresolvedExecutionResult)
    assert "SSRF protection: partial" in str(result)
    assert target.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["guardrails.txt"]


def test_final_boundary_cannot_bypass_outstanding_obligations(
    tmp_path: Path, monkeypatch
):
    target = tmp_path / "guardrails.txt"
    target.write_text("SSRF protection: partial\n", encoding="utf-8")
    before = target.read_bytes()
    calls = []

    # Force an outstanding obligation to test the boundary gate,
    # independently of request-language obligation classification.
    monkeypatch.setattr(
        adaptive,
        "_read_only_unsatisfied_obligations",
        lambda required, satisfied: ("unverified requirement",),
    )

    def ask(prompt):
        calls.append(prompt)
        return json.dumps({
            "action": {
                "type": "respond",
                "message": "All requirements verified.",
            }
        })

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
    assert "All requirements verified." not in str(result)
    assert "SSRF protection: partial" in str(result)
    assert target.read_bytes() == before
