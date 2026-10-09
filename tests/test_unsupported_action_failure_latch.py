import json

from pathlib import Path

from sophyane import adaptive_execution as adaptive
from sophyane.rsi.authority import Operation


INSPECT = {
    "action": {
        "type": "read_file",
        "path": "guardrails.txt",
    }
}

UNSUPPORTED = {
    "action": {
        "type": "synthesize_report",
    }
}

FINAL = {
    "action": {
        "type": "respond",
        "message": "Verified finding: SSRF protection is partial.",
    }
}


def encoded(value):
    return json.dumps(value)


def workspace_with_evidence(tmp_path: Path):
    target = tmp_path / "guardrails.txt"
    target.write_text(
        "SSRF protection: partial\n",
        encoding="utf-8",
    )
    return target, target.read_bytes()


def run_sequence(
    tmp_path,
    initial,
    responses,
    *,
    max_steps=5,
):
    prompts = []
    queue = iter(responses)

    def ask(prompt):
        prompts.append(prompt)
        try:
            return encoded(next(queue))
        except StopIteration:
            raise AssertionError(
                "Unexpected provider call "
                f"{len(prompts)}: {prompt[:350]!r}"
            ) from None

    result = adaptive.run_adaptive_loop(
        initial_text=encoded(initial),
        original_request=(
            "Audit whether Sophyane enforces SSRF "
            "protection. Read guardrails.txt and "
            "report the findings. Do not modify files."
        ),
        ask=ask,
        workspace=tmp_path,
        max_steps=max_steps,
        operation=Operation.READ_ONLY_OPERATION,
    )

    return result, prompts


def test_successful_inspection_then_unsupported_then_final(
    tmp_path,
):
    target, before = workspace_with_evidence(tmp_path)

    result, prompts = run_sequence(
        tmp_path,
        INSPECT,
        [UNSUPPORTED, FINAL],
    )

    assert len(prompts) == 2
    assert target.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "guardrails.txt"
    ]

    assert not isinstance(
        result,
        adaptive._UnresolvedExecutionResult,
    )

    output = str(result)
    assert "Verified finding: SSRF protection is partial." in output
    assert "Unsupported or missing action type: synthesize_report" in output
    assert "Execution evidence:" in output


def test_failed_inspection_cannot_be_cleared_by_final(
    tmp_path,
):
    # No target file exists. The required read_file must fail.
    result, prompts = run_sequence(
        tmp_path,
        INSPECT,
        [FINAL],
    )

    assert len(prompts) == 1
    assert isinstance(
        result,
        adaptive._UnresolvedExecutionResult,
    )

    assert (
        "Read-only execution remains incomplete"
        in str(result)
    )
    assert not (tmp_path / "guardrails.txt").exists()


def test_repeated_unsupported_actions_never_claim_success(
    tmp_path,
):
    target, before = workspace_with_evidence(tmp_path)

    result, prompts = run_sequence(
        tmp_path,
        INSPECT,
        [UNSUPPORTED, UNSUPPORTED, FINAL],
        max_steps=5,
    )

    assert target.read_bytes() == before

    # A provider that eventually supplies a valid final response
    # may recover from schema-only failures, but unsupported actions
    # themselves must never count as successful execution.
    output = str(result)

    assert len(prompts) == 3
    assert output.count(
        "Unsupported or missing action type: synthesize_report"
    ) >= 2
    assert (
        "Verified finding: SSRF protection is partial."
        in output
    )
    assert not isinstance(
        result,
        adaptive._UnresolvedExecutionResult,
    )


def test_unsupported_actions_without_final_never_claim_success(
    tmp_path,
):
    target, before = workspace_with_evidence(tmp_path)

    result, prompts = run_sequence(
        tmp_path,
        INSPECT,
        [UNSUPPORTED, UNSUPPORTED, UNSUPPORTED],
        max_steps=4,
    )

    assert target.read_bytes() == before
    assert len(prompts) == 3
    assert isinstance(
        result,
        adaptive._UnresolvedExecutionResult,
    )
    assert "Verified finding:" not in str(result)


def test_failed_inspection_then_unsupported_then_final_is_unresolved(
    tmp_path,
):
    result, prompts = run_sequence(
        tmp_path,
        INSPECT,
        [UNSUPPORTED, FINAL],
        max_steps=5,
    )

    assert len(prompts) == 2
    assert isinstance(
        result,
        adaptive._UnresolvedExecutionResult,
    )
    assert (
        "Read-only execution remains incomplete"
        in str(result)
    )


def test_unsupported_error_text_cannot_mask_supported_failure(
    tmp_path,
    monkeypatch,
):
    from sophyane import execution_runtime

    target, before = workspace_with_evidence(tmp_path)
    original = execution_runtime.execute_action

    def simulated_runtime(action, workspace, progress):
        if action.get("type") == "read_file":
            return (
                False,
                "Unsupported or missing action type: simulated failure",
            )
        return original(action, workspace, progress)

    monkeypatch.setattr(
        execution_runtime,
        "execute_action",
        simulated_runtime,
    )

    result, prompts = run_sequence(
        tmp_path,
        INSPECT,
        [FINAL],
    )

    assert len(prompts) == 1
    assert target.read_bytes() == before
    assert isinstance(
        result,
        adaptive._UnresolvedExecutionResult,
    )
