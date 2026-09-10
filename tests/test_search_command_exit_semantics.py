"""Regression coverage for search-command exit semantics."""

from sophyane.adaptive_execution import (
    _is_read_only_inspection_command,
)
from sophyane.execution_runtime import (
    _command_exit_code_is_accepted,
)
from sophyane.environment_constraints import (
    verification_result_is_meaningful,
)


# SOPHYANE_SEARCH_NO_MATCH_NONFATAL_REGRESSION_V1


def test_grep_match_exit_zero_is_valid():
    assert _command_exit_code_is_accepted(
        "grep -n needle file.txt",
        0,
    )


def test_grep_no_match_exit_one_is_valid_execution():
    assert _command_exit_code_is_accepted(
        "grep -n missing file.txt",
        1,
    )


def test_grep_exit_two_is_real_failure():
    assert not _command_exit_code_is_accepted(
        "grep -n needle missing-file.txt",
        2,
    )


def test_egrep_and_fgrep_no_match_are_valid():
    assert _command_exit_code_is_accepted(
        "egrep -n missing file.txt",
        1,
    )
    assert _command_exit_code_is_accepted(
        "fgrep -n missing file.txt",
        1,
    )


def test_ordinary_command_exit_one_remains_failure():
    assert not _command_exit_code_is_accepted(
        "python -m pytest -q",
        1,
    )
    assert not _command_exit_code_is_accepted(
        "git status",
        1,
    )


def test_grep_is_still_read_only_nonterminal_inspection():
    command = (
        "grep -RniE "
        "'class .*Agent|buyer|seller' . "
        "--include='*.py'"
    )

    assert _is_read_only_inspection_command(command)


def test_no_match_search_cannot_be_meaningful_verification():
    command = "grep -n missing app.py"

    synthetic_result = (
        f"Command: {command}\n"
        "Exit code: 1\n"
        "STDOUT:\n"
        "STDERR:\n"
    )

    assert _is_read_only_inspection_command(command)
    assert not verification_result_is_meaningful(
        command,
        synthetic_result,
    )


def test_failed_pytest_does_not_gain_search_semantics():
    command = "python -m pytest -q"

    assert not _command_exit_code_is_accepted(
        command,
        1,
    )
