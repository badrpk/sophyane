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


def _structured_artifact_action(raw: str) -> str | None:
    """Translate provider artifact actions into the executor's write_file schema."""
    try:
        plan = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(plan, dict):
        return None

    candidates: list[Any] = [plan.get("action"), plan.get("selected_action"), plan.get("next_action")]
    plan_candidates = plan.get("candidates")
    if isinstance(plan_candidates, list) and plan_candidates:
        try:
            selected = plan_candidates[int(plan.get("selected_index", 0))]
        except (IndexError, TypeError, ValueError):
            selected = plan_candidates[0]
        candidates.append(selected)

    for value in candidates:
        if not isinstance(value, dict):
            continue
        nested = value.get("action") if isinstance(value.get("action"), dict) else value
        kind = str(nested.get("type") or nested.get("kind") or "").strip().lower()
        if kind not in {"artifact", "file_artifact", "html_artifact"}:
            continue
        path = str(
            nested.get("path")
            or nested.get("file")
            or nested.get("file_path")
            or nested.get("filename")
            or nested.get("artifact_path")
            or "index.html"
        ).strip()
        content = nested.get("content")
        if content is None:
            content = nested.get("text")
        if not isinstance(content, str) or not content:
            continue
        return json.dumps(
            {
                "action": {
                    "type": "write_file",
                    "path": path or "index.html",
                    "content": content,
                    "replace": True,
                    "artifact_source": "structured_artifact_action",
                }
            },
            ensure_ascii=False,
        )
    return None


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
            structured = _structured_artifact_action(raw)
            if structured is not None:
                emit("Structured artifact action normalized to write_file")
                return structured
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
