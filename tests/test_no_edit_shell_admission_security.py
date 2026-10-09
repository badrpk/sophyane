import pytest

from sophyane.adaptive_execution import (
    _no_edit_action_problem,
    _no_edit_command_allowed,
)


@pytest.mark.parametrize(
    "command",
    [
        "cat pyproject.toml > output.txt",
        "cat pyproject.toml; touch output.txt",
        "cat pyproject.toml | tee output.txt",
        "cat $(touch output.txt)",
        "cat ${UNTRUSTED_PATH}",
        "git status; touch output.txt",
        "grep pattern README.md && touch output.txt",
        "cat pyproject.toml > /tmp/output.txt",
        "cat pyproject.toml 2> output.txt",
        "cat <(touch output.txt)",
    ],
)
def test_unsafe_shell_is_rejected(command):
    assert not _no_edit_command_allowed(command)
    assert _no_edit_action_problem(
        {"type": "command", "command": command}
    )


@pytest.mark.parametrize(
    "command",
    [
        "cat pyproject.toml",
        "pwd",
        "git status --short",
        "git ls-files",
    ],
)
def test_simple_read_only_commands_remain_allowed(command):
    assert _no_edit_command_allowed(command)
    assert not _no_edit_action_problem(
        {"type": "command", "command": command}
    )
