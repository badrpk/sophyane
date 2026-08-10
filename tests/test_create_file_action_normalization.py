from sophyane.adaptive_execution import (
    _normalise_action,
)
from sophyane.execution_runtime import (
    _normalize_action,
)


FILE_SHAPED_CREATE = {
    "action": "create",
    "path": "project/app.py",
    "content": "print('hello')",
}


def test_adaptive_normalizes_file_shaped_create() -> None:
    result = _normalise_action(
        FILE_SHAPED_CREATE
    )

    assert result is not None
    assert result["type"] == "write_file"
    assert result["path"] == "project/app.py"
    assert result["content"] == "print('hello')"
    assert "action" not in result


def test_runtime_normalizes_file_shaped_create() -> None:
    result = _normalize_action(
        FILE_SHAPED_CREATE
    )

    assert result is not None
    assert result["type"] == "write_file"
    assert result["path"] == "project/app.py"
    assert result["content"] == "print('hello')"
    assert "action" not in result


def test_create_with_text_alias_is_file_write() -> None:
    value = {
        "action": "create",
        "file": "README.md",
        "text": "# Demo",
    }

    adaptive = _normalise_action(value)
    runtime = _normalize_action(value)

    assert adaptive is not None
    assert runtime is not None

    assert adaptive["type"] == "write_file"
    assert runtime["type"] == "write_file"


def test_bare_create_remains_unsupported() -> None:
    value = {
        "action": "create",
    }

    assert _normalise_action(value) is None
    assert _normalize_action(value) is None


def test_create_path_without_content_remains_unsupported() -> None:
    value = {
        "action": "create",
        "path": "project",
    }

    assert _normalise_action(value) is None
    assert _normalize_action(value) is None


def test_existing_write_file_behavior_is_preserved() -> None:
    value = {
        "action": "write_file",
        "path": "app.py",
        "content": "print(42)",
    }

    adaptive = _normalise_action(value)
    runtime = _normalize_action(value)

    assert adaptive is not None
    assert runtime is not None

    assert adaptive["type"] == "write_file"
    assert runtime["type"] == "write_file"
