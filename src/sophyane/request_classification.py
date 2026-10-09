"""Deterministic request classification for authority and runtime UI decisions."""

from __future__ import annotations

from enum import Enum
import re


class RepositoryCapability(str, Enum):
    READ_ONLY = "read_only"
    MUTATION = "mutation"
    AMBIGUOUS = "ambiguous"


def classify_repository_capability(request: str) -> RepositoryCapability:
    """Classify original repository intent, with affirmative mutation first."""
    text = normalize_request_text(request)
    mutation = (
        r"\b(?:fix|patch|modify|edit|update|implement|rewrite|refactor|replace|"
        r"change|create|make|write|append|add|remove|delete|rename|move|"
        r"changing|modifying|editing|writing|creating|deleting)\b"
    )
    affirmative = re.sub(
        r"\b(?:do not|don't|never|without)\s+" + mutation,
        "",
        text,
    )
    # SOPHYANE_READ_ONLY_AUDIT_AUTHORITY_V1
    #
    # An audit describing existing implementation is not authorization
    # to change source. Keep explicit mutation instructions authoritative.
    audit_request = bool(
        re.match(
            r"(?:please\s+)?(?:audit|check|review|assess|evaluate|verify|"
            r"inspect|examine)\b",
            text,
        )
    )

    affirmative_mutation = bool(
        re.search(
            r"\b(?:fix|patch|modify|edit|update|implement|rewrite|refactor|"
            r"replace|change|create|make|write|append|add|remove|delete|"
            r"rename|move)\b",
            affirmative,
        )
    )

    # Questions about whether an implementation should be undertaken
    # do not themselves authorize implementation. This exception is
    # limited to audit-oriented requests without an independent edit command.
    # Exclude advisory "whether ... should implement" wording from
    # mutation detection, but retain independent mutation commands.
    advisory_stripped = re.sub(
        r"\bwhether\b[^.!?;]*?\bshould\s+implement\b",
        "whether implementation is advisable",
        affirmative,
    )
    remaining_mutation = bool(
        re.search(mutation, advisory_stripped)
    )

    if audit_request and not remaining_mutation:
        return RepositoryCapability.READ_ONLY


    if re.search(mutation, affirmative):
        return RepositoryCapability.MUTATION
    if re.search(
        r"\bread[- ]only\b|\b(?:do not|don't|never) (?:edit|modify|change|write)\b"
        r"|\bwithout (?:changing|modifying|editing) (?:it|anything|any files)\b",
        text,
    ):
        return RepositoryCapability.READ_ONLY
    if re.match(r"(?:please )?(?:inspect|read|explain|show|list)\b", text):
        return RepositoryCapability.READ_ONLY
    return RepositoryCapability.AMBIGUOUS


_FILESYSTEM_INSPECTION_TERMS = (
    "largest file", "largest files", "biggest file", "biggest files",
    "top largest file", "top largest files", "smallest file", "smallest files",
    "latest file", "latest files", "newest file", "newest files",
    "oldest file", "oldest files", "file size", "folder size",
    "directory size", "count files", "count folders", "list files",
    "list folders", "show files", "show folders", "find file", "locate file",
    "filesystem", "file system", "disk usage", "memory usage", "process list",
    "port list", "most recently amended file", "most recently modified file",
    "latest modified file", "latest amended file", "last file i amended",
    "last file i modified", "last file i changed", "last file i edited",
)

_PROJECT_TERMS = (
    "build", "create", "make", "develop", "generate", "design", "implement", "code", "website",
    "web app", "webapp", "application", " app", "game", "dashboard", "landing page", "html",
    "frontend", "backend", "api", "project", "program", "software", "calculator", "snake",
    "chess", "tetris", "portfolio",
)

_CONTINUATION_TERMS = (
    "continue project", "same project", "update project", "improve project", "modify project",
    "edit project", "fix project", "open project", "run project", "restart project",
)


def normalize_request_text(request: str) -> str:
    return " ".join(str(request or "").lower().split())


def is_read_only_filesystem_request(request: str) -> bool:
    text = normalize_request_text(request)
    return any(term in text for term in _FILESYSTEM_INSPECTION_TERMS)


def requires_post_build_menu(request: str) -> bool:
    text = normalize_request_text(request)
    if is_read_only_filesystem_request(text):
        return False
    return any(term in text for term in _PROJECT_TERMS) or any(term in text for term in _CONTINUATION_TERMS)
