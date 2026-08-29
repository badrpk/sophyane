"""Guarded execution for NIFDU browser-LLM filesystem proposals.

The browser LLM supplies intelligence only. Sophyane remains the sole
filesystem execution authority.

Accepted contract:

    WRITE_FILE
    path: relative/path.py
    content:
    <exact file content>
    END_WRITE_FILE

Only one relative file inside the supplied workspace may be written.
No shell returned by the LLM is executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


class NifduExecutionError(RuntimeError):
    """Rejected NIFDU execution proposal."""


@dataclass(frozen=True)
class FileWriteProposal:
    relative_path: str
    content: str


_HEADER = "WRITE_FILE"
_CONTENT = "content:"
_END = "END_WRITE_FILE"


def parse_file_write_proposal(
    response: str,
) -> FileWriteProposal:
    text = str(
        response
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).strip()

    lines = text.splitlines()

    if len(lines) < 4:
        raise NifduExecutionError(
            "NIFDU response is not a complete WRITE_FILE proposal"
        )

    if lines[0].strip() != _HEADER:
        raise NifduExecutionError(
            "NIFDU proposal must begin with WRITE_FILE"
        )

    path_line = lines[1].strip()

    if not path_line.startswith(
        "path:"
    ):
        raise NifduExecutionError(
            "NIFDU proposal is missing path:"
        )

    relative = path_line[
        len("path:"):
    ].strip()

    if not relative:
        raise NifduExecutionError(
            "NIFDU proposal path is empty"
        )

    if lines[2].strip() != _CONTENT:
        raise NifduExecutionError(
            "NIFDU proposal is missing content:"
        )

    if lines[-1].strip() != _END:
        raise NifduExecutionError(
            "NIFDU proposal must end with END_WRITE_FILE"
        )

    content = "\n".join(
        lines[3:-1]
    )

    # Preserve a normal text-file trailing newline.
    if content:
        content += "\n"

    return FileWriteProposal(
        relative_path=relative,
        content=content,
    )


def _resolve_target(
    workspace: Path,
    relative_path: str,
) -> Path:
    workspace = workspace.resolve()

    raw = Path(
        relative_path
    )

    if raw.is_absolute():
        raise NifduExecutionError(
            "absolute paths are forbidden"
        )

    if any(
        part in {
            "",
            ".",
            "..",
        }
        for part in raw.parts
    ):
        raise NifduExecutionError(
            "unsafe path component"
        )

    # Keep the first execution contract intentionally narrow.
    if len(raw.parts) != 1:
        raise NifduExecutionError(
            "nested paths are not allowed by this gate"
        )

    name = raw.name

    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+",
        name,
    ):
        raise NifduExecutionError(
            "unsafe filename"
        )

    if not name.endswith(
        ".py"
    ):
        raise NifduExecutionError(
            "this gate accepts Python files only"
        )

    target = (
        workspace
        / name
    ).resolve()

    try:
        target.relative_to(
            workspace
        )
    except ValueError as error:
        raise NifduExecutionError(
            "target escapes workspace"
        ) from error

    return target


def apply_file_write_proposal(
    response: str,
    *,
    workspace: Path,
    expected_filename: str | None = None,
) -> Path:
    proposal = parse_file_write_proposal(
        response
    )

    if (
        expected_filename
        and proposal.relative_path
        != expected_filename
    ):
        raise NifduExecutionError(
            "NIFDU proposed a different filename: "
            f"{proposal.relative_path!r}"
        )

    target = _resolve_target(
        workspace,
        proposal.relative_path,
    )

    # Fail closed instead of overwriting an unrelated existing file.
    if target.exists():
        raise NifduExecutionError(
            f"target already exists: {target.name}"
        )

    target.write_text(
        proposal.content,
        encoding="utf-8",
    )

    return target


# SOPHYANE_NIFDU_TUI_GUARDED_EXECUTION_V1

_FILE_REQUEST_RE = re.compile(
    r"""
    \b
    (?:
        create
        |
        make
        |
        write
    )
    \b
    .*?
    \b
    (?P<filename>[A-Za-z0-9_.-]+\.py)
    \b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def requested_python_filename(
    request: str,
) -> str | None:
    """Return one requested Python filename, or None."""

    match = _FILE_REQUEST_RE.search(
        str(
            request
            or ""
        )
    )

    if match is None:
        return None

    return match.group(
        "filename"
    )


def _nifdu_write_contract_prompt(
    request: str,
    *,
    filename: str,
) -> str:
    return (
        "You are the intelligence component for Sophyane's "
        "guarded filesystem executor.\n\n"
        "The user's authoritative request is:\n\n"
        + str(request).strip()
        + "\n\n"
        "Return exactly ONE proposed Python file write.\n"
        "Do not execute anything.\n"
        "Do not return shell commands.\n"
        "Do not use markdown fences.\n"
        "Do not add explanations.\n\n"
        "Required output contract:\n\n"
        "WRITE_FILE\n"
        f"path: {filename}\n"
        "content:\n"
        "<complete exact Python file contents>\n"
        "END_WRITE_FILE\n\n"
        "The path line MUST be exactly:\n"
        f"path: {filename}\n"
    )


def execute_nifdu_file_request(
    request: str,
    *,
    workspace: Path,
) -> Path | None:
    """Execute one guarded NIFDU Python-file request.

    Returns ``None`` when the request is not a supported one-file
    Python creation request.

    ChatGPT/NIFDU provides only the proposed file contents.
    Sophyane parses, validates and performs the filesystem write.
    """

    filename = requested_python_filename(
        request
    )

    if filename is None:
        return None

    from sophyane.providers.nifdu_browser import (
        NifduBrowserProvider,
    )

    provider = NifduBrowserProvider(
        timeout=180,
    )

    response = provider.generate(
        _nifdu_write_contract_prompt(
            request,
            filename=filename,
        )
    )

    return apply_file_write_proposal(
        response,
        workspace=Path(
            workspace
        ),
        expected_filename=filename,
    )



# SOPHYANE_NIFDU_EXPLICIT_FILE_READ_GROUNDING_V1

_EXPLICIT_PYTHON_READ_PATTERNS = (
    re.compile(
        r"""
        ^\s*
        (?:
            what\s+is
            |
            what['’]?s
            |
            show(?:\s+me)?
            |
            tell\s+me
        )
        \s+
        (?:
            the\s+
        )?
        (?:
            content
            |
            contents
        )
        \s+
        (?:
            of\s+
        )?
        (?P<filename>[A-Za-z0-9_.-]+\.py)
        \s*[?.!]?\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    re.compile(
        r"""
        ^\s*
        (?:
            read
            |
            cat
            |
            display
            |
            show
        )
        \s+
        (?P<filename>[A-Za-z0-9_.-]+\.py)
        \s*[?.!]?\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    re.compile(
        r"""
        ^\s*
        what
        \s+is
        \s+in
        \s+
        (?P<filename>[A-Za-z0-9_.-]+\.py)
        \s*[?.!]?\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    re.compile(
        r"""
        ^\s*
        (?:
            code\s+of
            |
            source\s+of
            |
            show\s+(?:me\s+)?(?:the\s+)?code\s+(?:of\s+)?
            |
            fetch\s+(?:the\s+)?code\s+(?:of\s+)?
        )
        \s*
        (?P<filename>[A-Za-z0-9_.-]+\.py)
        \s*[?.!]?\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
)


def requested_python_read_filename(
    request: str,
) -> str | None:
    """Return an explicitly requested local Python filename to read."""

    text = str(
        request
        or ""
    )

    for pattern in _EXPLICIT_PYTHON_READ_PATTERNS:
        match = pattern.fullmatch(
            text
        )

        if match is not None:
            return match.group(
                "filename"
            )

    return None


def grounded_nifdu_python_file_read(
    request: str,
    *,
    workspace: Path,
) -> str | None:
    """Answer an explicit local .py read directly from filesystem state.

    ``None`` means the request is not an explicit supported file-read
    request. A matched request never reaches NIFDU.
    """

    filename = requested_python_read_filename(
        request
    )

    if filename is None:
        return None

    workspace = Path(
        workspace
    ).resolve()

    target = _resolve_target(
        workspace,
        filename,
    )

    if not target.is_file():
        return (
            f"Local file {filename} does not exist "
            "in the active workspace."
        )

    try:
        size = target.stat().st_size
    except OSError as error:
        return (
            f"Could not inspect local file {filename}: "
            f"{error}"
        )

    if size > 1_000_000:
        return (
            f"Local file {filename} exceeds the "
            "1 MB safe read limit."
        )

    try:
        content = target.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return (
            f"Could not read local file {filename}: "
            f"{error}"
        )

    return (
        f"Grounded local file: {filename}\n\n"
        + content
    )


# SOPHYANE_NIFDU_UNGROUNDED_BROWSER_REFERENCE_V1

_UNGROUNDED_BROWSER_ACTION_RE = re.compile(
    r"""
    \b
    (?:
        play
        |
        run
        |
        execute
        |
        open
        |
        launch
        |
        start
    )
    \b
    .*?
    \b
    (?:
        this\s+code
        |
        that\s+code
        |
        the\s+code
        |
        it
    )
    \b
    .*?
    \b
    (?:
        browser
        |
        chrome
        |
        chromium
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def ungrounded_nifdu_browser_reference(
    request: str,
    *,
    workspace: Path,
) -> str | None:
    """Block deictic browser execution when no filename is grounded.

    Explicit .py browser requests are left to the existing fixed-argv
    launcher. This function never guesses a file from model prose or
    filesystem ordering.
    """

    del workspace

    text = str(
        request
        or ""
    )

    # Existing explicit-filename browser execution owns these requests.
    if requested_browser_python_file(
        text
    ) is not None:
        return None

    # Do not treat any explicitly named .py file as a pronoun-only request.
    if re.search(
        r"\b[A-Za-z0-9_.-]+\.py\b",
        text,
        flags=re.IGNORECASE,
    ):
        return None

    if _UNGROUNDED_BROWSER_ACTION_RE.search(
        text
    ) is None:
        return None

    return (
        "I cannot run that browser request because no grounded local file "
        "is identified. Name the Python filename explicitly, for example "
        "`run yaqeen.py in browser`."
    )





# SOPHYANE_NIFDU_LARGEST_FILE_GROUNDING_V1

_LARGEST_FILE_RE = re.compile(
    r"""
    \b(?:largest|biggest)\s+file\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def grounded_nifdu_largest_file(
    request: str,
    *,
    workspace: Path,
) -> str | None:
    import os

    if _LARGEST_FILE_RE.search(str(request or "")) is None:
        return None

    root = Path(workspace).expanduser().resolve()

    ignored = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "build",
        "dist",
    }

    largest = None
    largest_size = -1

    for current, directories, filenames in os.walk(
        root,
        onerror=lambda _error: None,
    ):
        directories[:] = [
            name
            for name in directories
            if name not in ignored
        ]

        current_path = Path(current)

        for filename in filenames:
            candidate = current_path / filename

            try:
                if not candidate.is_file():
                    continue
                size = candidate.stat().st_size
            except OSError:
                continue

            if size > largest_size:
                largest = candidate.resolve()
                largest_size = size

    if largest is None:
        return f"No accessible regular files were found under {root}."

    try:
        relative = largest.relative_to(root)
    except ValueError:
        relative = largest

    return (
        "Grounded largest file in the active Sophyane workspace:\n"
        f"Path: {largest}\n"
        f"Relative path: {relative}\n"
        f"Size: {largest_size} bytes"
    )



# SOPHYANE_NIFDU_FILE_DISCOVERY_GROUNDING_V1

_FILE_DISCOVERY_PATTERNS = (
    re.compile(
        r"""
        \b
        (?:
            is\s+there
            |
            find
            |
            locate
            |
            search
            |
            where\s+is
            |
            where['’]?s
        )
        \b
        .*?
        \b
        (?P<filename>[A-Za-z0-9_.-]+\.py)
        \b
        """,
        re.IGNORECASE | re.VERBOSE | re.DOTALL,
    ),
    re.compile(
        r"""
        \b
        (?:
            path
            |
            location
        )
        \b
        .*?
        \b
        (?P<filename>[A-Za-z0-9_.-]+\.py)
        \b
        """,
        re.IGNORECASE | re.VERBOSE | re.DOTALL,
    ),
)


def requested_python_discovery_filename(
    request: str,
) -> str | None:
    text = str(
        request
        or ""
    )

    for pattern in _FILE_DISCOVERY_PATTERNS:
        match = pattern.search(
            text
        )

        if match is not None:
            return match.group(
                "filename"
            )

    return None


def default_nifdu_file_search_roots() -> list[Path]:
    """Return accessible local roots without assuming all Android storage exists."""

    candidates = [
        Path.cwd(),
        Path.home(),
        Path("/storage/emulated/0"),
        Path("/sdcard"),
    ]

    roots = []

    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue

        if (
            resolved.is_dir()
            and resolved not in roots
        ):
            roots.append(
                resolved
            )

    return roots


_DISCOVERY_IGNORED_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".cache",
}


def _find_named_local_file(
    filename: str,
    *,
    roots,
) -> list[Path]:
    """Find exact basenames under explicitly supplied accessible roots."""

    import os

    matches: list[Path] = []
    seen: set[Path] = set()

    for root_value in roots:
        try:
            root = Path(
                root_value
            ).expanduser().resolve()
        except Exception:
            continue

        if not root.is_dir():
            continue

        for current, directories, files in os.walk(
            root,
            onerror=lambda _error: None,
        ):
            directories[:] = [
                name
                for name in directories
                if name not in _DISCOVERY_IGNORED_NAMES
            ]

            if filename not in files:
                continue

            candidate = (
                Path(current)
                / filename
            )

            try:
                resolved = candidate.resolve()
            except Exception:
                continue

            if (
                resolved.is_file()
                and resolved not in seen
            ):
                seen.add(
                    resolved
                )
                matches.append(
                    resolved
                )

    matches.sort(
        key=lambda item: str(item)
    )

    return matches


def grounded_nifdu_named_file_discovery(
    request: str,
    *,
    roots=None,
):
    """Ground exact filename existence/path questions in the filesystem."""

    filename = requested_python_discovery_filename(
        request
    )

    if filename is None:
        return None

    if roots is None:
        roots = default_nifdu_file_search_roots()

    paths = _find_named_local_file(
        filename,
        roots=roots,
    )

    if not paths:
        return {
            "handled": True,
            "filename": filename,
            "paths": [],
            "message": (
                f"No accessible file named {filename} was found "
                "in the local search roots."
            ),
        }

    if len(paths) == 1:
        message = (
            f"Found one grounded local file named {filename}:\n"
            f"{paths[0]}"
        )
    else:
        rendered = "\n".join(
            f"- {item}"
            for item in paths
        )

        message = (
            f"Found {len(paths)} grounded local files named "
            f"{filename}:\n{rendered}"
        )

    return {
        "handled": True,
        "filename": filename,
        "paths": paths,
        "message": message,
    }


def _read_grounded_python_path(
    target: Path,
) -> str:
    try:
        target = Path(
            target
        ).expanduser().resolve()
    except Exception as error:
        return (
            "Could not resolve the grounded local file: "
            f"{error}"
        )

    if not target.is_file():
        return (
            f"The grounded local file {target} no longer exists."
        )

    if target.suffix.lower() != ".py":
        return (
            f"The grounded local file {target.name} is not a Python file."
        )

    try:
        size = target.stat().st_size
    except OSError as error:
        return (
            f"Could not inspect local file {target.name}: {error}"
        )

    if size > 1_000_000:
        return (
            f"Local file {target.name} exceeds the 1 MB safe read limit."
        )

    try:
        content = target.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return (
            f"Could not read local file {target.name}: {error}"
        )

    return (
        f"Grounded local file: {target}\n\n"
        + content
    )


_FILE_FOLLOWUP_RE = re.compile(
    r"""
    ^\s*
    (?:
        what\s+is\s+(?:the\s+)?content\s+of\s+this\s+file
        |
        what\s+is\s+in\s+this\s+file
        |
        show\s+(?:me\s+)?(?:the\s+)?(?:code|content)
        |
        fetch\s+(?:the\s+)?(?:code|content)
        |
        read\s+(?:this|the)\s+file
        |
        dig\s+out\s+(?:the\s+)?(?:code|content)
        |
        code\s+of\s+this\s+file
    )
    \s*[?.!]?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


# SOPHYANE_NIFDU_MULTI_MATCH_FOLLOWUP_V1

def is_nifdu_file_followup_request(
    request: str,
) -> bool:
    """Recognize an explicit read of the previously grounded file."""

    return (
        _FILE_FOLLOWUP_RE.fullmatch(
            str(request or "")
        )
        is not None
    )


def grounded_nifdu_file_followup(
    request: str,
    *,
    active_file,
    candidate_paths=None,
) -> str | None:
    """Read the last runtime-grounded file or report ambiguity."""

    if not is_nifdu_file_followup_request(
        request
    ):
        return None

    candidates = []

    for value in (
        candidate_paths
        or []
    ):
        try:
            candidate = Path(
                value
            ).expanduser().resolve()
        except Exception:
            continue

        if (
            candidate.is_file()
            and candidate not in candidates
        ):
            candidates.append(
                candidate
            )

    if active_file is None:
        if len(candidates) > 1:
            rendered = "\n".join(
                f"- {candidate}"
                for candidate in candidates
            )

            return (
                "Multiple grounded files matched the previous request, "
                "so `this file` is ambiguous. Select one exact path:\n"
                + rendered
            )

        if len(candidates) == 1:
            active_file = candidates[0]

        else:
            return (
                "No grounded local file is currently selected. "
                "Search for or name the file explicitly first."
            )

    return _read_grounded_python_path(
        Path(active_file)
    )



# SOPHYANE_NIFDU_GUARDED_CONTINUATION_V1

_EDIT_HEADER = "REPLACE_FILE"
_EDIT_END = "END_REPLACE_FILE"


def _normalise_active_python_file(
    value,
    *,
    workspace: Path,
) -> Path | None:
    """Return a safe active Python file inside workspace."""

    if value is None:
        return None

    workspace = Path(
        workspace
    ).resolve()

    raw = Path(
        str(value)
    )

    if not raw.is_absolute():
        raw = (
            workspace
            / raw
        )

    try:
        target = raw.resolve()
    except Exception:
        return None

    try:
        target.relative_to(
            workspace
        )
    except ValueError:
        return None

    if (
        target.suffix.lower()
        != ".py"
    ):
        return None

    return target


def parse_file_replace_proposal(
    response: str,
) -> FileWriteProposal:
    """Parse one full-file replacement proposal."""

    text = str(
        response
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).strip()

    lines = text.splitlines()

    if len(lines) < 4:
        raise NifduExecutionError(
            "NIFDU response is not a complete REPLACE_FILE proposal"
        )

    if lines[0].strip() != _EDIT_HEADER:
        raise NifduExecutionError(
            "NIFDU proposal must begin with REPLACE_FILE"
        )

    path_line = lines[1].strip()

    if not path_line.startswith(
        "path:"
    ):
        raise NifduExecutionError(
            "NIFDU replacement is missing path:"
        )

    relative = path_line[
        len("path:"):
    ].strip()

    if not relative:
        raise NifduExecutionError(
            "NIFDU replacement path is empty"
        )

    if lines[2].strip() != _CONTENT:
        raise NifduExecutionError(
            "NIFDU replacement is missing content:"
        )

    if lines[-1].strip() != _EDIT_END:
        raise NifduExecutionError(
            "NIFDU replacement must end with END_REPLACE_FILE"
        )

    content = "\n".join(
        lines[3:-1]
    )

    if content:
        content += "\n"

    return FileWriteProposal(
        relative_path=relative,
        content=content,
    )


def apply_file_replace_proposal(
    response: str,
    *,
    workspace: Path,
    expected_filename: str,
) -> Path:
    """Replace exactly one existing Python file inside workspace."""

    proposal = parse_file_replace_proposal(
        response
    )

    if (
        proposal.relative_path
        != expected_filename
    ):
        raise NifduExecutionError(
            "NIFDU proposed replacement of a different file: "
            f"{proposal.relative_path!r}"
        )

    target = _resolve_target(
        workspace,
        proposal.relative_path,
    )

    if not target.is_file():
        raise NifduExecutionError(
            f"target does not exist: {target.name}"
        )

    target.write_text(
        proposal.content,
        encoding="utf-8",
    )

    return target


def _nifdu_replace_contract_prompt(
    request: str,
    *,
    target: Path,
) -> str:
    current = target.read_text(
        encoding="utf-8",
    )

    return (
        "You are the intelligence component for Sophyane's "
        "guarded filesystem editor.\n\n"
        "The user's authoritative continuation request is:\n\n"
        + str(request).strip()
        + "\n\n"
        "The active Python file is:\n"
        + target.name
        + "\n\n"
        "Its current complete contents are:\n\n"
        "----- CURRENT FILE -----\n"
        + current
        + (
            ""
            if current.endswith("\n")
            else "\n"
        )
        + "----- END CURRENT FILE -----\n\n"
        "Return the complete replacement contents for that SAME file.\n"
        "Do not execute anything.\n"
        "Do not return shell commands.\n"
        "Do not use markdown fences.\n"
        "Do not add explanations.\n\n"
        "Required output contract:\n\n"
        "REPLACE_FILE\n"
        f"path: {target.name}\n"
        "content:\n"
        "<complete replacement Python file contents>\n"
        "END_REPLACE_FILE\n"
    )


def is_nifdu_file_continuation_request(
    request: str,
    *,
    active_file,
    workspace: Path,
) -> bool:
    """Recognize a continuation aimed at the active Python file."""

    target = _normalise_active_python_file(
        active_file,
        workspace=workspace,
    )

    if target is None:
        return False

    text = " ".join(
        str(
            request
            or ""
        ).casefold().split()
    )

    if not text:
        return False

    explicit_name = (
        target.name.casefold()
        in text
    )

    continuation_words = (
        " it",
        "in it",
        "into it",
        "this file",
        "the file",
        "same file",
        "add ",
        "change ",
        "modify ",
        "update ",
        "code ",
        "make ",
        "build ",
        "put ",
        "write ",
        "background",
        "game",
        "snake",
        "run ",
        "open ",
    )

    return (
        explicit_name
        or any(
            token in text
            for token in continuation_words
        )
    )


def execute_nifdu_file_continuation(
    request: str,
    *,
    workspace: Path,
    active_file,
) -> Path | None:
    """Safely edit the remembered active Python file."""

    workspace = Path(
        workspace
    ).resolve()

    target = _normalise_active_python_file(
        active_file,
        workspace=workspace,
    )

    if target is None:
        return None

    if not target.is_file():
        return None

    if not is_nifdu_file_continuation_request(
        request,
        active_file=target,
        workspace=workspace,
    ):
        return None

    from sophyane.providers.nifdu_browser import (
        NifduBrowserProvider,
    )

    provider = NifduBrowserProvider(
        timeout=180,
    )

    response = provider.generate(
        _nifdu_replace_contract_prompt(
            request,
            target=target,
        )
    )

    return apply_file_replace_proposal(
        response,
        workspace=workspace,
        expected_filename=target.name,
    )


# SOPHYANE_NIFDU_DETERMINISTIC_EMPTY_CREATE_V1

_EMPTY_CREATE_RE = re.compile(
    r"""
    ^\s*
    (?:
        create
        |
        make
        |
        write
    )
    \s+
    (?:
        exactly\s+one\s+
    )?
    (?:
        a\s+
    )?
    (?:
        python\s+
    )?
    file
    (?:
        \s+named
    )?
    \s+
    (?P<filename>[A-Za-z0-9_.-]+\.py)
    \s*
    [.!]?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def deterministic_empty_python_create(
    request: str,
    *,
    workspace: Path,
) -> Path | None:
    """Create an explicitly requested empty Python file without LLM use.

    This handles only the narrow form where the user asks to create/make
    one .py file and supplies no content or coding instruction.
    """

    match = _EMPTY_CREATE_RE.fullmatch(
        str(
            request
            or ""
        )
    )

    if match is None:
        return None

    filename = match.group(
        "filename"
    )

    target = _resolve_target(
        Path(workspace),
        filename,
    )

    if target.exists():
        raise NifduExecutionError(
            f"target already exists: {target.name}"
        )

    target.write_text(
        "",
        encoding="utf-8",
    )

    return target


# SOPHYANE_NIFDU_GUARDED_BROWSER_LAUNCH_V1

import ast
import subprocess
import sys
import time
from urllib.request import urlopen


_RUN_BROWSER_RE = re.compile(
    r"""
    \b
    (?:
        run
        |
        execute
        |
        open
        |
        launch
        |
        start
    )
    \b
    .*?
    (?P<filename>[A-Za-z0-9_.-]+\.py)
    .*?
    \b
    (?:
        browser
        |
        chrome
        |
        chromium
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def requested_browser_python_file(
    request: str,
) -> str | None:
    match = _RUN_BROWSER_RE.search(
        str(request or "")
    )

    if match is None:
        return None

    return match.group(
        "filename"
    )


def validate_python_file(
    target: Path,
) -> None:
    """Fail closed unless the Python source parses."""

    source = target.read_text(
        encoding="utf-8",
    )

    try:
        ast.parse(
            source,
            filename=str(target),
        )

    except SyntaxError as error:
        raise NifduExecutionError(
            "Python validation failed before execution: "
            f"{error.msg} at line {error.lineno}"
        ) from error


def launch_guarded_browser_python(
    request: str,
    *,
    workspace: Path,
) -> tuple[Path, int] | None:
    """Launch one validated Python file from the current workspace.

    This path executes only the named .py file directly with the
    current Sophyane Python interpreter. It never executes LLM shell
    text and never enables shell=True.
    """

    filename = requested_browser_python_file(
        request
    )

    if filename is None:
        return None

    target = _resolve_target(
        Path(workspace),
        filename,
    )

    if not target.is_file():
        raise NifduExecutionError(
            f"requested Python file does not exist: {filename}"
        )

    validate_python_file(
        target
    )

    process = subprocess.Popen(
        [
            sys.executable,
            str(target),
        ],
        cwd=str(
            Path(workspace).resolve()
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Fail closed if the process crashes immediately.
    time.sleep(1.0)

    return_code = process.poll()

    if return_code is not None:
        raise NifduExecutionError(
            "Python browser launcher exited immediately "
            f"with status {return_code}"
        )

    return target, process.pid
