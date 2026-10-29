"""Deterministic request classification for runtime UI decisions."""

from __future__ import annotations


_FILESYSTEM_INSPECTION_TERMS = (
    "largest file",
    "largest files",
    "biggest file",
    "biggest files",
    "top largest file",
    "top largest files",
    "smallest file",
    "smallest files",
    "latest file",
    "latest files",
    "newest file",
    "newest files",
    "oldest file",
    "oldest files",
    "file size",
    "folder size",
    "directory size",
    "count files",
    "count folders",
    "list files",
    "list folders",
    "show files",
    "show folders",
    "find file",
    "locate file",
    "filesystem",
    "file system",
    "disk usage",
    "memory usage",
    "process list",
    "port list",
    "most recently amended file",
    "most recently modified file",
    "latest modified file",
    "latest amended file",
    "last file i amended",
    "last file i modified",
    "last file i changed",
    "last file i edited",
)

_PROJECT_TERMS = (
    "build",
    "create",
    "make",
    "develop",
    "generate",
    "design",
    "implement",
    "code",
    "website",
    "web app",
    "webapp",
    "application",
    " app",
    "game",
    "dashboard",
    "landing page",
    "html",
    "frontend",
    "backend",
    "api",
    "project",
    "program",
    "software",
    "calculator",
    "snake",
    "chess",
    "tetris",
    "portfolio",
)

_CONTINUATION_TERMS = (
    "continue project",
    "same project",
    "update project",
    "improve project",
    "modify project",
    "edit project",
    "fix project",
    "open project",
    "run project",
    "restart project",
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

    return (
        any(term in text for term in _PROJECT_TERMS)
        or any(term in text for term in _CONTINUATION_TERMS)
    )
