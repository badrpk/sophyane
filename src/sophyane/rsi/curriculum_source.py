"""Bounded, proposal-only LLM source for curriculum tasks."""

from __future__ import annotations

import json
from typing import Callable

from .curriculum_proposals import ProposalContext, ProposalResult


class CurriculumTaskSource:
    def __init__(self, generate: Callable[[str], str], proposal_adapter):
        self.generate = generate
        self.proposal_adapter = proposal_adapter

    def propose(self, context: ProposalContext | dict) -> ProposalResult:
        if isinstance(context, dict):
            context = ProposalContext(**context)
        prompt = json.dumps(
            {
                "ability": context.ability.name,
                "capability_summary": context.capability_summary,
                "allowed_paths": list(context.allowed_paths),
                "existing_task_ids": list(context.existing_task_ids),
                "required_output": "one JSON task object only",
            },
            sort_keys=True,
        )[:12000]
        try:
            raw = self.generate(prompt)
        except Exception as error:
            return ProposalResult(False, None, f"provider error: {error}")
        try:
            return self.proposal_adapter.validate(raw, context)
        except Exception as error:
            return ProposalResult(False, None, f"proposal validation error: {error}")
