#!/usr/bin/env python3
"""
Sophyane v5 local agent runtime.

Provides:
- Safe local system inspection
- Persistent SQLite memory
- Restricted shell execution
- Automatic tool routing
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .neuron_security import (
    NeuronSecurityDecision,
    NeuronSecurityUnavailable,
    authorize_shell,
)


BASE_DIR = Path.home() / ".sophyane"
DATA_DIR = BASE_DIR / "data"
WORKSPACE_DIR = BASE_DIR / "workspace"
DATABASE_FILE = DATA_DIR / "memory.db"

BASE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


SAFE_COMMANDS = {
    "uname",
    "uptime",
    "whoami",
    "hostname",
    "pwd",
    "date",
    "id",
    "ls",
    "find",
    "du",
    "df",
    "free",
    "lscpu",
    "lsmem",
    "lsblk",
    "lspci",
    "lsusb",
    "ip",
    "ss",
    "ps",
    "top",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "sed",
    "awk",
    "git",
    "python3",
    "pip",
    "pip3",
    "env",
    "printenv",
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
    r"\buseradd\b",
    r"\buserdel\b",
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
    r"\bnc\b",
    r"\bnetcat\b",
    r"\beval\b",
    r"\bexec\b",
    r">\s*/",
    r"\|\s*(sh|bash|zsh)\b",
    r"\$\(",
    r"`",
    r";",
    r"&&",
    r"\|\|",
]


class RuntimeErrorMessage(Exception):
    """Safe user-facing runtime error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            content TEXT NOT NULL UNIQUE,
            importance INTEGER NOT NULL DEFAULT 5
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            input_text TEXT,
            output_text TEXT,
            successful INTEGER NOT NULL
        )
        """
    )

    connection.commit()
    return connection


def remember(content: str, importance: int = 5) -> str:
    content = content.strip()

    if not content:
        return "Nothing was supplied to remember."

    importance = max(1, min(10, int(importance)))

    with database() as connection:
        connection.execute(
            """
            INSERT INTO memories(created_at, content, importance)
            VALUES (?, ?, ?)
            ON CONFLICT(content) DO UPDATE SET
                created_at = excluded.created_at,
                importance = excluded.importance
            """,
            (utc_now(), content, importance),
        )
        connection.commit()

    return f"Remembered: {content}"


def recall_memories(limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(100, limit))

    with database() as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, content, importance
            FROM memories
            ORDER BY importance DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def forget_memory(memory_id: int) -> str:
    with database() as connection:
        cursor = connection.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,),
        )
        connection.commit()

    if cursor.rowcount:
        return f"Memory {memory_id} deleted."

    return f"Memory {memory_id} was not found."


def format_memories(limit: int = 20) -> str:
    memories = recall_memories(limit)

    if not memories:
        return "No memories stored."

    lines = ["Stored memories:"]

    for memory in memories:
        lines.append(
            f"[{memory['id']}] "
            f"(importance {memory['importance']}) "
            f"{memory['content']}"
        )

    return "\n".join(lines)


def log_tool(
    tool_name: str,
    input_text: str,
    output_text: str,
    successful: bool,
) -> None:
    try:
        with database() as connection:
            connection.execute(
                """
                INSERT INTO tool_history(
                    created_at,
                    tool_name,
                    input_text,
                    output_text,
                    successful
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    tool_name,
                    input_text[:5000],
                    output_text[:20000],
                    1 if successful else 0,
                ),
            )
            connection.commit()
    except sqlite3.Error:
        pass


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def run_command(
    arguments: list[str],
    timeout: int = 15,
    cwd: Path | None = None,
) -> str:
    if not arguments:
        raise RuntimeErrorMessage("No command supplied.")

    executable = arguments[0]

    if not command_exists(executable):
        return f"$ {' '.join(arguments)}\nCommand not installed: {executable}"

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
        return f"$ {' '.join(arguments)}\nCommand timed out after {timeout}s."
    except OSError as error:
        return f"$ {' '.join(arguments)}\nExecution failed: {error}"

    output_parts = [f"$ {' '.join(arguments)}"]

    if result.stdout.strip():
        output_parts.append(result.stdout.strip())

    if result.stderr.strip():
        output_parts.append("STDERR:")
        output_parts.append(result.stderr.strip())

    output_parts.append(f"[exit code: {result.returncode}]")

    return "\n".join(output_parts)


def first_existing_command(commands: list[list[str]]) -> str:
    for command in commands:
        if command and command_exists(command[0]):
            return run_command(command)

    return "No supported command was found."


def system_information() -> str:
    sections: list[str] = []

    sections.append(
        "\n".join(
            [
                "=== BASIC SYSTEM ===",
                f"Platform: {platform.platform()}",
                f"System: {platform.system()}",
                f"Release: {platform.release()}",
                f"Architecture: {platform.machine()}",
                f"Python: {platform.python_version()}",
                f"Hostname: {socket.gethostname()}",
                f"User: {os.getenv('USER', 'unknown')}",
                f"Current directory: {Path.cwd()}",
                f"Workspace: {WORKSPACE_DIR}",
            ]
        )
    )

    if Path("/etc/os-release").exists():
        sections.append(
            run_command(["cat", "/etc/os-release"])
        )

    sections.append(
        first_existing_command(
            [
                ["lscpu"],
                ["uname", "-a"],
            ]
        )
    )

    sections.append(
        first_existing_command(
            [
                ["free", "-h"],
                ["cat", "/proc/meminfo"],
            ]
        )
    )

    sections.append(run_command(["df", "-h"]))

    sections.append(
        first_existing_command(
            [
                ["lsblk"],
                ["df", "-h"],
            ]
        )
    )

    sections.append(run_command(["uptime"]))

    output = "\n\n".join(sections)
    log_tool("system_information", "", output, True)
    return output


def cpu_information() -> str:
    output = first_existing_command(
        [
            ["lscpu"],
            ["cat", "/proc/cpuinfo"],
            ["uname", "-m"],
        ]
    )
    log_tool("cpu_information", "", output, True)
    return output


def memory_information() -> str:
    output = first_existing_command(
        [
            ["free", "-h"],
            ["cat", "/proc/meminfo"],
        ]
    )
    log_tool("memory_information", "", output, True)
    return output


def disk_information() -> str:
    outputs = [
        run_command(["df", "-h"]),
        first_existing_command(
            [
                ["lsblk"],
                ["du", "-sh", str(Path.home())],
            ]
        ),
    ]

    output = "\n\n".join(outputs)
    log_tool("disk_information", "", output, True)
    return output


def network_information() -> str:
    outputs = [
        first_existing_command(
            [
                ["ip", "address"],
                ["hostname", "-I"],
            ]
        ),
        first_existing_command(
            [
                ["ip", "route"],
                ["route", "-n"],
            ]
        ),
        first_existing_command(
            [
                ["ss", "-tuln"],
                ["netstat", "-tuln"],
            ]
        ),
    ]

    output = "\n\n".join(outputs)
    log_tool("network_information", "", output, True)
    return output


def process_information() -> str:
    output = first_existing_command(
        [
            ["ps", "aux", "--sort=-%mem"],
            ["ps", "aux"],
        ]
    )

    lines = output.splitlines()
    shortened = "\n".join(lines[:35])

    log_tool("process_information", "", shortened, True)
    return shortened


def git_information() -> str:
    current = Path.cwd()

    output = "\n\n".join(
        [
            run_command(["git", "status", "--short", "--branch"], cwd=current),
            run_command(["git", "remote", "-v"], cwd=current),
            run_command(
                ["git", "log", "-5", "--oneline", "--decorate"],
                cwd=current,
            ),
        ]
    )

    log_tool("git_information", str(current), output, True)
    return output


def directory_information(path_text: str = ".") -> str:
    requested_path = Path(path_text).expanduser()

    try:
        resolved = requested_path.resolve()
    except OSError as error:
        return f"Could not resolve path: {error}"

    if not resolved.exists():
        return f"Path does not exist: {resolved}"

    if not resolved.is_dir():
        return f"Path is not a directory: {resolved}"

    try:
        entries = sorted(
            resolved.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
    except PermissionError:
        return f"Permission denied: {resolved}"

    lines = [f"Directory: {resolved}"]

    for entry in entries[:200]:
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"- {entry.name}{suffix}")

    if len(entries) > 200:
        lines.append(f"... {len(entries) - 200} additional entries")

    output = "\n".join(lines)
    log_tool("directory_information", str(resolved), output, True)
    return output


def validate_shell_command(command_text: str) -> list[str]:
    command_text = command_text.strip()

    if not command_text:
        raise RuntimeErrorMessage("No shell command supplied.")

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command_text, flags=re.IGNORECASE):
            raise RuntimeErrorMessage(
                "The command contains a blocked or potentially destructive "
                "shell operation."
            )

    try:
        arguments = shlex.split(command_text)
    except ValueError as error:
        raise RuntimeErrorMessage(
            f"Could not parse shell command: {error}"
        ) from error

    if not arguments:
        raise RuntimeErrorMessage("No command supplied.")

    executable = Path(arguments[0]).name

    if executable not in SAFE_COMMANDS:
        raise RuntimeErrorMessage(
            f"Command '{executable}' is not in Sophyane's safe command list."
        )

    return arguments


def safe_shell(command_text: str) -> str:
    try:
        arguments = validate_shell_command(command_text)
    except RuntimeErrorMessage as error:
        output = f"Shell command rejected: {error}"
        log_tool("safe_shell", command_text, output, False)
        return output

    try:
        security = authorize_shell(command_text)
    except NeuronSecurityUnavailable as error:
        output = f"Shell command rejected: {error}"
        log_tool("safe_shell", command_text, output, False)
        return output

    if security.decision in {
        NeuronSecurityDecision.ISOLATE,
        NeuronSecurityDecision.BLOCK,
    }:
        reasons = ", ".join(security.reasons) or "policy decision"
        output = (
            "Shell command rejected by Neuron security: "
            f"{security.decision.value} ({reasons})."
        )
        log_tool("safe_shell", command_text, output, False)
        return output

    print()
    print("Sophyane wants to execute:")
    print(f"  {' '.join(shlex.quote(item) for item in arguments)}")
    print()

    if security.decision == NeuronSecurityDecision.REQUIRE_REVIEW:
        print(
            "Neuron security requires review "
            f"(risk={security.risk:.3f})."
        )

    confirmation = input("Allow this command? [y/N]: ").strip().lower()

    if confirmation not in {"y", "yes"}:
        output = "Command cancelled by user."
        log_tool("safe_shell", command_text, output, False)
        return output

    output = run_command(arguments, timeout=30)
    log_tool("safe_shell", command_text, output, True)
    return output


def tools_help() -> str:
    return """Available Sophyane tools:

Natural-language tools:
  check my system configuration
  show CPU information
  check RAM or memory
  check disk/storage
  inspect network configuration
  show running processes
  check Git repository
  list files

Commands:
  /tools
  /memory
  /remember <information>
  /forget <memory-id>
  /system
  /cpu
  /ram
  /disk
  /network
  /processes
  /git
  /files [path]
  /shell <safe-command>

Configuration commands:
  /setup
  /status
  /clear
  /exit

Shell commands are restricted and require confirmation.
Destructive commands are blocked.
"""


def detect_natural_tool(prompt: str) -> str | None:
    normalized = prompt.lower().strip()

    system_phrases = [
        "system configuration",
        "system information",
        "computer configuration",
        "machine configuration",
    ]

    if any(phrase in normalized for phrase in system_phrases):
        return "system"

    if any(phrase in normalized for phrase in ["cpu", "processor"]):
        return "cpu"

    if any(phrase in normalized for phrase in ["ram", "memory usage", "memory information"]):
        return "ram"

    if any(phrase in normalized for phrase in ["disk", "storage", "filesystem"]):
        return "disk"

    if any(phrase in normalized for phrase in ["network", "ip address", "routing", "ports"]):
        return "network"

    if any(phrase in normalized for phrase in ["processes", "running processes", "process list"]):
        return "processes"

    if any(phrase in normalized for phrase in ["git status", "repository status", "git repository"]):
        return "git"

    if any(phrase in normalized for phrase in ["list files", "show files", "directory contents"]):
        return "files"

    return None


def route_tool(prompt: str) -> str | None:
    prompt = prompt.strip()

    if not prompt:
        return None

    if prompt == "/tools":
        return tools_help()

    if prompt == "/memory":
        return format_memories()

    if prompt.startswith("/remember "):
        return remember(prompt[len("/remember ") :])

    if prompt.startswith("/forget "):
        memory_id = prompt[len("/forget ") :].strip()
        try:
            return forget_memory(int(memory_id))
        except ValueError:
            return "Usage: /forget <memory-id>"

    if prompt == "/system":
        return system_information()

    if prompt == "/cpu":
        return cpu_information()

    if prompt == "/ram":
        return memory_information()

    if prompt == "/disk":
        return disk_information()

    if prompt == "/network":
        return network_information()

    if prompt == "/processes":
        return process_information()

    if prompt == "/git":
        return git_information()

    if prompt.startswith("/files"):
        path_text = prompt[len("/files") :].strip() or "."
        return directory_information(path_text)

    if prompt.startswith("/shell "):
        return safe_shell(prompt[len("/shell ") :])

    natural_tool = detect_natural_tool(prompt)

    if natural_tool == "system":
        return system_information()
    if natural_tool == "cpu":
        return cpu_information()
    if natural_tool == "ram":
        return memory_information()
    if natural_tool == "disk":
        return disk_information()
    if natural_tool == "network":
        return network_information()
    if natural_tool == "processes":
        return process_information()
    if natural_tool == "git":
        return git_information()
    if natural_tool == "files":
        return directory_information()

    return None
