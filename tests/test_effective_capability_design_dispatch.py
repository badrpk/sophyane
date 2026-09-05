from __future__ import annotations

import inspect


def test_cli_installed_run_contains_effective_conversational_authority():
    from sophyane import tui_v2

    from sophyane.runtime_intent_refinement_patch import (
        install_intent_refinement,
    )

    install_intent_refinement()

    source = inspect.getsource(
        tui_v2.ObservableTUI.run
    )

    assert (
        "SOPHYANE_EFFECTIVE_CONVERSATIONAL_AUTHORITY_V9"
        in source
    )

    assert (
        "try_conversational_graph_followup"
        in source
    )

    assert (
        "prepare_capability_design_request"
        in source
    )

    assert (
        "remember_grounded_process_context"
        in source
    )


def test_exact_capability_request_produces_systematic_prompt():
    from sophyane.capability_design import (
        prepare_capability_design_request,
    )

    request = (
        "Sophyane should have all features as ElevenLabs"
    )

    prompt = prepare_capability_design_request(
        request=request,
        conversational_context=request,
    )

    assert prompt is not None
    assert "Required response structure" in prompt
    assert "PROCESS_FLOW:" in prompt


def test_show_me_the_flow_is_graph_followup():
    from sophyane.conversational_graph import (
        is_conversational_graph_followup,
    )

    assert (
        is_conversational_graph_followup(
            "show me the flow"
        )
        is True
    )


def test_process_flow_retention_remains_exact():
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        retained_grounded_process_context,
        retained_grounded_process_step_count,
    )

    class Session:
        pass

    session = Session()

    response = """
1. Capability goal

Detailed systematic description.

PROCESS_FLOW: input ingestion -> validation -> extraction -> transformation -> generation -> verification
""".strip()

    assert (
        remember_grounded_process_context(
            session,
            response,
        )
        is True
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == (
            "input ingestion -> validation -> extraction -> "
            "transformation -> generation -> verification"
        )
    )

    assert (
        retained_grounded_process_step_count(
            session
        )
        == 6
    )
