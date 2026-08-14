from sophyane.execution_runtime import (
    _normalize_action,
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
