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


def _is_internal_provider_prompt(message: str) -> bool:
    """Identify SLI/provider control prompts that are not user edits.

    The acquisition wrapper surrounds ObservableTUI.call_provider(), which
    is also used internally by semantic resolution and planning. Those
    internal calls must reach the provider unchanged and must never mutate
    the active canvas.
    """

    raw = str(message or "")
    text = " ".join(raw.lower().split())

    strong_prefixes = (
        "answer directly",
        "system:",
        "developer:",
        "sli_profile=",
        "sli profile:",
        "return only",
        "respond only",
        "you are ",
        "analyze the following",
        "resolve the following",
        "semantic consultation",
    )

    strong_markers = (
        "no json or tool action",
        "approved sli intent ledger",
        "sli execution guidance",
        "recent sli execution history",
        "provider latency",
        "return only the next compact executable",
        "do not broaden scope",
        "uncertain terms",
        "semantic confidence",
        "frozen user intent",
        "tool action",
    )

    if any(text.startswith(prefix) for prefix in strong_prefixes):
        return True

    marker_hits = sum(
        marker in text
        for marker in strong_markers
    )

    # Internal prompts are usually long and contain multiple control markers.
    if len(raw) > 700 and marker_hits >= 2:
        return True

    return False


def _is_editable_session_request(message: str) -> bool:
    """Return whether the user is asking to start an editable visual mission."""

    text = " ".join(
        str(message or "").lower().split()
    )

    artifact_terms = (
        "portrait",
        "poster",
        "logo",
        "wallpaper",
        "illustration",
        "design",
        "canvas",
        "visual",
    )

    editing_terms = (
        "editable",
        "keep editing",
        "continue editing",
        "same document",
        "same design",
        "like canva",
        "canva",
        "undo",
        "redo",
        "live preview",
        "layers",
        "select element",
        "change only",
    )

    return (
        any(term in text for term in artifact_terms)
        and any(term in text for term in editing_terms)
    )


def _activate_editable_session(
    tui: Any,
    message: str,
) -> str:
    """Start a new session using an already installed capability."""

    workspace = _capability_workspace(
        tui,
        message,
    )

    session = _active_canvas_session(
        tui,
        workspace,
    )

    # Reset only when the workspace does not yet contain an active
    # user mission. Existing active sessions are never replaced here.
    tui._active_canvas_session = session
    tui._active_canvas_workspace = str(session.workspace)

    registry_path = (
        session.workspace
        / ".sophyane-active-capability.json"
    )

    registry_payload = {
        "capability": "editable_visual_session",
        "document_id": session.scene.get("document_id"),
        "workspace": str(session.workspace),
        "scene_file": str(session.scene_path),
        "preview_file": str(session.preview_path),
        "revision": session.scene.get("revision", 0),
        "original_request": message,
        "status": "active",
        "activation": "installed_capability",
    }

    import json

    temporary = registry_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            registry_payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(registry_path)

    tui.progress(
        "SLI Capability: installed editable capability activated "
        "as a persistent mission."
    )

    return (
        "Editable visual session activated.\n\n"
        f"Document: {session.scene.get('document_id')}\n"
        f"Revision: {session.scene.get('revision', 0)}\n"
        f"Workspace: {session.workspace}\n"
        f"Scene: {session.scene_path}\n"
        f"Preview: {session.preview_path}"
    )


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
        # SLI semantic resolution, planning and provider-control prompts
        # are internal traffic. They must bypass canvas/session routing.
        if _is_internal_provider_prompt(message):
            return original_call_provider(
                self,
                message,
                timeout=timeout,
            )

        # Mission-local controls and edits have highest priority.
        # They must never be reinterpreted as requests to acquire
        # capabilities that the active session already owns.
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

            text = " ".join(
                message.lower().split()
            )

            if text in {
                "/undo",
                "undo",
                "undo last change",
            }:
                session.undo()
                self.progress(
                    "Applied undo to the active editable session."
                )
                return (
                    "Undo applied.\n\n"
                    f"Workspace: {session.workspace}\n"
                    f"Document: "
                    f"{session.scene.get('document_id')}\n"
                    f"Preview: {session.preview_path}\n"
                    f"Revision: "
                    f"{session.scene.get('revision', 0)}"
                )

            if text in {
                "/redo",
                "redo",
                "redo last change",
            }:
                session.redo()
                self.progress(
                    "Applied redo to the active editable session."
                )
                return (
                    "Redo applied.\n\n"
                    f"Workspace: {session.workspace}\n"
                    f"Document: "
                    f"{session.scene.get('document_id')}\n"
                    f"Preview: {session.preview_path}\n"
                    f"Revision: "
                    f"{session.scene.get('revision', 0)}"
                )

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
                "sit",
                "sits",
                "sitting",
                "seated",
                "seat",
                "seats",
                "resize",
                "change",
                "modify",
                "remove",
                "add",
            )

            if any(
                term in text
                for term in edit_terms
            ):
                try:
                    scene, operations = session.edit(
                        message
                    )
                except ValueError:
                    pass
                else:
                    self.progress(
                        "Applied incremental edit to the same "
                        "persistent visual document."
                    )

                    return (
                        "Updated the active editable visual "
                        "session.\n\n"
                        f"Document: "
                        f"{scene.get('document_id')}\n"
                        f"Revision: "
                        f"{scene.get('revision')}\n"
                        f"Operations: "
                        f"{len(operations)}\n"
                        f"Scene: {session.scene_path}\n"
                        f"Preview: {session.preview_path}"
                    )

        # An installed capability still needs a mission instance.
        # Starting a session is not recursive acquisition because the
        # required implementation is already available.
        if _is_editable_session_request(message):
            return _activate_editable_session(
                self,
                message,
            )

        # Only requests not handled by an active mission or an
        # installed-capability activation are eligible for acquisition.
        gap = detect_capability_gap(message)

        if gap is not None:
            self.progress(
                "Current runtime cannot yet satisfy all "
                "acceptance criteria; checking whether "
                "Sophyane can acquire the missing capability."
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
                    "Capability upgrade validated; resuming "
                    "the original request against the upgraded "
                    "runtime."
                )

                self._active_canvas_session = (
                    _active_canvas_session(
                        self,
                        result.payload.get("workspace")
                        or workspace,
                    )
                )

                return _format_result(result)

            self.progress(
                "Bounded capability acquisition did not "
                "satisfy the request; falling back to the "
                "normal provider route."
            )

        return original_call_provider(
            self,
            message,
            timeout=timeout,
        )

    tui_v2.ObservableTUI.call_provider = call_provider
    tui_v2._capability_acquisition_patch_installed = True
