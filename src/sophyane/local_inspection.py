from __future__ import annotations

import getpass
import os
import platform
import re
import shutil
import sys
from pathlib import Path


_SAFE_COMMAND = re.compile(r"^[A-Za-z0-9._+-]+$")


def _normalize(message: str) -> str:
    return " ".join(message.strip().lower().split()).strip(" .?!")


def _safe_command_name(name: str) -> bool:
    return bool(name and _SAFE_COMMAND.fullmatch(name))


def _command_lookup(text: str) -> str | None:
    for prefix in ("locate ", "where is ", "which "):
        if not text.startswith(prefix):
            continue

        rest = text[len(prefix):].strip()
        name = rest.split()[0] if rest else ""
        name = name.strip(" .?!,")

        if not _safe_command_name(name):
            return None

        found = shutil.which(name)

        if found:
            return f"{name}: {found}"

        return f"{name}: not found on PATH"

    return None


def _installed_python_interpreters() -> str:
    candidates = (
        "python",
        "python3",
        "python3.13",
        "python3.12",
        "python3.11",
        "python3.10",
        "pypy3",
    )

    found: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        executable = shutil.which(candidate)

        if not executable:
            continue

        resolved = str(Path(executable).resolve())

        if resolved in seen:
            continue

        seen.add(resolved)
        found.append(f"{candidate}: {executable}")

    if not found:
        return "No Python interpreters were found on PATH."

    return "Installed Python interpreters:\n" + "\n".join(found)


def inspect_local_request(message: str) -> str | None:
    text = _normalize(message)

    # Command-location requests must run before version matching.
    command_result = _command_lookup(text)
    if command_result is not None:
        return command_result

    if any(
        phrase in text
        for phrase in (
            "python version",
            "version of python",
            "python is installed",
            "installed python version",
            "what version of python",
        )
    ):
        return f"Python {sys.version.split()[0]} ({sys.executable})"

    if text in {
        "list installed python interpreters",
        "show installed python interpreters",
        "find installed python interpreters",
        "list python interpreters",
    }:
        return _installed_python_interpreters()

    if text in {
        "show path",
        "print path",
        "what is path",
        "what is my path",
        "show my path",
    }:
        return f"PATH={os.environ.get('PATH', '')}"

    if text in {
        "pwd",
        "show cwd",
        "what is cwd",
        "current directory",
        "working directory",
        "current working directory",
        "what is the current working directory",
        "where am i",
    }:
        return f"cwd: {Path.cwd()}"

    if text in {
        "what shell am i using",
        "which shell am i using",
        "show shell",
        "what is my shell",
    }:
        shell = os.environ.get("SHELL")

        if shell:
            return f"Shell: {shell}"

        return "Shell: unknown"

    if text in {
        "who am i",
        "what is my username",
        "show username",
        "current user",
    }:
        return f"User: {getpass.getuser()}"

    if text in {
        "what operating system is this",
        "what os is this",
        "show operating system",
        "show os",
        "operating system",
    }:
        return (
            f"Operating system: {platform.system()} "
            f"{platform.release()} ({platform.platform()})"
        )

    if text in {
        "what architecture is this machine",
        "what is the machine architecture",
        "show architecture",
        "machine architecture",
        "cpu architecture",
    }:
        architecture = platform.machine() or "unknown"
        bits = platform.architecture()[0]
        return f"Architecture: {architecture} ({bits})"

    if text in {
        "what is my home directory",
        "show home directory",
        "my home directory",
        "home directory",
    }:
        return f"Home: {Path.home()}"

    return None

def _email_followup_reply(message: str) -> str | None:
    """EMAIL digit/integration follow-ups without importing tui_v2."""
    t = " ".join(str(message or "").strip().lower().split())
    if t in {"1", "2", "3", "4"}:
        return (
            "Pick an email path with a full sentence, for example:\n"
            "  2) Read workspace file mail/last.eml and count words.\n"
            "  3) Scaffold a read-only IMAP script using SOPHYANE_IMAP_USER "
            "and SOPHYANE_IMAP_APP_PASSWORD (do not paste the app password)."
        )
    if any(p in t for p in ("integrate email", "how to integrate email", "email with sophyane")):
        try:
            from sophyane.capability_gap_messages import EMAIL_INTEGRATION_GUIDE
            return EMAIL_INTEGRATION_GUIDE
        except Exception:
            return "Email: paste, local .eml, or IMAP env SOPHYANE_IMAP_USER / SOPHYANE_IMAP_APP_PASSWORD."
    return None

