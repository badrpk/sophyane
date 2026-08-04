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

# SOPHYANE_TOPIC_SITE_ROUTE_V1
# Informational website requests use public topic retrieval rather than
# searching for a pre-existing runnable website repository.

_try_sli_before_topic_site = try_sli_chunks


def try_sli_chunks(
    message: str,
    workspace=None,
    progress=None,
):
    from pathlib import Path as _Path

    from sophyane.code_memory.topic_site_compose import (
        compose_topic_site,
        is_topic_site_request,
    )

    target = (
        _Path(workspace)
        if workspace is not None
        else _Path.cwd()
        / ".sophyane-workspace"
    )

    if is_topic_site_request(message):
        return compose_topic_site(
            message,
            target,
            progress=progress,
        )

    return _try_sli_before_topic_site(
        message,
        workspace=target,
        progress=progress,
    )

# SOPHYANE_PYTHON_FIRST_ROUTE_V6
def _sli_is_python_file_request(message: str) -> bool:
    t = (message or "").lower()
    keys = (
        "exactly one python file",
        "one python file",
        "python file named",
        "implementing a deterministic",
        "feature-flag",
        "feature flag",
        "dependency scheduler",
        "policy_engine",
        "decide_route",
        ".py",
        "fastapi",
        "flask app",
    )
    if any(k in t for k in keys):
        return True
    if "python" in t and any(k in t for k in ("implement", "create", "file", "module", "function")):
        if "index.html" not in t and "canvas" not in t:
            return True
    return False

_sli_try_before_python_first = try_sli_chunks

def try_sli_chunks(message: str, workspace=None, progress=None):
    progress = progress or (lambda _m: None)
    if _sli_is_python_file_request(message):
        try:
            from sophyane.code_memory.python_harness_compose import (
                compose_python_harness_request,
                detect_python_harness_request,
            )
            if detect_python_harness_request(message) or _sli_is_python_file_request(message):
                progress("SLI route: python harness (curriculum/python-first)")
                return compose_python_harness_request(
                    message, workspace=workspace, progress=progress
                )
        except Exception as e:
            progress(f"SLI python-first route error: {e}")
            return (
                "SLI python harness failed.\n"
                f"Error: {e}\n"
                "No LLM fallback was used."
            )
    return _sli_try_before_python_first(message, workspace=workspace, progress=progress)


# SOPHYANE_LANGUAGE_LINKER_FIRST_V8
def _sli_is_language_exercise_request(message: str) -> bool:
    t = (message or "").lower()
    keys = (
        "missing word", "missing letter", "cloze", "spelling",
        "vocabulary", "quiz", "language exercise", "sentence game",
        "word game", "fill in the blank", "fill-in-the-blank",
    )
    if any(k in t for k in keys):
        return True
    if "learning game" in t and any(k in t for k in ("word", "letter", "spell", "sentence")):
        return True
    return False

_sli_try_before_language_v8 = try_sli_chunks

def try_sli_chunks(message: str, workspace=None, progress=None):
    progress = progress or (lambda _m: None)
    if _sli_is_language_exercise_request(message):
        progress("SLI route: language component-linker first")
        try:
            from sophyane.code_memory.intelligent_compose import compose_browser_request
            from sophyane.code_memory.store import ChunkStore
            from pathlib import Path as _P
            ws = workspace if workspace is not None else _P.cwd() / ".sophyane-workspace"
            ws = _P(ws)
            ws.mkdir(parents=True, exist_ok=True)
            store = ChunkStore()
            report, used = compose_browser_request(
                message, ws, store, progress=progress,
            )
            if report and used and "Success: True" in str(report):
                return report
            if report and (ws / "index.html").exists():
                # accept if linker produced html with exercise markers
                html = (ws / "index.html").read_text(encoding="utf-8", errors="ignore")
                low = html.lower()
                if any(x in low for x in ("startexerciseapp", "sli_exercise", "validateanswer", "missing")):
                    return report
            progress("SLI language linker miss; falling through to internet acquire")
        except Exception as e:
            progress(f"SLI language linker error: {e}; falling through")
    return _sli_try_before_language_v8(message, workspace=workspace, progress=progress)

# SOPHYANE_FLYWHEEL_ROUTER_V1
# Note: cascade is handled in sli_cascade / TUI; router stays pure SLI.

_sli_try_chunks_before_graph = try_sli_chunks


# SOPHYANE_SLI_GRAPH_ENTRY_V3
import os as _sli_g_os

def try_sli_chunks(message: str, workspace=None, progress=None):
    progress = progress or (lambda _m: None)
    use = _sli_g_os.environ.get("SOPHYANE_SLI_GRAPH", "1").strip().lower() not in {
        "0", "false", "no",
    }
    if use:
        try:
            from sophyane.sli_graph import run_sli_graph
            state = run_sli_graph(message, workspace=workspace, progress=progress)
            if state.success and state.report:
                return state.report
            prev = _sli_g_os.environ.get("SOPHYANE_SLI_GRAPH")
            _sli_g_os.environ["SOPHYANE_SLI_GRAPH"] = "0"
            try:
                legacy = _sli_try_chunks_before_graph(
                    message, workspace=workspace, progress=progress
                )
            finally:
                if prev is None:
                    _sli_g_os.environ.pop("SOPHYANE_SLI_GRAPH", None)
                else:
                    _sli_g_os.environ["SOPHYANE_SLI_GRAPH"] = prev
            if legacy and "Success: True" in str(legacy):
                return legacy
            return state.report or legacy
        except Exception as e:
            progress(f"SLI-graph entry error: {e}")
    return _sli_try_chunks_before_graph(message, workspace=workspace, progress=progress)
