from sophyane.execution_runtime import _normalize_action


def test_invalid_string_action_does_not_raise_unbound_local() -> None:
    value = {
        "action": "build_project",
        "goal": "Create a SaaS",
    }

    assert _normalize_action(value) is None


def test_valid_string_action_is_normalized() -> None:
    value = {
        "action": "write_file",
        "path": "app.py",
        "content": "print('ok')",
    }

    result = _normalize_action(value)

    assert result is not None
    assert result["type"] == "write_file"
    assert "action" not in result
    assert result["path"] == "app.py"


def test_answer_alias_becomes_respond() -> None:
    result = _normalize_action(
        {
            "action": "answer",
            "message": "done",
        }
    )

    assert result is not None
    assert result["type"] == "respond"
    assert "action" not in result


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
