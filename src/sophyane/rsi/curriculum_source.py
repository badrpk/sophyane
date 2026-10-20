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
        payload = {
            "ability_id": context.ability.ability_id,
            "ability": context.ability.name,
            "capability_summary": context.capability_summary,
            "allowed_paths": list(context.allowed_paths),
            "existing_task_ids": list(context.existing_task_ids),
            "repository_id": context.repository_id,
            "base_commit": context.base_commit,
            "repository_editable_paths": list(context.repository.editable_paths) if context.repository else [],
            "required_fields": ["repository_id", "base_commit", "red_command", "red_failure_marker", "green_commands"],
            "required_output": "one JSON task object only",
        }
        prompt = json.dumps(payload, sort_keys=True)
        if len(prompt) > 12000:
            summary = context.capability_summary
            payload["capability_summary"] = ""
            if len(json.dumps(payload, sort_keys=True)) > 12000:
                return ProposalResult(False, None, "prompt context exceeds 12000 characters")
            low, high = 0, len(summary)
            while low < high:
                middle = (low + high + 1) // 2
                payload["capability_summary"] = summary[:middle]
                if len(json.dumps(payload, sort_keys=True)) <= 12000:
                    low = middle
                else:
                    high = middle - 1
            payload["capability_summary"] = summary[:low]
            prompt = json.dumps(payload, sort_keys=True)
        try:
            raw = self.generate(prompt)
        except Exception as error:
            return ProposalResult(False, None, f"provider error: {error}")
        try:
            return self.proposal_adapter.validate(raw, context)
        except Exception as error:
            return ProposalResult(False, None, f"proposal validation error: {error}")
