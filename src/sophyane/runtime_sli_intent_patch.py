"""Install SLI intent decisions after all legacy execution-routing patches."""
from __future__ import annotations


def install_sli_intent_routing() -> None:
    from sophyane import tui_v2
    from sophyane.sli_intent_router import classify_intent, record_intent

    if getattr(tui_v2, "_sli_intent_routing_installed", False):
        return

    current_execution_requested = tui_v2._execution_requested

    def execution_requested(message: str) -> bool:
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
