"""Install SLI intent decisions after all legacy execution-routing patches."""
from __future__ import annotations

import re


_STATE_ACTIONS = (
    "read",
    "inspect",
    "check",
    "search",
    "find",
    "query",
    "show",
    "identify",
    "recover",
    "load",
    "locate",
    "list",
)

_STATE_TARGETS = (
    "local state",
    "persistent state",
    "saved state",
    "runtime state",
    "session state",
    "state file",
    "scratchpad",
    "checkpoint",
    "previous run",
    "previous task",
    "previous turn",
    "last run",
    "last task",
    "conversation history",
    "memory database",
    "memory db",
    "local log",
    "recent log",
    "runtime log",
    "filesystem evidence",
    "intermediate output",
    "intermediate outputs",
)

_EVIDENCE_REQUIREMENTS = (
    "without re-injecting",
    "without conversation history",
    "using filesystem",
    "using local state",
    "from the filesystem",
    "from local state",
    "read the local",
    "exact file",
    "exact files",
    "where are",
    "where is",
    "stored",
    "evidence",
)


def persistent_state_inspection_request(message: str) -> bool:
    """Return True for requests that must inspect persisted local evidence."""
    text = " ".join(str(message or "").casefold().split())

    has_action = any(
        re.search(rf"\b{re.escape(action)}\b", text)
        for action in _STATE_ACTIONS
    )
    has_target = any(target in text for target in _STATE_TARGETS)
    has_evidence_requirement = any(
        phrase in text
        for phrase in _EVIDENCE_REQUIREMENTS
    )

    # Strong explicit combinations are always execution requests.
    if has_action and has_target:
        return True

    # Questions such as "what was the previous task and where is it stored?"
    # often omit an imperative verb but still require real filesystem state.
    return has_target and has_evidence_requirement


def install_sli_intent_routing() -> None:
    from sophyane import tui_v2
    from sophyane.sli_intent_router import classify_intent, record_intent

    if getattr(tui_v2, "_sli_intent_routing_installed", False):
        return

    current_execution_requested = tui_v2._execution_requested

    def execution_requested(message: str) -> bool:
        # SOPHYANE_PERSISTENT_STATE_INSPECTION_V1
        # Requests about previous runs, checkpoints, logs, scratchpads or
        # persisted conclusions must inspect real local evidence. They must
        # never be answered from provider memory or ordinary chat context.
        if persistent_state_inspection_request(message):
            return True

        # SOPHYANE_HARNESS_EXECUTION_OVERRIDE_V1
        # Strong build, repository, benchmark and long-loop requests must be
        # resolved before the generic SLI direct-response classifier can veto
        # execution.
        try:
            from sophyane.harness_task_policy import (
                is_execution_request,
            )

            if is_execution_request(message):
                return True
        except Exception:
            pass

        # SOPHYANE_GROUNDED_FILESYSTEM_ROUTING
        # Filesystem inspection must run against real local state even when
        # the generic intent router incorrectly labels it direct_response.
        try:
            from sophyane.runtime_filesystem_capabilities_v20 import (
                classify_request,
            )
            if classify_request(message):
                return True
        except Exception:
            pass

        decision = classify_intent(message, has_project=False)
        if decision.route == "direct_response":
            return False
        return current_execution_requested(message)

    def project_continuation(message: str, has_project: bool) -> bool:
        decision = classify_intent(message, has_project=has_project)
        record_intent(message, decision, has_project=has_project)
        return decision.route == "continue_project"

    tui_v2._execution_requested = execution_requested
    tui_v2._project_continuation = project_continuation
    tui_v2._sli_intent_routing_installed = True
