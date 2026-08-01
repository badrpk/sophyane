"""Extract safe project files from provider Markdown responses.

Supported forms include:

    ### `app/main.py`
    ```python
    ...
    ```

    ### Dockerfile
    ```dockerfile
    ...
    ```

    **File: `.github/workflows/ci.yml`**
    ```yaml
    ...
    ```
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileArtifact:
    path: str
    content: str
    language: str
    source: str


_FENCE = re.compile(
    r"(?ms)^```(?P<language>[A-Za-z0-9_+.-]*)[ \t]*\n"
    r"(?P<content>.*?)"
    r"^```[ \t]*$"
)

_BACKTICK_PATH = re.compile(r"`([^`\r\n]+)`")

_FILE_LABEL = re.compile(
    r"(?i)\b(?:file|filename|path)\s*:\s*"
    r"(?:`(?P<quoted>[^`]+)`|(?P<plain>[^\s,;]+))"
)

_PATH_TOKEN = re.compile(
    r"(?P<path>"
    r"(?:\.[A-Za-z0-9_.-]+|"
    r"(?:[A-Za-z0-9_.-]+/)*"
    r"[A-Za-z0-9_.-]+"
    r"(?:\.[A-Za-z0-9_.-]+)?)"
    r")"
)

_SPECIAL_NAMES = {
    "Dockerfile",
    "Containerfile",
    "Makefile",
    "Procfile",
    "README",
    "README.md",
    "README.rst",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    ".gitignore",
    ".dockerignore",
    ".env.example",
    "compose.yml",
    "compose.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
}

_ALLOWED_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".yaml",
    ".yml",
    ".xml",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".md",
    ".rst",
    ".txt",
    ".csv",
    ".env",
    ".dockerfile",
    ".cpp",
    ".cc",
    ".c",
    ".h",
    ".hpp",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".gradle",
}

_REJECTED_PATH_WORDS = {
    "python",
    "json",
    "yaml",
    "yml",
    "bash",
    "shell",
    "text",
    "plaintext",
    "markdown",
    "javascript",
    "typescript",
    "dockerfile",
    "structure",
    "output",
    "example",
    "implementation",
    "code",
}


def _safe_path(value: str) -> str | None:
    candidate = str(value or "").strip()
    candidate = candidate.strip("`'\"()[]{}<>:;,")
    candidate = candidate.replace("\\", "/")

    while candidate.startswith("./"):
        candidate = candidate[2:]

    if not candidate:
        return None

    if candidate.casefold() in _REJECTED_PATH_WORDS:
        return None

    # Paths extracted from prose headings must look like actual project paths,
    # not commands or numbered documentation labels.
    if any(char.isspace() for char in candidate):
        return None

    lowered = candidate.casefold()

    if lowered.startswith(
        (
            "pip ",
            "python ",
            "pytest ",
            "docker ",
            "uvicorn ",
            "npm ",
            "git ",
        )
    ):
        return None

    if re.match(r"^[ivxlcdm]+[.)_-]", lowered):
        return None

    path = Path(candidate)

    if path.is_absolute():
        return None

    if any(part in {"", ".", ".."} for part in path.parts):
        return None

    if candidate.startswith("~"):
        return None

    if ":" in candidate:
        return None

    name = path.name

    if name in _SPECIAL_NAMES:
        return candidate

    if "/" in candidate:
        suffix = path.suffix.casefold()

        if suffix in _ALLOWED_SUFFIXES:
            return candidate

        # Extensionless files inside known project directories are allowed.
        if path.parts[0] in {
            "bin",
            "scripts",
            "config",
            "templates",
            "static",
        }:
            return candidate

        return None

    if path.suffix.casefold() in _ALLOWED_SUFFIXES:
        return candidate

    return None


def _heading_context(text: str, fence_start: int, previous_end: int) -> str:
    context = text[previous_end:fence_start]
    lines = [
        line.strip()
        for line in context.splitlines()
        if line.strip()
    ]
    return "\n".join(lines[-8:])


def _path_from_context(context: str) -> str | None:
    labelled = list(_FILE_LABEL.finditer(context))

    for match in reversed(labelled):
        candidate = match.group("quoted") or match.group("plain")
        safe = _safe_path(candidate)
        if safe:
            return safe

    backticks = _BACKTICK_PATH.findall(context)

    for candidate in reversed(backticks):
        safe = _safe_path(candidate)
        if safe:
            return safe

    lines = context.splitlines()

    for raw_line in reversed(lines):
        line = raw_line.strip()
        line = re.sub(r"^[#>*+\-\s]+", "", line)
        line = re.sub(r"^\d+(?:\.\d+)*[.)\-:\s]+", "", line)
        line = re.sub(
            r"(?i)^(?:file|filename|path)\s*:\s*",
            "",
            line,
        )
        line = line.strip("*_`'\"()[]{}<>:;,")

        direct = _safe_path(line)
        if direct:
            return direct

        tokens = [
            match.group("path")
            for match in _PATH_TOKEN.finditer(line)
        ]

        for token in reversed(tokens):
            safe = _safe_path(token)
            if safe:
                return safe

    return None


def extract_files(text: str) -> list[FileArtifact]:
    raw = str(text or "")

    if not raw.strip():
        return []

    found: dict[str, FileArtifact] = {}
    previous_end = 0

    for index, match in enumerate(_FENCE.finditer(raw), start=1):
        language = (match.group("language") or "").strip().casefold()
        content = match.group("content")
        context = _heading_context(
            raw,
            match.start(),
            previous_end,
        )
        previous_end = match.end()

        path = _path_from_context(context)

        if path is None:
            continue

        if not content.strip():
            continue

        artifact = FileArtifact(
            path=path,
            content=content.rstrip() + "\n",
            language=language,
            source=f"markdown.fence[{index}]",
        )

        existing = found.get(path)

        # Prefer the fuller copy when providers repeat the same file.
        if existing is None or len(artifact.content) > len(existing.content):
            found[path] = artifact

    return list(found.values())


def as_batch_action(text: str) -> dict[str, Any] | None:
    files = extract_files(text)

    if not files:
        return None

    return {
        "type": "batch",
        "artifact_source": "markdown_multifile_bundle",
        "actions": [
            {
                "type": "write_file",
                "path": artifact.path,
                "content": artifact.content,
                "replace": True,
                "artifact_source": artifact.source,
            }
            for artifact in files
        ],
    }


__all__ = [
    "FileArtifact",
    "as_batch_action",
    "extract_files",
]
