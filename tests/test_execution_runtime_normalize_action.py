from sophyane.execution_runtime import (
    _normalize_action,
)


def test_invalid_string_action_does_not_raise_unbound_local():
    result = _normalize_action(
        {
            "action": "not_a_real_action",
        }
    )

    assert result is None


def test_valid_string_action_is_normalized():
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


def test_string_answer_alias_becomes_respond():
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


def test_invalid_string_action_can_fall_through_to_nested_action():
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
