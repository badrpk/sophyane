from pathlib import Path

from sophyane import adaptive_execution as adaptive
from sophyane.rsi.authority import Operation


def test_repeated_inspection_does_not_exhaust_budget(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / "guardrails.txt"
    target.write_text(
        "SSRF protection: partial\n",
        encoding="utf-8",
    )

    before = target.read_bytes()
    calls = []

    inspection = (
        '{"action":{"type":"run_command",'
        '"command":"find . -maxdepth 1 -type f -print"}}'
    )

    def ask(prompt):
        calls.append(prompt)
        return inspection

    result = adaptive.run_adaptive_loop(
        initial_text=inspection,
        original_request=(
            "Audit whether Sophyane enforces its execution "
            "guardrails deterministically."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=6,
        operation=Operation.READ_ONLY_OPERATION,
    )

    text = str(result).casefold()

    assert "stopped after bounded execution loop" not in text
    assert "guardrails.txt" in text
    assert target.read_bytes() == before
    assert len(calls) < 6
