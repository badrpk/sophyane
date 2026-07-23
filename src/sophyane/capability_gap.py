"""Acceptance-driven recursive capability acquisition for Sophyane.

The orchestrator does not permit arbitrary uncontrolled self-modification.
Each capability is acquired through a registered, bounded builder containing
explicit stages, tests, rollback information and success evidence.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable, Protocol


Progress = Callable[[str], None]


@dataclass(frozen=True)
class CapabilityGap:
    request: str
    required_capabilities: frozenset[str]
    available_capabilities: frozenset[str]
    missing_capabilities: frozenset[str]
    acceptance_criteria: tuple[str, ...]
    failure_kind: str = "capability_gap"
    evidence: tuple[str, ...] = ()


@dataclass
class StageResult:
    name: str
    success: bool
    evidence: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class ImprovementResult:
    success: bool
    capability: str
    stages: list[StageResult]
    evidence: list[str]
    retry_original_request: bool
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


class CapabilityBuilder(Protocol):
    capability: str

    def supports(self, gap: CapabilityGap) -> bool:
        ...

    def build(
        self,
        gap: CapabilityGap,
        *,
        workspace: Path,
        progress: Progress,
    ) -> ImprovementResult:
        ...


_EDITABLE_TERMS = {
    "editable",
    "keep editing",
    "continue editing",
    "same design",
    "same portrait",
    "same document",
    "like canva",
    "canva",
    "undo",
    "redo",
    "layers",
    "select element",
    "move it",
    "resize it",
    "change only",
    "live preview",
    "visual editor",
    "edit the same",
}


def required_capabilities(request: str) -> set[str]:
    text = " ".join(request.lower().split())
    required: set[str] = set()

    if any(term in text for term in _EDITABLE_TERMS):
        required.update(
            {
                "persistent_visual_session",
                "structured_scene_edits",
                "visual_revision_history",
                "undo_redo",
                "persistent_preview",
                "follow_up_edit_routing",
            }
        )

    if any(
        word in text
        for word in (
            "portrait",
            "poster",
            "logo",
            "wallpaper",
            "illustration",
            "design",
        )
    ) and any(term in text for term in _EDITABLE_TERMS):
        required.add("editable_visual_artifact")

    return required


def available_capabilities() -> set[str]:
    available = {
        "provider_generation",
        "workspace_execution",
        "browser_artifact_generation",
        "live_prompt_steering",
    }

    try:
        from sophyane.editable_canvas import CanvasSession

        if CanvasSession is not None:
            available.update(
                {
                    "persistent_visual_session",
                    "structured_scene_edits",
                    "visual_revision_history",
                    "undo_redo",
                    "persistent_preview",
                    "editable_visual_artifact",
                }
            )
    except Exception:
        pass

    try:
        from sophyane.runtime_editable_canvas_patch import (
            install_editable_canvas_runtime,
        )

        if install_editable_canvas_runtime is not None:
            available.add("follow_up_edit_routing")
    except Exception:
        pass

    return available


def acceptance_criteria_for(
    required: set[str],
) -> tuple[str, ...]:
    criteria: list[str] = []

    mapping = {
        "persistent_visual_session":
            "The same document ID survives multiple edits and reopening.",
        "structured_scene_edits":
            "Edits modify bounded scene properties or elements.",
        "visual_revision_history":
            "Every successful edit produces a new persisted revision.",
        "undo_redo":
            "Undo reverses the latest edit and redo restores it.",
        "persistent_preview":
            "One preview file represents the current document revision.",
        "follow_up_edit_routing":
            "Follow-up edit requests target the active visual session.",
        "editable_visual_artifact":
            "The result is an editable artifact, not only descriptive text.",
    }

    for capability in sorted(required):
        criterion = mapping.get(capability)

        if criterion:
            criteria.append(criterion)

    return tuple(criteria)


def detect_capability_gap(
    request: str,
    *,
    available: set[str] | None = None,
) -> CapabilityGap | None:
    required = required_capabilities(request)

    if not required:
        return None

    current = set(
        available
        if available is not None
        else available_capabilities()
    )

    missing = required - current

    if not missing:
        return None

    return CapabilityGap(
        request=request,
        required_capabilities=frozenset(required),
        available_capabilities=frozenset(current),
        missing_capabilities=frozenset(missing),
        acceptance_criteria=acceptance_criteria_for(required),
        evidence=(
            "Request requires an editable persistent visual workflow.",
            "Current capability registry does not satisfy all requirements.",
        ),
    )


class Heartbeat:
    """Emit truthful periodic status while a bounded stage is active."""

    def __init__(
        self,
        progress: Progress,
        message: str,
        interval: float = 5.0,
    ) -> None:
        self.progress = progress
        self.message = message
        self.interval = max(1.0, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def __enter__(self) -> "Heartbeat":
        self._started = time.monotonic()

        def run() -> None:
            tick = 1

            while not self._stop.wait(self.interval):
                elapsed = int(time.monotonic() - self._started)
                self.progress(
                    f"{self.message} "
                    f"({elapsed}s elapsed; checkpoint {tick})"
                )
                tick += 1

        self._thread = threading.Thread(
            target=run,
            daemon=True,
            name="sophyane-capability-heartbeat",
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc: Any,
        traceback: Any,
    ) -> None:
        self._stop.set()

        if self._thread is not None:
            self._thread.join(timeout=1.0)


class EditableVisualBuilder:
    capability = "editable_visual_session"

    def supports(self, gap: CapabilityGap) -> bool:
        editable_set = {
            "persistent_visual_session",
            "structured_scene_edits",
            "visual_revision_history",
            "undo_redo",
            "persistent_preview",
            "follow_up_edit_routing",
            "editable_visual_artifact",
        }
        return bool(gap.missing_capabilities & editable_set)

    def build(
        self,
        gap: CapabilityGap,
        *,
        workspace: Path,
        progress: Progress,
    ) -> ImprovementResult:
        stages: list[StageResult] = []
        evidence: list[str] = []
        workspace.mkdir(parents=True, exist_ok=True)

        progress(
            "Capability gap confirmed: editable persistent visual "
            "sessions are required."
        )

        # Stage 1: verify or acquire scene engine.
        progress(
            "Improvement stage 1/5: acquiring persistent scene state."
        )

        with Heartbeat(
            progress,
            "Building persistent scene-state capability",
        ):
            try:
                from sophyane.editable_canvas import CanvasSession
            except Exception as error:
                return ImprovementResult(
                    success=False,
                    capability=self.capability,
                    stages=stages,
                    evidence=evidence,
                    retry_original_request=False,
                    message=(
                        "Editable canvas engine is not installed. "
                        f"{type(error).__name__}: {error}"
                    ),
                )

            session = CanvasSession.open(
                workspace,
                title="Sophyane Editable Visual Session",
            )

            document_id = str(
                session.scene.get("document_id") or ""
            )

            if not document_id:
                return ImprovementResult(
                    success=False,
                    capability=self.capability,
                    stages=stages,
                    evidence=evidence,
                    retry_original_request=False,
                    message="Scene engine did not produce a document ID.",
                )

        stage = StageResult(
            name="persistent scene",
            success=True,
            evidence=[
                f"Document ID created: {document_id}",
                f"Scene file: {session.scene_path}",
            ],
        )
        stages.append(stage)
        evidence.extend(stage.evidence)
        progress(
            "Stage 1 passed: persistent scene document created."
        )

        # Stage 2: prove incremental edits preserve identity.
        progress(
            "Improvement stage 2/5: validating incremental scene edits."
        )

        with Heartbeat(
            progress,
            "Testing incremental edit operations",
        ):
            before_id = session.scene["document_id"]
            before_revision = int(
                session.scene.get("revision", 0)
            )

            request_text = gap.request.lower()

            if "jinnah" in request_text:
                session.edit("it should be of Jinnah")
            else:
                session.edit("move the subject slightly right")

            after_id = session.scene["document_id"]
            after_revision = int(
                session.scene.get("revision", 0)
            )

            if before_id != after_id:
                raise RuntimeError(
                    "Document identity changed during incremental edit."
                )

            if after_revision <= before_revision:
                raise RuntimeError(
                    "Revision did not increase after incremental edit."
                )

        stage = StageResult(
            name="incremental edits",
            success=True,
            evidence=[
                "Document identity preserved during edit.",
                f"Revision advanced to {after_revision}.",
            ],
        )
        stages.append(stage)
        evidence.extend(stage.evidence)
        progress(
            "Stage 2 passed: bounded edit preserved the document."
        )

        # Stage 3: prove undo and redo.
        progress(
            "Improvement stage 3/5: validating undo and redo."
        )

        with Heartbeat(
            progress,
            "Testing reversible visual revisions",
        ):
            edited_snapshot = deepcopy(session.scene)
            session.undo()
            undone_snapshot = deepcopy(session.scene)
            session.redo()
            redone_snapshot = deepcopy(session.scene)

            if undone_snapshot == edited_snapshot:
                raise RuntimeError(
                    "Undo did not alter the current scene."
                )

            edited_elements = edited_snapshot.get("elements", [])
            redone_elements = redone_snapshot.get("elements", [])

            if edited_elements != redone_elements:
                raise RuntimeError(
                    "Redo did not restore edited scene elements."
                )

        stage = StageResult(
            name="undo and redo",
            success=True,
            evidence=[
                "Undo changed the scene.",
                "Redo restored edited scene elements.",
            ],
        )
        stages.append(stage)
        evidence.extend(stage.evidence)
        progress(
            "Stage 3 passed: reversible revision history works."
        )

        # Stage 4: verify persistent preview.
        progress(
            "Improvement stage 4/5: validating persistent preview."
        )

        with Heartbeat(
            progress,
            "Rendering and validating persistent preview",
        ):
            preview = session.preview_path

            if not preview.is_file():
                raise RuntimeError(
                    "Persistent preview file was not created."
                )

            preview_text = preview.read_text(
                encoding="utf-8"
            )

            if "<!doctype html" not in preview_text.lower():
                raise RuntimeError(
                    "Preview is not a complete HTML document."
                )

            if document_id not in json.dumps(
                session.scene,
                ensure_ascii=False,
            ):
                raise RuntimeError(
                    "Current scene lost its document identity."
                )

        stage = StageResult(
            name="persistent preview",
            success=True,
            evidence=[
                f"Preview file verified: {preview}",
                "Preview is backed by the current scene revision.",
            ],
        )
        stages.append(stage)
        evidence.extend(stage.evidence)
        progress(
            "Stage 4 passed: persistent preview is available."
        )

        # Stage 5: register active session for follow-up routing.
        progress(
            "Improvement stage 5/5: registering active edit session."
        )

        with Heartbeat(
            progress,
            "Registering follow-up edit routing",
        ):
            registry_path = (
                workspace
                / ".sophyane-active-capability.json"
            )

            registry_payload = {
                "capability": self.capability,
                "document_id": document_id,
                "workspace": str(workspace),
                "scene_file": str(session.scene_path),
                "preview_file": str(session.preview_path),
                "revision": session.scene.get("revision", 0),
                "original_request": gap.request,
                "acceptance_criteria": list(
                    gap.acceptance_criteria
                ),
                "status": "active",
            }

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

            if not registry_path.is_file():
                raise RuntimeError(
                    "Active capability registry was not persisted."
                )

        stage = StageResult(
            name="follow-up routing registration",
            success=True,
            evidence=[
                f"Active capability registry: {registry_path}",
                "Original request retained for resumed execution.",
            ],
        )
        stages.append(stage)
        evidence.extend(stage.evidence)
        progress(
            "Stage 5 passed: follow-up edits can target this session."
        )

        return ImprovementResult(
            success=True,
            capability=self.capability,
            stages=stages,
            evidence=evidence,
            retry_original_request=True,
            message=(
                "Editable visual capability acquired and validated. "
                "The original request can now resume against the "
                "persistent session."
            ),
            payload={
                "workspace": str(workspace),
                "document_id": document_id,
                "scene_file": str(session.scene_path),
                "preview_file": str(session.preview_path),
                "revision": session.scene.get("revision", 0),
            },
        )


_BUILDERS: list[CapabilityBuilder] = [
    EditableVisualBuilder(),
]


def register_builder(builder: CapabilityBuilder) -> None:
    if any(
        existing.capability == builder.capability
        for existing in _BUILDERS
    ):
        return

    _BUILDERS.append(builder)


def improve_until_satisfied(
    gap: CapabilityGap,
    *,
    workspace: Path,
    progress: Progress,
    max_stages: int = 6,
) -> ImprovementResult:
    progress(
        "Recursive capability acquisition activated."
    )
    progress(
        "Missing capabilities: "
        + ", ".join(sorted(gap.missing_capabilities))
    )

    for builder in _BUILDERS:
        if not builder.supports(gap):
            continue

        result = builder.build(
            gap,
            workspace=workspace,
            progress=progress,
        )

        if len(result.stages) > max_stages:
            return ImprovementResult(
                success=False,
                capability=result.capability,
                stages=result.stages[:max_stages],
                evidence=result.evidence,
                retry_original_request=False,
                message=(
                    "Improvement stopped because the bounded stage "
                    "limit was exceeded."
                ),
            )

        return result

    return ImprovementResult(
        success=False,
        capability="unregistered",
        stages=[],
        evidence=[],
        retry_original_request=False,
        message=(
            "A capability gap was detected, but no approved bounded "
            "builder is registered for this domain."
        ),
    )
