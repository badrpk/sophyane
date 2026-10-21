"""Bounded, proposal-only LLM source for curriculum tasks."""

from __future__ import annotations

import json
from typing import Callable

from .curriculum_proposals import ProposalContext, ProposalResult


class CurriculumTaskSource:
    def __init__(self, generate: Callable[[str], str], proposal_adapter, intelligence=None):
        self.generate = generate
        self.proposal_adapter = proposal_adapter
        self.intelligence = intelligence
        self._proposal_attempt = 0

    def propose(self, context: ProposalContext | dict) -> ProposalResult:
        if isinstance(context, dict):
            context = ProposalContext(**context)
        self._proposal_attempt += 1

        def bounded(values, limit=32, item_limit=256, newest=False):
            values = list(values)
            if newest:
                values = values[-limit:]
            else:
                values = values[:limit]
            return [str(value)[:item_limit] for value in values]

        payload = {
            "ability_id": context.ability.ability_id,
            "ability": context.ability.name,
            "capability_summary": context.capability_summary,
            "allowed_paths": bounded(context.allowed_paths),
            "existing_task_ids": bounded(context.existing_task_ids, newest=True),
            "repository_id": context.repository_id,
            "base_commit": context.base_commit,
            "repository_editable_paths": bounded(context.repository.editable_paths) if context.repository else [],
            "required_fields": ["repository_id", "base_commit", "red_command", "red_failure_marker", "green_commands"],
            "verification_schema": {
                "type": "array",
                "min_items": 1,
                "max_items": 16,
                "items": "non-empty string arguments, not one string or an object",
                "example": ["PYTHONPATH=src .venv/bin/pytest -q tests/test_target.py"],
            },
            "editable_paths_schema": {
                "type": "array",
                "min_items": 1,
                "max_items": 8,
                "items": "one exact path from allowed_paths",
            },
            "required_output": "one JSON task object only",
            "proposal_attempt": self._proposal_attempt,
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
            proposal = self.proposal_adapter.validate(raw, context)
            if proposal.accepted and self.intelligence is not None:
                return self.intelligence.review(context, proposal)
            return proposal
        except Exception as error:
            return ProposalResult(False, None, f"proposal validation error: {error}")
