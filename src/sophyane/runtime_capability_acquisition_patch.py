"""Runtime integration for user-visible recursive capability acquisition."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _capability_workspace(tui: Any, request: str) -> Path:
    existing = getattr(tui, "_active_canvas_workspace", None)

    if existing:
        return Path(existing).expanduser().resolve()

    base = Path.home() / ".sophyane" / "workspaces"
    base.mkdir(parents=True, exist_ok=True)

    workspace = base / "editable-capability-session"
    workspace.mkdir(parents=True, exist_ok=True)
    tui._active_canvas_workspace = str(workspace)
    return workspace


def _active_canvas_session(
    tui: Any,
    workspace: Path | str | None = None,
) -> Any:
    """Return the live CanvasSession owned by this TUI mission."""

    from sophyane.editable_canvas import CanvasSession

    current = getattr(
        tui,
        "_active_canvas_session",
        None,
    )

    if workspace is None:
        workspace = getattr(
            tui,
            "_active_canvas_workspace",
            None,
        )

    if current is not None:
        if workspace is None:
            return current

        expected = Path(workspace).expanduser().resolve()

        if current.workspace == expected:
            return current

    if not workspace:
        raise RuntimeError(
            "No active editable workspace is registered."
        )

    resolved = Path(workspace).expanduser().resolve()
    session = CanvasSession.open(resolved)

    tui._active_canvas_workspace = str(resolved)
    tui._active_canvas_session = session
    return session


def _format_result(result: Any) -> str:
    lines = [
        result.message,
        "",
        "Capability acquisition evidence:",
    ]

    for stage in result.stages:
        status = "PASS" if stage.success else "FAIL"
        lines.append(f"- [{status}] {stage.name}")

        for evidence in stage.evidence:
            lines.append(f"  - {evidence}")

    payload = result.payload or {}

    if payload:
        lines.extend(
            [
                "",
                f"Workspace: {payload.get('workspace', '')}",
                f"Document: {payload.get('document_id', '')}",
                f"Scene: {payload.get('scene_file', '')}",
                f"Preview: {payload.get('preview_file', '')}",
                f"Revision: {payload.get('revision', '')}",
            ]
        )

    return "\n".join(lines)


def install_capability_acquisition_patch() -> None:
    from sophyane import tui_v2
    from sophyane.capability_gap import (
        detect_capability_gap,
        improve_until_satisfied,
    )

    if getattr(
        tui_v2,
        "_capability_acquisition_patch_installed",
        False,
    ):
        return

    original_call_provider = tui_v2.ObservableTUI.call_provider

    def call_provider(
        self: Any,
        message: str,
        *,
        timeout: int = 60,
    ) -> Any:
        gap = detect_capability_gap(message)

        if gap is not None:
            self.progress(
                "Current runtime cannot yet satisfy all acceptance "
                "criteria; checking whether Sophyane can acquire the "
                "missing capability."
            )

            workspace = _capability_workspace(
                self,
                message,
            )

            result = improve_until_satisfied(
                gap,
                workspace=workspace,
                progress=self.progress,
                max_stages=6,
            )

            if result.success:
                self.progress(
                    "Capability upgrade validated; resuming the "
                    "original request against the upgraded runtime."
                )

                # Retain the same session object throughout this
                # mission so undo and redo history remain available.
                self._active_canvas_session = _active_canvas_session(
                    self,
                    result.payload.get("workspace") or workspace,
                )

                return _format_result(result)

            self.progress(
                "Bounded capability acquisition did not satisfy the "
                "request; falling back to the normal provider route."
            )

        active_workspace = getattr(
            self,
            "_active_canvas_workspace",
            None,
        )

        if active_workspace:
            session = _active_canvas_session(
                self,
                active_workspace,
            )
            text = " ".join(message.lower().split())

            edit_terms = (
                "jinnah",
                "attire",
                "clothes",
                "clothing",
                "sherwani",
                "chair",
                "background",
                "move",
                "left",
                "right",
                "larger",
                "bigger",
                "smaller",
                "sitting",
                "seated",
            )

            if text in {"/undo", "undo"}:
                session.undo()
                self.progress(
                    "Applied undo to the active editable session."
                )
                return (
                    "Undo applied.\n\n"
                    f"Workspace: {session.workspace}\n"
                    f"Preview: {session.preview_path}\n"
                    f"Revision: {session.scene.get('revision', 0)}"
                )

            if text in {"/redo", "redo"}:
                session.redo()
                self.progress(
                    "Applied redo to the active editable session."
                )
                return (
                    "Redo applied.\n\n"
                    f"Workspace: {session.workspace}\n"
                    f"Preview: {session.preview_path}\n"
                    f"Revision: {session.scene.get('revision', 0)}"
                )

            if any(term in text for term in edit_terms):
                try:
                    scene, operations = session.edit(message)
                except ValueError:
                    pass
                else:
                    self.progress(
                        "Applied incremental edit to the same "
                        "persistent visual document."
                    )

                    return (
                        "Updated the active editable visual session.\n\n"
                        f"Document: {scene.get('document_id')}\n"
                        f"Revision: {scene.get('revision')}\n"
                        f"Operations: {len(operations)}\n"
                        f"Scene: {session.scene_path}\n"
                        f"Preview: {session.preview_path}"
                    )

        return original_call_provider(
            self,
            message,
            timeout=timeout,
        )

    tui_v2.ObservableTUI.call_provider = call_provider
    tui_v2._capability_acquisition_patch_installed = True
