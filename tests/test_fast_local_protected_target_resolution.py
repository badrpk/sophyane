from __future__ import annotations

from pathlib import Path

from sophyane.fast_local_coding import (
    _explicit_python_paths,
    _protected_python_path_references,
    _resolve_fast_python_target,
)


def _files(root: Path) -> None:
    (root / "clamp_task.py").write_text(
        """def clamp(value, low, high):
    if value < low:
        return low
    if value >= high:
        return high - 1
    return value
""",
        encoding="utf-8",
    )

    (root / "test_clamp_task.py").write_text(
        """from clamp_task import clamp

def test_upper():
    assert clamp(10, 0, 10) == 10
""",
        encoding="utf-8",
    )


def test_do_not_modify_test_reference_is_not_writable_target(
    tmp_path: Path,
) -> None:
    _files(tmp_path)

    request = """
Repair the existing Python file clamp_task.py.
Do not modify test_clamp_task.py.
"""

    paths = _explicit_python_paths(
        request
    )

    assert paths == [
        "clamp_task.py",
        "test_clamp_task.py",
    ]

    protected = (
        _protected_python_path_references(
            request,
            paths,
        )
    )

    assert protected == {
        "test_clamp_task.py",
    }

    target, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request=request,
            explicit_paths=paths,
        )
    )

    assert target == "clamp_task.py"
    assert "single writable explicit" in reason


def test_pytest_command_reference_is_not_writable_target(
    tmp_path: Path,
) -> None:
    _files(tmp_path)

    request = """
Repair clamp_task.py.
Run pytest test_clamp_task.py.
"""

    paths = _explicit_python_paths(
        request
    )

    target, _reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request=request,
            explicit_paths=paths,
        )
    )

    assert target == "clamp_task.py"


def test_test_only_reference_does_not_become_edit_target(
    tmp_path: Path,
) -> None:
    _files(tmp_path)

    request = "Do not modify test_clamp_task.py."

    paths = _explicit_python_paths(
        request
    )

    target, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request=request,
            explicit_paths=paths,
        )
    )

    assert target is None
    assert "protected/test authority" in reason


def test_two_positive_edit_targets_remain_ambiguous(
    tmp_path: Path,
) -> None:
    _files(tmp_path)

    (tmp_path / "helper.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    request = (
        "Repair clamp_task.py and helper.py."
    )

    paths = _explicit_python_paths(
        request
    )

    target, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request=request,
            explicit_paths=paths,
        )
    )

    assert target is None
    assert (
        reason
        == "fast path requires exactly one explicit Python target"
    )


def test_full_clamp_mission_resolves_production_target(
    tmp_path: Path,
) -> None:
    _files(tmp_path)

    request = f"""
Repair the existing Python file clamp_task.py.

ACTIVE WORKSPACE:
{tmp_path}

Explicit requested function signature:
def clamp(value, low, high):

The existing pytest suite is immutable authority.

Observe the existing failing pytest suite, make the smallest justified
repair to clamp_task.py, rerun the existing tests, and only report
success after full-suite GREEN.

Do not modify test_clamp_task.py.
Do not commit.
Do not push.
"""

    paths = _explicit_python_paths(
        request
    )

    target, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request=request,
            explicit_paths=paths,
        )
    )

    assert target == "clamp_task.py"
    assert "single writable explicit" in reason


def test_second_positive_reference_remains_ambiguous_even_if_missing(
    tmp_path: Path,
) -> None:
    """Filesystem absence must not grant authority over the surviving path."""

    (tmp_path / "sample.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    request = (
        "Update sample.py and other.py"
    )

    paths = _explicit_python_paths(
        request
    )

    assert paths == [
        "sample.py",
        "other.py",
    ]

    target, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request=request,
            explicit_paths=paths,
        )
    )

    assert target is None
    assert (
        reason
        == "fast path requires exactly one explicit Python target"
    )
