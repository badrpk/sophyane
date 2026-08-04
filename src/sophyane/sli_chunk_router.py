"""SLI-only routing through capability-graph composition."""
from __future__ import annotations

from pathlib import Path
from typing import Callable


Progress = Callable[[str], None]


def _normalise(message: str) -> str:
    return " ".join(str(message or "").lower().split())


def _is_preview(message: str) -> bool:
    text = _normalise(message)

    actions = (
        "open",
        "preview",
        "launch",
        "show",
        "view",
        "run",
        "test",
        "play",
    )

    targets = (
        "output",
        "result",
        "artifact",
        "browser",
        "page",
        "website",
        "html",
        "game",
        "it",
    )

    return (
        any(action in text for action in actions)
        and any(target in text for target in targets)
    )


def _is_build(message: str) -> bool:
    text = _normalise(message)

    return any(
        term in text
        for term in (
            "make",
            "create",
            "build",
            "generate",
            "develop",
            "implement",
            "write",
            "design",
            "fix",
            "modify",
            "update",
        )
    )


def _is_browser_build(message: str) -> bool:
    text = _normalise(message)

    return any(
        term in text
        for term in (
            "html",
            "browser",
            "web app",
            "website",
            "webpage",
            "frontend",
            "game",
            "dashboard",
            "quiz",
        )
    )


def try_sli_chunks(
    message: str,
    workspace: Path | None = None,
    progress: Progress | None = None,
) -> str:
    workspace = (
        workspace
        or Path.cwd() / ".sophyane-workspace"
    )
    progress = progress or (lambda _message: None)

    if _is_preview(message):
        from sophyane.sli_capability_engine import (
            preview_sli_artifact,
        )

        return preview_sli_artifact(
            workspace,
            progress=progress,
        )

    if not _is_build(message):
        return (
            "SLI-only mode handles code construction and artifact "
            "operations. This request is not a supported build or "
            "preview instruction. No LLM was used."
        )

    if _is_browser_build(message):
        from sophyane.code_memory.intelligent_compose import (
            compose_browser_request,
        )
        from sophyane.code_memory.store import ChunkStore

        report, _used = compose_browser_request(
            message,
            workspace,
            ChunkStore(),
            progress=progress,
        )

        return report

    # Only non-browser code uses the previous strict code-memory path.
    from sophyane.sli_capability_engine import (
        handle_sli_request,
    )

    return handle_sli_request(
        message,
        workspace=workspace,
        progress=progress,
    )


def resolve_tier(
    message: str,
    *,
    selected_mode: str = "sli_chunks",
    workspace: Path | None = None,
    progress: Progress | None = None,
    **_ignored,
) -> tuple[str, str | None]:
    if selected_mode == "sli_chunks":
        return (
            "sli_chunks",
            try_sli_chunks(
                message,
                workspace=workspace,
                progress=progress,
            ),
        )

    if selected_mode in {
        "local_llm",
        "cloud_llm",
    }:
        return selected_mode, None

    return "none", None

# SOPHYANE_PYTHON_HARNESS_ROUTE_V1
# Domain-first routing: explicit Python harness requests never enter the
# browser composer, preview path or generic semantic assembler.

_SLI_PRE_PYTHON_HARNESS_TRY = try_sli_chunks


def try_sli_chunks(
    message: str,
    workspace=None,
    progress=None,
):
    from pathlib import Path as _HarnessPath

    from sophyane.code_memory.python_harness_compose import (
        compose_python_harness_request,
        detect_python_harness_request,
    )

    if detect_python_harness_request(message):
        target = (
            _HarnessPath(workspace)
            if workspace is not None
            else _HarnessPath.cwd() / ".sophyane-workspace"
        )

        return compose_python_harness_request(
            message,
            target,
            progress=progress,
        )

    return _SLI_PRE_PYTHON_HARNESS_TRY(
        message,
        workspace=workspace,
        progress=progress,
    )

# SOPHYANE_INTERNET_ACQUIRE_ON_MISS_V1
# Unsupported or failed browser builds trigger bounded internet acquisition,
# chunk ingestion, reindexing, recomposition and validation.

_SLI_BEFORE_INTERNET_ACQUIRE = try_sli_chunks


def _sli_browser_build_request(message: str) -> bool:
    value = " ".join(
        str(message or "").lower().split()
    )

    build_terms = (
        "make",
        "create",
        "build",
        "develop",
        "generate",
        "implement",
        "design",
    )

    browser_terms = (
        "game",
        "browser",
        "html",
        "website",
        "web app",
        "webpage",
        "dashboard",
        "quiz",
        "calculator",
        "editor",
        "simulation",
        "visualizer",
    )

    return (
        any(term in value for term in build_terms)
        and any(term in value for term in browser_terms)
    )


def _sli_needs_internet_acquisition(
    report: str,
    workspace,
) -> bool:
    from pathlib import Path as _Path

    value = str(report or "").lower()
    artifact = _Path(workspace) / "index.html"

    failure_markers = (
        "family unavailable",
        "could not find compatible",
        "did not meet",
        "composition rejected",
        "no valid chunk",
        "recomposition failed",
        "success: false",
        "unsupported",
    )

    return (
        not artifact.is_file()
        or any(marker in value for marker in failure_markers)
    )


def try_sli_chunks(
    message: str,
    workspace=None,
    progress=None,
):
    from pathlib import Path as _Path

    target = (
        _Path(workspace)
        if workspace is not None
        else _Path.cwd() / ".sophyane-workspace"
    )

    result = _SLI_BEFORE_INTERNET_ACQUIRE(
        message,
        workspace=target,
        progress=progress,
    )

    if (
        _sli_browser_build_request(message)
        and _sli_needs_internet_acquisition(
            result,
            target,
        )
    ):
        from sophyane.code_memory.internet_acquire import (
            acquire_and_build,
        )

        return acquire_and_build(
            message,
            target,
            progress=progress,
        )

    return result

# SOPHYANE_GROUNDED_INTERNET_ROUTE_V2
# Browser-build failures trigger bounded repository acquisition.

_SLI_BEFORE_GROUNDED_INTERNET = try_sli_chunks


def _sli_is_browser_build(message: str) -> bool:
    text = " ".join(str(message or "").lower().split())

    return (
        any(
            term in text
            for term in (
                "make", "create", "build", "develop",
                "generate", "implement", "design",
            )
        )
        and any(
            term in text
            for term in (
                "browser", "html", "website", "webpage",
                "web app", "game", "dashboard", "editor",
                "calculator", "quiz", "simulation",
                "visualizer",
            )
        )
    )


def _sli_requires_acquisition(result, workspace) -> bool:
    from pathlib import Path as _Path

    text = str(result or "").lower()
    artifact = _Path(workspace) / "index.html"

    failure_markers = (
        "family unavailable",
        "could not find compatible",
        "composition rejected",
        "did not meet",
        "no valid",
        "unsupported",
        "success: false",
        "no compatible browser chunks",
    )

    return (
        not artifact.is_file()
        or any(marker in text for marker in failure_markers)
    )


def try_sli_chunks(
    message: str,
    workspace=None,
    progress=None,
):
    from pathlib import Path as _Path

    target = (
        _Path(workspace)
        if workspace is not None
        else _Path.cwd() / ".sophyane-workspace"
    )

    original = _SLI_BEFORE_GROUNDED_INTERNET(
        message,
        workspace=target,
        progress=progress,
    )

    if (
        _sli_is_browser_build(message)
        and _sli_requires_acquisition(original, target)
    ):
        from sophyane.code_memory.internet_acquire import (
            acquire_and_build,
        )

        return acquire_and_build(
            message,
            target,
            progress=progress,
        )

    return original
