from pathlib import Path

import pytest

from sophyane import adaptive_execution as adaptive


@pytest.mark.parametrize(
    ("command", "keyword"),
    (
        ("if true; then echo ok; fi", "if"),
        ('for x in a b; do echo "$x"; done', "for"),
        ("while false; do echo never; done", "while"),
        ("until true; do echo never; done", "until"),
        ("case x in x) echo ok;; esac", "case"),
        ("select x in a b; do echo \"$x\"; break; done", "select"),
    ),
)
def test_shell_control_recipe_is_explicitly_rejected_even_if_host_resolves_keyword(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    keyword: str,
) -> None:
    """Shell-control recipes must not depend on host executable discovery."""

    monkeypatch.setattr(
        adaptive.shutil,
        "which",
        lambda _name: "/synthetic/host/executable",
    )

    problem = adaptive._command_problem(
        {
            "type": "run_command",
            "command": command,
        },
        tmp_path,
    )

    assert problem == (
        "model returned a shell recipe or natural-language "
        "instruction instead of source files"
    )

    # Prove this is the explicit recipe gate, not executable lookup.
    assert keyword not in problem


@pytest.mark.parametrize(
    "command",
    (
        "git diff --check",
        "python -V",
    ),
)
def test_normal_executable_commands_remain_valid_when_host_resolves_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.setattr(
        adaptive.shutil,
        "which",
        lambda _name: "/synthetic/host/executable",
    )

    assert (
        adaptive._command_problem(
            {
                "type": "run_command",
                "command": command,
            },
            tmp_path,
        )
        == ""
    )
