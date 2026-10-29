"""Bounded, proposal-only LLM source for curriculum tasks."""

from __future__ import annotations

import json
import hashlib
import time
from typing import Callable

from .curriculum_proposals import ProposalContext, ProposalResult


class CurriculumTaskSource:
    def __init__(self, generate: Callable[[str], str], proposal_adapter, intelligence=None, metrics=None):
        self.generate = generate
        self.proposal_adapter = proposal_adapter
        self.intelligence = intelligence
        self.metrics = metrics
        self._proposal_attempt = 0

    def propose(self, context: ProposalContext | dict) -> ProposalResult:
        started = time.monotonic()
        if isinstance(context, dict):
            context = ProposalContext(**context)
        self._proposal_attempt += 1
        if (self.metrics is not None
                and getattr(self.proposal_adapter, "generator", "") in {"codex_cli", "nifdu_browser"}):
            self.metrics.increment("frontier_calls")

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
        def validate_generated(raw: str) -> ProposalResult:
            try:
                return self.proposal_adapter.validate(raw, context)
            except Exception as error:
                return ProposalResult(False, None, f"proposal validation error: {error}")

        try:
            raw = self.generate(prompt)
            proposal = validate_generated(raw)
        except Exception as error:
            return ProposalResult(False, None, f"provider error: {error}")

        # Frontier models occasionally recycle the previous task identifier
        # even when they propose a new objective. Give them one bounded,
        # explicit correction opportunity; never rewrite the identifier or
        # weaken the validator.
        if not proposal.accepted and proposal.reason == "duplicate or empty task_id":
            retry_prompt = prompt[:-1] + (
                ', "task_id_correction": "The task_id is empty or already used. '
                'Return a new unique task_id for this proposal; do not reuse any '
                'existing_task_ids."}'
            ) if prompt.endswith("}") else prompt + "\nReturn a new unique task_id; do not reuse existing_task_ids."
            try:
                raw = self.generate(retry_prompt)
                proposal = validate_generated(raw)
            except Exception as error:
                return ProposalResult(False, None, f"provider error: {error}")
            if not proposal.accepted and proposal.reason == "duplicate or empty task_id":
                try:
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise ValueError("proposal is not an object")
                    material = json.dumps({
                        "ability": context.ability.ability_id,
                        "attempt": self._proposal_attempt,
                        "content": raw,
                        "time_ns": time.time_ns(),
                    }, sort_keys=True)
                    payload["task_id"] = "frontier-" + hashlib.sha256(material.encode()).hexdigest()[:24]
                    proposal = validate_generated(json.dumps(payload, sort_keys=True))
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass

        if not proposal.accepted and proposal.reason == "parent ability does not match current ability":
            retry_prompt = prompt[:-1] + (
                ', "parent_ability_correction": "The parent_ability_id is stale. '
                f'Use exactly {context.ability.ability_id} as parent_ability_id; do not reuse any older ability ID."}}'
            ) if prompt.endswith("}") else prompt + (
                f"\nUse exactly {context.ability.ability_id} as parent_ability_id; do not reuse an older ability ID."
            )
            try:
                raw = self.generate(retry_prompt)
                proposal = validate_generated(raw)
            except Exception as error:
                return ProposalResult(False, None, f"provider error: {error}")

        if proposal.accepted and self.intelligence is not None:
            proposal = self.intelligence.review(context, proposal)
        if self.metrics is not None and hasattr(self.metrics, "record_proposal"):
            provider = getattr(self.proposal_adapter, "generator", "unknown") or "unknown"
            self.metrics.record_proposal(provider, proposal.accepted, (time.monotonic() - started) * 1000)
        return proposal
