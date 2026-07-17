"""Safe local Sophyane tools."""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sophyane.config import WORKSPACE_DIR, ensure_directories
from sophyane.repository import repository_report


@dataclass
class ToolResult:
    tool: str
    successful: bool
    output: str


SAFE_COMMANDS = {
    "date",
    "df",
    "du",
    "free",
    "hostname",
    "id",
    "ip",
    "ls",
    "lsblk",
    "lscpu",
    "lsmem",
    "lspci",
    "lsusb",
    "ps",
    "pwd",
    "ss",
    "top",
    "uname",
    "uptime",
    "whoami",
}

BLOCKED_PATTERNS = [
    r"\brm\b",
    r"\brmdir\b",
    r"\bmkfs\b",
    r"\bdd\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bhalt\b",
    r"\bkill\b",
    r"\bpkill\b",
    r"\bkillall\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bmount\b",
    r"\bumount\b",
    r"\bpasswd\b",
    r"\bsudo\b",
    r"\bsu\b",
    r"\bapt\b",
    r"\bapt-get\b",
    r"\bdnf\b",
    r"\byum\b",
    r"\bpacman\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\beval\b",
    r"\bexec\b",
    r"\$\(",
    r"`",
    r";",
    r"&&",
    r"\|\|",
    r"\|\s*(?:sh|bash|zsh)\b",
    r">\s*/",
]


def run_process(
    arguments: list[str],
    timeout: int = 20,
    cwd: Path | None = None,
) -> ToolResult:
    if not arguments:
        return ToolResult(
            "shell",
            False,
            "No command supplied.",
        )

    if shutil.which(arguments[0]) is None:
        return ToolResult(
            "shell",
            False,
            f"Command not installed: {arguments[0]}",
        )

    try:
        result = subprocess.run(
            arguments,
            cwd=str(cwd or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={
                **os.environ,
                "LC_ALL": "C.UTF-8",
                "LANG": "C.UTF-8",
            },
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            "shell",
            False,
            f"Command timed out after {timeout} seconds.",
        )
    except OSError as error:
        return ToolResult(
            "shell",
            False,
            f"Execution failed: {error}",
        )

    sections = [f"$ {shlex.join(arguments)}"]

    if result.stdout.strip():
        sections.append(result.stdout.strip())

    if result.stderr.strip():
        sections.extend(
            ["STDERR:", result.stderr.strip()]
        )

    sections.append(f"[exit code: {result.returncode}]")

    return ToolResult(
        "shell",
        result.returncode == 0,
        "\n".join(sections),
    )


def validate_shell(command: str) -> list[str]:
    command = command.strip()

    if not command:
        raise ValueError("No command supplied.")

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            raise ValueError(
                "Potentially destructive shell operation blocked."
            )

    arguments = shlex.split(command)

    if not arguments:
        raise ValueError("No command supplied.")

    executable = Path(arguments[0]).name

    if executable not in SAFE_COMMANDS:
        raise ValueError(
            f"Command '{executable}' is not in the safe command list."
        )

    return arguments


def safe_shell(
    command: str,
    require_confirmation: bool = True,
) -> ToolResult:
    try:
        arguments = validate_shell(command)
    except ValueError as error:
        return ToolResult(
            "shell",
            False,
            f"Rejected: {error}",
        )

    if require_confirmation:
        print()
        print(f"Proposed command: {shlex.join(arguments)}")
        confirmation = input(
            "Allow execution? [y/N]: "
        ).strip().lower()

        if confirmation not in {"y", "yes"}:
            return ToolResult(
                "shell",
                False,
                "Command cancelled by user.",
            )

    ensure_directories()
    return run_process(arguments, timeout=30, cwd=WORKSPACE_DIR.resolve())


def system_information() -> ToolResult:
    ensure_directories()

    commands = [
        ["cat", "/etc/os-release"],
        ["uname", "-a"],
        ["lscpu"],
        ["free", "-h"],
        ["df", "-h"],
        ["lsblk"],
        ["uptime"],
    ]

    sections = [
        "=== SOPHYANE LOCAL SYSTEM ===",
        f"Platform: {platform.platform()}",
        f"Architecture: {platform.machine()}",
        f"Python: {platform.python_version()}",
        f"Hostname: {socket.gethostname()}",
        f"User: {os.getenv('USER', 'unknown')}",
        f"Current directory: {Path.cwd()}",
        f"Workspace: {WORKSPACE_DIR}",
    ]

    success = True

    for command in commands:
        if shutil.which(command[0]) is None:
            continue

        result = run_process(command)
        sections.append(result.output)
        success = success and result.successful

    return ToolResult(
        "system",
        success,
        "\n\n".join(sections),
    )


def repository_information() -> ToolResult:
    try:
        output = repository_report()
    except Exception as error:
        return ToolResult(
            "repository",
            False,
            f"Repository inspection failed: {error}",
        )

    return ToolResult(
        "repository",
        True,
        output,
    )



def resolve_workspace_path(path_text: str = ".") -> Path:
    """Resolve a user path and reject escapes from Sophyane's workspace."""
    workspace = WORKSPACE_DIR.expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    root = workspace.resolve()
    candidate = Path(path_text).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"Path is outside the Sophyane workspace: {resolved}"
        ) from error
    return resolved

def list_directory(path_text: str = ".") -> ToolResult:
    try:
        path = resolve_workspace_path(path_text)
    except ValueError as error:
        return ToolResult("files", False, f"Rejected: {error}")

    if not path.exists():
        return ToolResult(
            "files",
            False,
            f"Path does not exist: {path}",
        )

    if not path.is_dir():
        return ToolResult(
            "files",
            False,
            f"Not a directory: {path}",
        )

    try:
        entries = sorted(
            path.iterdir(),
            key=lambda item: (
                not item.is_dir(),
                item.name.lower(),
            ),
        )
    except OSError as error:
        return ToolResult(
            "files",
            False,
            f"Cannot list directory: {error}",
        )

    lines = [f"Directory: {path}"]

    for entry in entries[:300]:
        lines.append(
            f"- {entry.name}{'/' if entry.is_dir() else ''}"
        )

    return ToolResult(
        "files",
        True,
        "\n".join(lines),
    )


def read_text_file(path_text: str) -> ToolResult:
    try:
        path = resolve_workspace_path(path_text)
    except ValueError as error:
        return ToolResult("read", False, f"Rejected: {error}")

    if not path.exists() or not path.is_file():
        return ToolResult(
            "read",
            False,
            f"File not found: {path}",
        )

    if path.stat().st_size > 1_000_000:
        return ToolResult(
            "read",
            False,
            "File exceeds the 1 MB safe read limit.",
        )

    try:
        content = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return ToolResult(
            "read",
            False,
            f"Could not read file: {error}",
        )

    return ToolResult(
        "read",
        True,
        f"File: {path}\n\n{content}",
    )


def tools_description() -> str:
    return """Available local tools:

  system       Inspect OS, CPU, RAM, storage and uptime
  repository   Analyze project tree, imports, functions and Git state
  files        List a directory
  read         Read a text file up to 1 MB
  shell        Run a restricted command after confirmation
  memory       Persistent SQLite memory
  doctor       Run Sophyane self-diagnostics

Commands:
  /system
  /repo
  /files [path]
  /read <path>
  /shell <safe command>
  /remember <fact>
  /memory
  /forget <id>
  /doctor
  /providers
  /setup
  /status
  /exit

Plain aliases such as tools, status, memory, help and exit also work.
"""
