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
