from __future__ import annotations

from pathlib import Path

from sophyane.fast_local_coding import (
    _resolve_fast_python_target,
)


def test_multi_file_request_prefers_only_incomplete_file(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "parser.py"
    ).write_text(
        "def parse_record(line):\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )

    (
        tmp_path
        / "service.py"
    ).write_text(
        "from parser import parse_record\n\n"
        "def parse_many(lines):\n"
        "    return [parse_record(x) for x in lines]\n",
        encoding="utf-8",
    )

    path, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request=(
                "Implement parse_record(line) in parser.py. "
                "Do not modify service.py."
            ),
            explicit_paths=[
                "parser.py",
                "service.py",
            ],
        )
    )

    assert path == "parser.py"
    assert "structural stub" in reason


def test_symbol_can_resolve_stub_when_multiple_python_files_exist(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "inventory.py"
    ).write_text(
        "def available(stock, requested):\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )

    (
        tmp_path
        / "checkout.py"
    ).write_text(
        "from inventory import available\n\n"
        "def can_checkout(stock, cart):\n"
        "    return all(available(stock, item) for item in cart)\n",
        encoding="utf-8",
    )

    path, _ = (
        _resolve_fast_python_target(
            root=tmp_path,
            request=(
                "Implement available(stock, requested). "
                "Do not modify checkout.py."
            ),
            explicit_paths=[
                "checkout.py",
            ],
        )
    )

    assert path == "inventory.py"


def test_ambiguous_structural_stubs_decline(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "a.py"
    ).write_text(
        "def first():\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )

    (
        tmp_path
        / "b.py"
    ).write_text(
        "def second():\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )

    path, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request="Implement the missing behavior.",
            explicit_paths=[],
        )
    )

    assert path is None
    assert "could not resolve" in reason


def test_single_explicit_non_stub_target_keeps_historical_path(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "average.py"
    ).write_text(
        "def mean(values):\n"
        "    return sum(values) / len(values)\n",
        encoding="utf-8",
    )

    path, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request="Fix mean(values) in average.py.",
            explicit_paths=[
                "average.py",
            ],
        )
    )

    assert path == "average.py"
    assert reason == "single explicit Python target"


def test_tests_are_never_selected_as_structural_targets(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "test_objective.py"
    ).write_text(
        "def helper():\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )

    (
        tmp_path
        / "real.py"
    ).write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    path, _ = (
        _resolve_fast_python_target(
            root=tmp_path,
            request="Implement missing behavior.",
            explicit_paths=[],
        )
    )

    assert path is None


def test_genuine_multiple_explicit_targets_still_decline(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "sample.py"
    ).write_text(
        "def target():\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )

    (
        tmp_path
        / "other.py"
    ).write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    path, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request="Update sample.py and other.py",
            explicit_paths=[
                "sample.py",
                "other.py",
            ],
        )
    )

    # Structural incompleteness alone is not authority to choose
    # one file from a generic multi-file update request.
    assert path is None
    assert (
        reason
        == "fast path requires exactly one explicit Python target"
    )


def test_no_path_and_no_symbol_does_not_pick_unique_workspace_stub(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "sample.py"
    ).write_text(
        "def target():\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )

    path, reason = (
        _resolve_fast_python_target(
            root=tmp_path,
            request="Inspect sample.py.bak only.",
            explicit_paths=[],
        )
    )

    assert path is None
    assert "could not resolve" in reason
