"""Session-scoped memory for persistent command environment constraints."""

from __future__ import annotations

import re
import shlex
from pathlib import Path


# Constraints are isolated by workspace and live only for this Python process.
_CONSTRAINTS: dict[str, dict[str, str]] = {}


def _workspace_key(workspace: Path) -> str:
    return str(workspace.resolve())


def command_capability_key(command: str) -> str:
    """Return a normalized capability family for a generated command."""

    try:
        tokens = shlex.split(command)
    except ValueError:
        return ""

    if not tokens:
        return ""

    # python/python3/... -m <module>
    python_names = {
        "python",
        "python3",
        "python3.10",
        "python3.11",
        "python3.12",
        "python3.13",
    }

    executable = Path(tokens[0]).name.lower()

    if executable in python_names:
        for index, token in enumerate(tokens[:-1]):
            if token == "-m":
                module = tokens[index + 1].strip().lower()
                if module:
                    return f"python-module:{module}"
                break

    # Direct invocation of well-known test runners and tools.
    if executable in {
        "pytest",
        "py.test",
        "tox",
        "nox",
        "ruff",
        "mypy",
        "cargo",
        "npm",
        "pnpm",
        "yarn",
    }:
        return f"executable:{executable}"

    return ""


def remember_constraint(
    workspace: Path,
    capability_key: str,
    explanation: str,
) -> None:
    """Remember a persistent environment constraint for this session."""

    if not capability_key:
        return

    constraints = _CONSTRAINTS.setdefault(_workspace_key(workspace), {})
    constraints[capability_key] = explanation.strip()



def _is_broad_unittest_discovery(command: str) -> bool:
    """Return whether a command performs broad unittest discovery."""

    lowered = " ".join(command.lower().split())
    return "-m unittest discover" in lowered or "unittest discover" in lowered


def _missing_imports(workspace: Path) -> list[str]:
    """Return imports known to be unavailable in a workspace."""

    constraints = _CONSTRAINTS.get(_workspace_key(workspace), {})

    return sorted(
        key.removeprefix("python-import:")
        for key in constraints
        if key.startswith("python-import:")
    )




def _is_system_pip_install(command: str) -> bool:
    """Return whether a command attempts installation with system pip."""

    lowered = " ".join(command.lower().split())

    pip_install_markers = (
        "python -m pip install ",
        "python3 -m pip install ",
        "/usr/bin/python -m pip install ",
        "/usr/bin/python3 -m pip install ",
        "pip install ",
        "pip3 install ",
    )

    return any(marker in lowered for marker in pip_install_markers)


def _system_pip_install_is_blocked(workspace: Path) -> bool:
    """Return whether PEP 668 blocked system pip in this workspace."""

    constraints = _CONSTRAINTS.get(_workspace_key(workspace), {})
    return "python-package-install:system-pip" in constraints



def constraint_for_command(workspace: Path, command: str) -> str:
    """Return a planner-visible message when a command family is unavailable."""

    if (
        _system_pip_install_is_blocked(workspace)
        and _is_system_pip_install(command)
    ):
        return (
            "Known environment constraint: system pip installation is "
            "blocked because this Python environment is externally managed "
            "under PEP 668. Do not retry pip install during this execution. "
            "Use an existing virtual environment, create an isolated virtual "
            "environment when permitted, use the operating-system package "
            "manager with user approval, or report that dependency "
            "installation is blocked."
        )

    missing_imports = _missing_imports(workspace)

    if missing_imports and _is_broad_unittest_discovery(command):
        modules = ", ".join(repr(module) for module in missing_imports)
        return (
            "Known environment constraint: broad unittest discovery will "
            "import test modules requiring unavailable Python module(s): "
            f"{modules}. Do not repeat broad discovery. Run a focused test "
            "subset that does not require those modules, install the missing "
            "dependency, or report that complete verification is blocked."
        )

    key = command_capability_key(command)
    if not key:
        return ""

    explanation = _CONSTRAINTS.get(_workspace_key(workspace), {}).get(key)
    if not explanation:
        return ""

    return (
        "Known environment constraint: "
        + explanation
        + " Do not retry an equivalent command during this execution. "
          "Use an available alternative or report the missing dependency."
    )


def learn_constraints_from_result(
    workspace: Path,
    command: str,
    result: str,
) -> str:
    """Recognize persistent environment failures in command output."""

    text = result or ""
    lowered = text.lower()

    # PEP 668: system Python is externally managed — block later system pip.
    externally_managed_markers = (
        "externally-managed-environment",
        "this environment is externally managed",
        "pep 668",
    )
    if _is_system_pip_install(command) and any(
        marker in lowered for marker in externally_managed_markers
    ):
        key = "python-package-install:system-pip"
        explanation = (
            "System pip installation is blocked because this Python "
            "environment is externally managed under PEP 668."
        )
        remember_constraint(workspace, key, explanation)
        return key


    missing_module = re.search(
        r"(?:no module named|modulenotfounderror:\s*no module named)\s+"
        r"['\"]?([a-zA-Z0-9_.-]+)",
        text,
        flags=re.IGNORECASE,
    )

    if missing_module:
        module = missing_module.group(1).strip("'\"").lower()
        key = f"python-module:{module}"
        explanation = f"Python module '{module}' is unavailable."
        remember_constraint(workspace, key, explanation)

        import_failure_markers = (
            "modulenotfounderror:",
            "failed to import test module",
            "importerror:",
        )

        if any(marker in lowered for marker in import_failure_markers):
            remember_constraint(
                workspace,
                f"python-import:{module}",
                f"Python import '{module}' is unavailable.",
            )

        return key

    missing_executable = re.search(
        r"executable does not exist:\s*([^\s]+)",
        text,
        flags=re.IGNORECASE,
    )

    if missing_executable:
        executable = Path(
            missing_executable.group(1).strip("'\"")
        ).name.lower()
        key = f"executable:{executable}"
        explanation = f"Executable '{executable}' is unavailable."
        remember_constraint(workspace, key, explanation)
        return key

    # Common shell-level command-not-found forms.
    command_not_found = re.search(
        r"(?:^|\n)(?:/bin/sh:\s*\d+:\s*)?"
        r"([a-zA-Z0-9_.+-]+):\s*(?:command\s+)?not found",
        text,
        flags=re.IGNORECASE,
    )

    if command_not_found:
        executable = command_not_found.group(1).lower()
        key = f"executable:{executable}"
        explanation = f"Executable '{executable}' is unavailable."
        remember_constraint(workspace, key, explanation)
        return key

    # When Python reports the module failure, normalize by the actual module
    # rather than merely by the originally proposed command.
    capability = command_capability_key(command)
    if capability and "no module named" in lowered:
        remember_constraint(
            workspace,
            capability,
            f"Required capability '{capability}' is unavailable.",
        )
        return capability

    return ""


def verification_result_is_meaningful(command: str, result: str) -> bool:
    """Decide whether exit-code-zero output constitutes real verification."""

    text = result or ""
    lowered = text.lower()

    if "exit code: 0" not in lowered:
        return False

    failure_markers = (
        "no tests ran",
        "no test ran",
        "ran 0 tests",
        "ran 0 test",
        "collected 0 items",
        "0 tests collected",
        "no module named",
        "modulenotfounderror",
        "command not found",
        "executable does not exist",
    )

    if any(marker in lowered for marker in failure_markers):
        return False

    capability = command_capability_key(command)
    command_lower = command.lower()

    appears_to_be_test_command = (
        capability in {
            "python-module:pytest",
            "executable:pytest",
            "executable:py.test",
            "python-module:unittest",
        }
        or " unittest " in f" {command_lower} "
        or "/test_" in command_lower
        or "tests/" in command_lower
    )

    if not appears_to_be_test_command:
        return True

    stdout_match = re.search(
        r"STDOUT:\s*(.*?)\s*STDERR:",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    stderr_match = re.search(
        r"STDERR:\s*(.*)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    stdout = stdout_match.group(1).strip() if stdout_match else ""
    stderr = stderr_match.group(1).strip() if stderr_match else ""

    # A test command that silently exits zero does not prove tests executed.
    if not stdout and not stderr:
        return False

    positive_markers = (
        "passed",
        "tests ran",
        "test ran",
        "ran 1 test",
        "ran 2 tests",
        "ran 3 tests",
        "ran 4 tests",
        "ran 5 tests",
        "ran 6 tests",
        "ran 7 tests",
        "ran 8 tests",
        "ran 9 tests",
        "ran 10 tests",
        "ok",
    )

    return any(marker in lowered for marker in positive_markers)


def clear_environment_constraints(workspace: Path | None = None) -> None:
    """Clear constraints, primarily for tests."""

    if workspace is None:
        _CONSTRAINTS.clear()
        return

    _CONSTRAINTS.pop(_workspace_key(workspace), None)
