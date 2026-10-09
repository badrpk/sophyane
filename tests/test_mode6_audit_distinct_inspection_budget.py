from pathlib import Path

from sophyane import adaptive_execution as adaptive
from sophyane.rsi.authority import Operation


def test_distinct_read_only_inspections_preserve_truthful_budget(
    tmp_path: Path,
):
    # Distinct real files ensure this is not merely a
    # duplicate-inspection regression.
    for index in range(20):
        (tmp_path / f"guardrail_{index:02d}.txt").write_text(
            f"guardrail evidence {index:02d}\n",
            encoding="utf-8",
        )

    before = {
        p.name: p.read_bytes()
        for p in tmp_path.iterdir()
        if p.is_file()
    }

    calls = []

    def inspection(index):
        return (
            '{"action":{"type":"read_file",'
            f'"path":"guardrail_{index:02d}.txt"'
            '}}'
        )

    def ask(prompt):
        calls.append(prompt)
        return inspection(len(calls))

    result = adaptive.run_adaptive_loop(
        initial_text=inspection(0),
        original_request=(
            "Audit whether Sophyane enforces its agent "
            "execution guardrails deterministically. "
            "Report only verified findings."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=16,
        operation=Operation.READ_ONLY_OPERATION,
    )

    output = str(result).casefold()

    after = {
        p.name: p.read_bytes()
        for p in tmp_path.iterdir()
        if p.is_file()
    }

    assert after == before, "Read-only execution mutated workspace"

    # Never fabricate a compliance conclusion.
    assert "all guardrails pass" not in output
    assert "fully compliant" not in output

    # The execution must return without unbounded provider calls.
    assert len(calls) <= 16

    # Successful observations must not be silently discarded.
    assert (
        "guardrail evidence" in output
        or "guardrail_00.txt" in output
        or "bounded execution" in output
    )

    print(f"PROVIDER_CONTINUATIONS={len(calls)}")
    print(f"RESULT_TYPE={type(result).__name__}")
    print(f"BOUNDED_STOP={'stopped after bounded execution loop' in output}")
    print(f"WORKSPACE_UNCHANGED={after == before}")
    print(f"RESULT_PREVIEW={str(result)[:700]!r}")
