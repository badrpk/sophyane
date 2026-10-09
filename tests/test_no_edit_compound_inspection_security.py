import pytest

from sophyane.adaptive_execution import (
    _no_edit_action_problem,
    _no_edit_command_allowed,
)


@pytest.mark.parametrize(
    "command",
    [
        "pwd && find . -maxdepth 2 -type f -print | sort",
        "find . -maxdepth 2 -type f -print | sort",
    ],
)
def test_safe_compound_inspection_is_admitted(command):
    assert _no_edit_command_allowed(command)
    assert not _no_edit_action_problem(
        {"type": "run_command", "command": command}
    )


@pytest.mark.parametrize(
    "command",
    [
        "cat pyproject.toml; touch output.txt",
        "cat pyproject.toml | tee output.txt",
        "grep pattern README.md && touch output.txt",
        "pwd && touch output.txt",
        "find . -type f | xargs rm -f",
        "find . -type f -delete",
        "find . -exec touch output.txt \\;",
        "find . -type f | sort > output.txt",
        "find . -type f | sort && touch output.txt",
        "pwd && find . -type f | sort $(touch output.txt)",
        "pwd && find . -type f | sort ${UNTRUSTED_PATH}",
        "find . -type f | sort `touch output.txt`",
    ],
)
def test_unsafe_compound_inspection_is_rejected(command):
    assert not _no_edit_command_allowed(command)
    assert _no_edit_action_problem(
        {"type": "run_command", "command": command}
    )
