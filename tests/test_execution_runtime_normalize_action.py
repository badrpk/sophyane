from sophyane.execution_runtime import (
    _normalize_action,
    execute_action,
)


def test_invalid_string_action_does_not_raise_unbound_local() -> None:
    result = _normalize_action(
        {
            "action": "not_a_real_action",
        }
    )

    assert result is None


def test_valid_string_action_is_normalized() -> None:
    result = _normalize_action(
        {
            "action": "write_file",
            "path": "README.md",
            "content": "hello",
        }
    )

    assert result == {
        "type": "write_file",
        "path": "README.md",
        "content": "hello",
    }


def test_string_answer_alias_becomes_respond() -> None:
    result = _normalize_action(
        {
            "action": "answer",
            "message": "done",
        }
    )

    assert result == {
        "type": "respond",
        "message": "done",
    }


def test_nested_action_still_normalizes() -> None:
    result = _normalize_action(
        {
            "action": {
                "type": "run_command",
                "command": "python3 -V",
            }
        }
    )

    assert result is not None
    assert result["type"] == "run_command"
    assert result["command"] == "python3 -V"


def test_invalid_string_action_can_fall_through_to_nested_action() -> None:
    result = _normalize_action(
        {
            "action": "invalid",
            "next_action": {
                "type": "respond",
                "message": "fallback",
            },
        }
    )

    assert result == {
        "type": "respond",
        "message": "fallback",
    }



# SOPHYANE_NIFDU_STRING_ACTION_NORMALIZATION_V1

def test_normalize_action_accepts_raw_json_run_command_string():
    result = _normalize_action(
        '{"type":"run_command","command":"printf hello"}'
    )

    assert result == {
        "type": "run_command",
        "command": "printf hello",
    }


def test_normalize_action_accepts_raw_json_nested_action_string():
    result = _normalize_action(
        '{"action":{"type":"run_command","command":"printf hello"}}'
    )

    assert result == {
        "type": "run_command",
        "command": "printf hello",
    }


def test_normalize_action_accepts_raw_json_nested_write_file_string():
    result = _normalize_action(
        '{"action":{"type":"write_file","path":"probe.txt","content":"hello"}}'
    )

    assert result == {
        "type": "write_file",
        "path": "probe.txt",
        "content": "hello",
    }


def test_normalize_action_canonicalizes_run_alias():
    result = _normalize_action(
        {
            "type": "run",
            "command": "printf hello",
        }
    )

    assert result == {
        "type": "run_command",
        "command": "printf hello",
    }


def test_normalize_action_canonicalizes_run_alias_from_json_string():
    result = _normalize_action(
        '{"type":"run","command":"printf hello"}'
    )

    assert result == {
        "type": "run_command",
        "command": "printf hello",
    }


def test_normalize_action_rejects_non_json_provider_text():
    assert (
        _normalize_action(
            "Please run this command: printf hello"
        )
        is None
    )


def test_normalize_action_rejects_json_scalar_string():
    assert _normalize_action('"run_command"') is None


def test_targeted_patch_normalizes():
    result = _normalize_action(
        {
            "type": "targeted_patch",
            "path": "sample.txt",
            "old": "before",
            "new": "after",
        }
    )

    assert result == {
        "type": "targeted_patch",
        "path": "sample.txt",
        "old": "before",
        "new": "after",
    }


def test_targeted_patch_replaces_exactly_one_match(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("alpha\nbefore\nomega\n", encoding="utf-8")

    ok, result = execute_action(
        {
            "type": "targeted_patch",
            "path": "sample.txt",
            "old": "before",
            "new": "after",
        },
        tmp_path,
        lambda _: None,
    )

    assert ok is True
    assert target.read_text(encoding="utf-8") == "alpha\nafter\nomega\n"


def test_targeted_patch_rejects_ambiguous_old_text(tmp_path):
    target = tmp_path / "sample.txt"
    original = "before\nbefore\n"
    target.write_text(original, encoding="utf-8")

    ok, result = execute_action(
        {
            "type": "targeted_patch",
            "path": "sample.txt",
            "old": "before",
            "new": "after",
        },
        tmp_path,
        lambda _: None,
    )

    assert ok is False
    assert target.read_text(encoding="utf-8") == original


def test_targeted_patch_rejects_outside_workspace(tmp_path):
    ok, result = execute_action(
        {
            "type": "targeted_patch",
            "path": "../outside.txt",
            "old": "before",
            "new": "after",
        },
        tmp_path,
        lambda _: None,
    )

    assert ok is False
