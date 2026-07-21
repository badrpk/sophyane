"""Install provider-neutral artifact extraction around the active execution loop."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sophyane.artifact_extractor import (
    Artifact,
    continuation_prompt,
    extract_artifact,
    merge_continuation,
)


def _as_write_action(artifact: Artifact) -> str:
    return json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": artifact.path or "index.html",
                "content": artifact.content,
                "replace": True,
                "artifact_source": artifact.source,
            }
        },
        ensure_ascii=False,
    )


def _text(response: Any) -> str:
    return str(getattr(response, "text", response))


def install_artifact_patch() -> None:
    from sophyane import execution_runtime as runtime

    if getattr(runtime, "_artifact_patch_installed", False):
        return

    original_loop = runtime.run_structured_loop

    def run_structured_loop(
        *,
        initial_text: str,
        original_request: str,
        ask: Any,
        workspace: Path | None = None,
        max_steps: int = 12,
        progress: Any = None,
    ) -> str:
        emit = progress or (lambda _message: None)

        def normalize(raw: str) -> str:
            artifact = extract_artifact(raw)
            if artifact is None:
                return raw
            emit(
                f"Artifact detected: HTML from {artifact.source}; "
                f"{'complete' if artifact.complete else 'truncated'} ({len(artifact.content)} characters)"
            )
            attempts = 0
            while not artifact.complete and attempts < 3:
                attempts += 1
                emit(f"Continuing truncated HTML with current provider ({attempts}/3)")
                response = ask(continuation_prompt(artifact, original_request))
                combined = merge_continuation(artifact.content, _text(response))
                artifact = Artifact(
                    content=combined,
                    source=f"{artifact.source}+continuation{attempts}",
                    complete=combined.strip().lower().endswith("</html>"),
                    path=artifact.path,
                )
            if not artifact.complete:
                emit("HTML continuation remained incomplete; preserving it for bounded validator recovery")
            return _as_write_action(artifact)

        def normalized_ask(prompt: str) -> Any:
            return normalize(_text(ask(prompt)))

        return original_loop(
            initial_text=normalize(str(initial_text or "")),
            original_request=original_request,
            ask=normalized_ask,
            workspace=workspace,
            max_steps=max_steps,
            progress=progress,
        )

    runtime.run_structured_loop = run_structured_loop
    runtime._artifact_patch_installed = True
