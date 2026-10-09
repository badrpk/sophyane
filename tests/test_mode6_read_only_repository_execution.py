import json
from pathlib import Path

import json
from pathlib import Path

from sophyane import adaptive_execution as adaptive
from sophyane import execution_runtime as runtime


def _progress(_message: str) -> None:
    pass


def test_inspect_alias_normalizes_to_native_read_file():
    assert adaptive._normalise_action({"action": "inspect", "file": "src/sophyane/mode6_session.py"}) == {"type": "read_file", "path": "src/sophyane/mode6_session.py"}


def test_read_file_alias_normalizes_to_native_read_file():
    assert adaptive._normalise_action({"action": "read_file", "file": "src/sophyane/mode6_session.py"}) == {"type": "read_file", "path": "src/sophyane/mode6_session.py"}


def test_runtime_read_is_grounded_and_non_mutating(tmp_path):
    target = tmp_path / "known.txt"
    target.write_text("grounded fixture\n", encoding="utf-8")
    before = target.read_bytes()
    before_entries = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    ok, result = runtime.execute_action({"type": "read_file", "path": "known.txt"}, tmp_path, _progress)
    assert ok is True
    assert "grounded fixture" in result
    assert target.read_bytes() == before
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before_entries


def test_runtime_read_rejects_traversal_absolute_missing_and_directory(tmp_path):
    outside = tmp_path.parent / "outside-mode6-read.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "directory").mkdir()
    try:
        for path in ("../outside-mode6-read.txt", str(outside)):
            ok, result = runtime.execute_action(
                {"type": "read_file", "path": path},
                tmp_path,
                _progress,
            )
            assert ok is False
            assert "outside workspace" in result.casefold()

        ok, result = runtime.execute_action(
            {"type": "read_file", "path": "missing.txt"},
            tmp_path,
            _progress,
        )
        assert ok is False
        assert "does not exist" in result

        ok, result = runtime.execute_action(
            {"type": "read_file", "path": "directory"},
            tmp_path,
            _progress,
        )
        assert ok is False
        assert "not a file" in result
    finally:
        outside.unlink()


def test_no_edit_accepts_reads_but_rejects_mutations():
    assert adaptive._no_edit_action_problem({"type": "read_file", "path": "known.txt"}) == ""
    for action in ({"type": "write_file", "path": "known.txt", "content": "x"}, {"type": "append_file", "path": "known.txt", "content": "x"}, {"type": "mkdir", "path": "new"}, {"type": "run_command", "command": "touch known.txt"}):
        assert adaptive._no_edit_action_problem(action)


def test_read_only_continuation_uses_observation_then_responds(tmp_path):
    (tmp_path / "known.txt").write_text("answer evidence\n", encoding="utf-8")
    prompts = []
    responses = iter(['{"action":"inspect","file":"known.txt"}', '{"action":{"type":"respond","message":"It contains answer evidence."}}'])
    def ask(prompt):
        prompts.append(prompt)
        return next(responses)
    result = adaptive.run_adaptive_loop(initial_text=next(responses), original_request="Inspect known.txt and briefly explain it. Do not modify any files.", ask=ask, workspace=tmp_path, max_steps=3)
    assert "It contains answer evidence." in result
    assert "Inspect known.txt and briefly explain it." in prompts[0]
    assert "answer evidence" in prompts[0]
    assert all(token not in prompts[0] for token in ("write_file", "append_file", "mkdir"))


def test_read_only_second_mutation_response_is_blocked(tmp_path):
    target = tmp_path / "known.txt"
    target.write_text("unchanged\n", encoding="utf-8")
    responses = iter(['{"action":"read_file","file":"known.txt"}', '{"action":{"type":"write_file","path":"known.txt","content":"tampered"}}'])
    before = target.read_bytes()
    result = adaptive.run_adaptive_loop(
        initial_text=next(responses),
        original_request="Inspect known.txt. Do not modify any files.",
        ask=lambda _prompt: next(responses),
        workspace=tmp_path,
        max_steps=3,
    )
    assert "rejected write_file" in result
    assert target.read_bytes() == before


# SOPHYANE_MODE6_CLASSIFIED_READ_ONLY_LIFECYCLE_V1
def test_classified_read_only_inspection_uses_observation_continuation(
    tmp_path,
):
    from sophyane.rsi.authority import Operation

    target = tmp_path / "known.txt"
    target.write_text(
        "classified read-only evidence\n",
        encoding="utf-8",
    )
    before = target.read_bytes()

    prompts = []
    responses = iter([
        '{"action":{"type":"respond","message":"It contains classified read-only evidence."}}',
    ])

    def ask(prompt):
        prompts.append(prompt)
        return next(responses)

    result = adaptive.run_adaptive_loop(
        initial_text='{"action":"inspect","file":"known.txt"}',
        original_request="Inspect known.txt and briefly explain it.",
        ask=ask,
        workspace=tmp_path,
        max_steps=3,
        operation=Operation.READ_ONLY_OPERATION,
    )

    assert "It contains classified read-only evidence." in result
    assert len(prompts) == 1
    assert "classified read-only evidence" in prompts[0]
    assert target.read_bytes() == before


# SOPHYANE_MODE6_READ_ONLY_CONTINUATION_PROVIDER_FAILURE_RED_V1
def test_read_only_continuation_provider_failure_returns_grounded_evidence(
    tmp_path,
):
    from sophyane.providers.base import ProviderError
    from sophyane.rsi.authority import Operation

    target = tmp_path / "known.txt"
    target.write_text(
        "grounded evidence survives provider outage\n",
        encoding="utf-8",
    )
    before = target.read_bytes()

    calls = []

    def unavailable_provider(prompt):
        calls.append(prompt)
        raise ProviderError("synthetic continuation outage")

    result = adaptive.run_adaptive_loop(
        initial_text='{"action":"read_file","path":"known.txt"}',
        original_request="Inspect known.txt.",
        ask=unavailable_provider,
        workspace=tmp_path,
        max_steps=3,
        operation=Operation.READ_ONLY_OPERATION,
    )

    assert len(calls) == 1
    assert "grounded evidence survives provider outage" in calls[0]

    # A provider outage after a successful grounded observation must not
    # erase that observation or escape as an uncaught exception.
    assert "grounded evidence survives provider outage" in result
    assert "provider" in result.casefold()
    assert "unavailable" in result.casefold()
    assert "read-only repository observation.\n\n" in result
    assert r"\n\n" not in result

    # Read-only failure recovery must remain byte-for-byte non-mutating.
    assert target.read_bytes() == before


# SOPHYANE_MODE6_READ_ONLY_CONTINUATION_FAILURE_SELECTIVITY_V1
def test_read_only_continuation_does_not_swallow_unexpected_runtime_error(
    tmp_path,
):
    import pytest

    from sophyane.rsi.authority import Operation

    target = tmp_path / "known.txt"
    target.write_text(
        "grounded before unexpected failure\n",
        encoding="utf-8",
    )
    before = target.read_bytes()

    def broken_continuation(_prompt):
        raise RuntimeError("synthetic programming failure")

    with pytest.raises(
        RuntimeError,
        match="synthetic programming failure",
    ):
        adaptive.run_adaptive_loop(
            initial_text='{"action":"read_file","path":"known.txt"}',
            original_request="Inspect known.txt.",
            ask=broken_continuation,
            workspace=tmp_path,
            max_steps=3,
            operation=Operation.READ_ONLY_OPERATION,
        )

    assert target.read_bytes() == before


def test_read_only_continuation_does_not_swallow_keyboard_interrupt(
    tmp_path,
):
    import pytest

    from sophyane.rsi.authority import Operation

    target = tmp_path / "known.txt"
    target.write_text(
        "grounded before cancellation\n",
        encoding="utf-8",
    )
    before = target.read_bytes()

    def cancelled_continuation(_prompt):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        adaptive.run_adaptive_loop(
            initial_text='{"action":"read_file","path":"known.txt"}',
            original_request="Inspect known.txt.",
            ask=cancelled_continuation,
            workspace=tmp_path,
            max_steps=3,
            operation=Operation.READ_ONLY_OPERATION,
        )

    assert target.read_bytes() == before


# SOPHYANE_MODE6_CLASSIFIED_READ_ONLY_FIRST_MUTATION_BOUNDARY_V1
def test_classified_read_only_operation_blocks_first_mutation(
    tmp_path,
):
    from sophyane.rsi.authority import Operation

    target = tmp_path / "known.txt"
    target.write_text(
        "must remain unchanged\n",
        encoding="utf-8",
    )
    before = target.read_bytes()

    result = adaptive.run_adaptive_loop(
        initial_text=(
            '{"action":{"type":"write_file",'
            '"path":"known.txt","content":"tampered\\n"}}'
        ),
        original_request="Inspect known.txt.",
        ask=lambda _prompt: (
            '{"action":{"type":"respond","message":"done"}}'
        ),
        workspace=tmp_path,
        max_steps=2,
        operation=Operation.READ_ONLY_OPERATION,
    )

    assert target.read_bytes() == before
    assert (
        "rejected" in result.casefold()
        or "read-only" in result.casefold()
        or "stopped safely" in result.casefold()
    )


def test_read_only_repository_duplicate_inspection_finishes_from_grounded_evidence(
    tmp_path,
    monkeypatch,
):
    """A repeated inspection must not turn sufficient evidence into repair."""
    requested_repository = tmp_path / "requested-repository"
    requested_repository.mkdir()
    unique_name = "grounded-evidence-unique.txt"
    (requested_repository / unique_name).write_text(
        "repository-only evidence\n", encoding="utf-8"
    )

    source_root = Path.cwd().resolve()
    source_before = sorted(
        path.relative_to(source_root)
        for path in source_root.rglob("*") if path.is_file()
    )
    requested_before = sorted(
        path.relative_to(requested_repository)
        for path in requested_repository.rglob("*") if path.is_file()
    )
    command = f"find {requested_repository} -type f -not -path '*/.git/*' -print"
    executed_workspaces = []
    original_execute_action = runtime.execute_action

    def tracked_execute_action(action, workspace, progress):
        executed_workspaces.append(Path(workspace).resolve())
        return original_execute_action(action, workspace, progress)

    monkeypatch.setattr(runtime, "execute_action", tracked_execute_action)

    def ask(_prompt):
        # Model the live defect: the provider repeats the successful inspection.
        return json.dumps({"action": {"type": "run_command", "command": command}})

    result = adaptive.run_adaptive_loop(
        initial_text=json.dumps({"action": {"type": "run_command", "command": command}}),
        original_request=(
            f"Inspect the explicitly supplied repository {requested_repository} "
            "read-only and report what files are present. Do not modify anything."
        ),
        ask=ask, workspace=requested_repository, max_steps=4,
    )

    assert unique_name in result
    assert "bounded repair attempts" not in result.casefold()
    assert "inspection/non-verifying" not in result.casefold()
    assert executed_workspaces == [requested_repository.resolve()]
    assert sorted(
        path.relative_to(requested_repository)
        for path in requested_repository.rglob("*") if path.is_file()
    ) == requested_before
    assert sorted(
        path.relative_to(source_root)
        for path in source_root.rglob("*") if path.is_file()
    ) == source_before
