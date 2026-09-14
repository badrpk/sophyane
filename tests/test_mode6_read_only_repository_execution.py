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
