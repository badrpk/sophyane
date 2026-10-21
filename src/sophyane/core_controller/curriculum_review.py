"""Explicit LLM review boundary for durable curriculum candidates."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Any

from sophyane.rsi.curriculum import AbilityRecord, CurriculumPolicy, CurriculumStore, CurriculumScheduler, TaskStatus
from sophyane.rsi.curriculum_intelligence import CurriculumIntelligenceRouter
from sophyane.rsi.curriculum_proposals import ProposalContext, ProposalResult
from sophyane.rsi.intelligence_evidence import ProviderEvidenceStore


class CurriculumTaskReviewer:
    """Review queued tasks without executing or promoting them."""

    def __init__(self, state_path: Path, reviewer: Callable[[str], str] | None = None):
        self.store = CurriculumStore(state_path)
        self.scheduler = CurriculumScheduler(self.store, CurriculumPolicy())
        evidence_path = state_path.with_name(state_path.stem + ".provider-evidence.json")
        if reviewer is None:
            from sophyane.providers.codex_cli import CodexCliProvider

            provider = CodexCliProvider(workspace=Path.cwd())
            reviewer = lambda prompt: provider.generate(
                prompt,
                "Review one bounded curriculum candidate. Return JSON only: {\\\"action\\\":\\\"approve\\\"} or {\\\"action\\\":\\\"reject\\\",\\\"reason\\\":\\\"...\\\"}. Do not execute actions.",
            )
        self.router = CurriculumIntelligenceRouter(
            {"codex_cli": reviewer},
            ProviderEvidenceStore(evidence_path),
            provider_order=("codex_cli",),
        )

    def review(self, task_id: str | None = None) -> dict[str, Any]:
        state = self.store.load()
        task = next(
            (item for item in state.queue if item.task_id == task_id),
            None,
        ) if task_id else next(
            (item for item in state.queue if item.status is TaskStatus.QUEUED),
            None,
        )
        if task is None:
            return {"reviewed": False, "reason": "no queued curriculum task"}

        ability = AbilityRecord(
            ability_id=task.parent_ability_id or "runtime-observation",
            name=task.component or "runtime improvement",
            evidence=(task.objective,),
            task_id=task.task_id,
        )
        context = ProposalContext(
            ability=ability,
            allowed_paths=task.editable_paths,
            existing_task_ids=tuple(item.task_id for item in state.queue),
            capability_summary=task.objective,
        )
        proposal = ProposalResult(True, task, "candidate")
        result = self.router.review(context, proposal)
        if result.review_outcome in {"approved", "rejected"}:
            self.scheduler.record_review(
                task.task_id,
                approved=result.review_outcome == "approved",
                provider=result.reviewers[0] if result.reviewers else "",
                reason=result.reason,
            )
        self.store.append_event({
            "event": "llm_task_reviewed",
            "task_id": task.task_id,
            "outcome": result.review_outcome,
            "provider": result.reviewers,
        })
        return {
            "reviewed": True,
            "task_id": task.task_id,
            "approved": result.review_outcome == "approved",
            "outcome": result.review_outcome,
            "reason": result.reason,
            "provider": result.reviewers[0] if result.reviewers else "",
        }


def review_host_curriculum_task(task_id: str | None = None, *, reviewer: Callable[[str], str] | None = None) -> dict[str, Any]:
    path = Path(os.environ.get("SOPHYANE_CURRICULUM_STATE", ".sophyane-state/curriculum.json")).expanduser()
    return CurriculumTaskReviewer(path, reviewer=reviewer).review(task_id)


__all__ = ["CurriculumTaskReviewer", "review_host_curriculum_task"]
