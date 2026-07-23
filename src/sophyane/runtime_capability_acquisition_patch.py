"""Runtime integration for user-visible recursive capability acquisition."""

from __future__ import annotations

from pathlib import Path
import re
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


def _is_repository_coding_request(message: str) -> bool:
    """Return whether repository/software intent overrides visual keywords.

    Capability routing is hierarchical. Explicit requests to inspect, modify,
    test or maintain source code must reach the repository coding runtime even
    when the request discusses visual, canvas, image or website behavior.
    """

    text = " ".join(
        str(message or "").lower().split()
    )

    if not text:
        return False

    strong_repository_markers = (
        "src/sophyane",
        "src/",
        "tests/",
        "test_",
        "pyproject.toml",
        "setup.py",
        "pytest",
        "python source",
        "python code",
        "source code",
        "repository",
        "codebase",
        "software engineering",
        "software project",
        "project files",
        "git commit",
        "git diff",
        "git status",
        "unit test",
        "regression test",
        "test suite",
    )

    coding_actions = (
        "inspect",
        "modify",
        "change",
        "fix",
        "repair",
        "patch",
        "refactor",
        "implement",
        "improve",
        "update",
        "test",
        "run",
        "compile",
        "debug",
        "maintain",
        "add",
        "remove",
        "write",
        "edit",
        "audit",
    )

    marker_count = sum(
        marker in text
        for marker in strong_repository_markers
    )
    action_present = any(
        action in text
        for action in coding_actions
    )

    # One highly specific path/test marker plus a coding action is enough.
    if marker_count >= 1 and action_present:
        return True

    # Multiple repository markers are themselves unambiguous.
    return marker_count >= 2


def _contains_intent_term(text: str, term: str) -> bool:
    """Match an intent term without accidental substring activation."""

    escaped = re.escape(term)

    # Multi-word phrases are still bounded at both ends.
    return bool(
        re.search(
            rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])",
            text,
        )
    )


def _is_editable_session_request(message: str) -> bool:
    """Return whether the user requests an editable visual artifact.

    Explanations, questions and repository-coding tasks must not activate the
    persistent canvas merely because they mention words such as visual,
    design, canvas, editable or Canva.
    """

    text = " ".join(
        str(message or "").lower().split()
    )

    if not text:
        return False

    # Explicit repository/software work outranks visual capability terms.
    if _is_repository_coding_request(text):
        return False

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

    artifact_present = any(
        _contains_intent_term(text, term)
        for term in artifact_terms
    )

    editing_present = any(
        _contains_intent_term(text, term)
        for term in editing_terms
    )

    # Creation verbs must be used as actual actions. "Design" is special:
    # it activates only when used as an imperative/leading verb, not when it
    # appears as a noun in "visual design principles".
    creation_present = bool(
        re.search(
            r"(?<![a-z0-9_])"
            r"(?:create|make|generate|draw|build|produce)"
            r"(?![a-z0-9_])",
            text,
        )
        or re.match(
            r"^(?:please\s+)?design\b",
            text,
        )
    )

    # Common explanatory or interrogative forms are conversation, unless
    # they also contain an unambiguous editing request.
    conversational = bool(
        re.match(
            r"^(?:what|why|how|when|where|who|which|explain|describe|"
            r"define|tell me about|can you explain)\b",
            text,
        )
    )

    # Explanations and questions never start a persistent visual mission.
    # Words such as editable, layers, Canva, undo or canvas may be the topic
    # being discussed rather than an instruction to mutate an artifact.
    if conversational:
        return False

    return artifact_present and (
        editing_present or creation_present
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

    # Apply the initial user instruction to the newly activated
    # scene. For example, "make Jinnah portrait" sets the person
    # immediately instead of merely creating a generic session.
    initial_operations = 0

    try:
        _, operations = session.edit(message)
    except ValueError:
        operations = []
    else:
        initial_operations = len(operations)

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
        f"Initial operations: {initial_operations}\n"
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

            # Every non-internal instruction is offered to the active
            # visual mission. The recursive visual engine decides whether
            # it contains supported, explicit visual requirements. This
            # avoids person-specific and keyword-specific routing.
            try:
                scene, operations = session.edit(message)
            except ValueError:
                pass
            else:
                match = scene.get("requirement_match", {})
                self.progress(
                    "Applied an instruction-led visual edit and "
                    "recursively verified requirement coverage."
                )

                return (
                    "Updated the active editable visual session.\n\n"
                    f"Document: {scene.get('document_id')}\n"
                    f"Revision: {scene.get('revision')}\n"
                    f"Operations: {len(operations)}\n"
                    f"Requirement match: "
                    f"{float(match.get('score', 0.0)) * 100:.1f}%\n"
                    f"Improvement iterations: "
                    f"{match.get('iterations', 0)}\n"
                    f"Stop reason: "
                    f"{match.get('stop_reason', 'unknown')}\n"
                    f"Unmet requirements: "
                    f"{len(match.get('unmet', []))}\n"
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
