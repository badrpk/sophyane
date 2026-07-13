"""Deterministic command and intent router."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Route:
    kind: str
    argument: str = ""
    summarize: bool = False


COMMAND_ALIASES = {
    "tools": "tools",
    "help": "tools",
    "/help": "tools",
    "/tools": "tools",
    "status": "status",
    "/status": "status",
    "memory": "memory",
    "/memory": "memory",
    "providers": "providers",
    "/providers": "providers",
    "doctor": "doctor",
    "/doctor": "doctor",
    "system": "system",
    "/system": "system",
    "repo": "repository",
    "/repo": "repository",
    "repository": "repository",
    "setup": "setup",
    "/setup": "setup",
    "exit": "exit",
    "quit": "exit",
    "/exit": "exit",
    "/quit": "exit",
}


def route(message: str) -> Route:
    stripped = message.strip()
    lowered = stripped.lower()

    if lowered in COMMAND_ALIASES:
        kind = COMMAND_ALIASES[lowered]

        return Route(
            kind=kind,
            summarize=kind in {
                "system",
                "repository",
            },
        )

    prefixes = {
        "/remember ": "remember",
        "/forget ": "forget",
        "/files ": "files",
        "/read ": "read",
        "/shell ": "shell",
    }

    for prefix, kind in prefixes.items():
        if lowered.startswith(prefix):
            return Route(
                kind=kind,
                argument=stripped[len(prefix):].strip(),
                summarize=kind in {"files", "read"},
            )

    natural_patterns = [
        (
            r"\b(check|inspect|show|analy[sz]e)\b.*"
            r"\b(system|computer|machine|hardware)\b",
            "system",
        ),
        (
            r"\b(analy[sz]e|inspect|map|review|refactor)\b.*"
            r"(?:\b(repository|repo|codebase|source code)\b|src/)",
            "repository",
        ),
        (
            r"\b(git status|repository status|project tree|"
            r"dependency map|internal imports)\b",
            "repository",
        ),
        (
            r"\b(list|show)\b.*\bfiles\b",
            "files",
        ),
    ]

    for pattern, kind in natural_patterns:
        if re.search(pattern, lowered):
            return Route(
                kind=kind,
                summarize=True,
            )

    return Route(kind="chat")
