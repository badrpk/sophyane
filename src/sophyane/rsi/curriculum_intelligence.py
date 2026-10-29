"""Fail-closed intelligence review for bounded curriculum proposals."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Callable, Mapping

from .curriculum_proposals import ProposalContext, ProposalResult
from .intelligence_evidence import ProviderEvidenceStore


class CurriculumIntelligenceRouter:
    def __init__(self, reviewers: Mapping[str, Callable[[str], str]], evidence: ProviderEvidenceStore,
                 provider_order: tuple[str, ...] = ("codex_cli", "nifdu_browser")):
        self.reviewers = dict(reviewers)
        self.evidence = evidence
        self.provider_order = provider_order

    def _prompt(self, context: ProposalContext, proposal: ProposalResult) -> str:
        return json.dumps({
            "ability": context.ability.name,
            "capability_summary": context.capability_summary,
            "task": {
                "task_id": proposal.task.task_id,
                "objective": proposal.task.objective,
                "editable_paths": list(proposal.task.editable_paths),
                "verification": list(proposal.task.verification),
            },
            "required_output": "JSON action approve or reject with optional reason; do not change the task",
        }, sort_keys=True)

    def review(self, context: ProposalContext, proposal: ProposalResult) -> ProposalResult:
        if not proposal.accepted or proposal.task is None:
            return proposal
        base = replace(proposal, generator=proposal.generator or "local_llm")
        for provider in self.evidence.rank(self.provider_order):
            reviewer = self.reviewers.get(provider)
            if reviewer is None:
                continue
            try:
                payload = json.loads(reviewer(self._prompt(context, base)))
                if not isinstance(payload, dict) or payload.get("action") not in {"approve", "reject"}:
                    raise ValueError("invalid review action")
                approved = payload["action"] == "approve"
                self.evidence.record(provider, approved)
            except Exception:
                try:
                    self.evidence.record(provider, False)
                except ValueError:
                    pass
                continue
            if approved:
                return replace(base, reviewers=(provider,), review_outcome="approved")
            return replace(base, accepted=False, task=None, reason=str(payload.get("reason", "provider rejected proposal"))[:2000], reviewers=(provider,), review_outcome="rejected")
        return replace(base, review_outcome="unavailable")
