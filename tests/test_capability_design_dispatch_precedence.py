from pathlib import Path


def test_early_intent_boundary_is_before_direct_provider():
    source = Path(
        "src/sophyane/tui_v2.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        source.index(
            "SOPHYANE_EARLY_CONVERSATIONAL_INTENT_AUTHORITY_V8_1"
        )
        <
        source.index(
            "dispatch_user_request("
        )
    )


def test_design_intent_disables_quick_chat_reply():
    source = Path(
        "src/sophyane/tui_v2.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_CAPABILITY_DESIGN_BEFORE_QUICK_REPLY_V8_1"
        in source
    )

    assert (
        "_sophyane_early_design_prompt"
        in source
    )


def test_direct_provider_receives_prepared_design_message():
    source = Path(
        "src/sophyane/tui_v2.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "dispatch_user_request("
        in source
    )

    assert (
        "_sophyane_provider_message"
        in source
    )


def test_direct_provider_response_is_retained_for_graph():
    source = Path(
        "src/sophyane/tui_v2.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_EARLY_DIRECT_RESPONSE_RETENTION_V8_1"
        in source
    )


def test_exact_capability_parity_request_builds_systematic_prompt():
    from sophyane.capability_design import (
        prepare_capability_design_request,
    )

    request = (
        "Sophyane should have all features "
        "as ElevenLabs"
    )

    prompt = (
        prepare_capability_design_request(
            request=request,
            conversational_context=request,
        )
    )

    assert prompt is not None
    assert "Required response structure" in prompt
    assert "PROCESS_FLOW:" in prompt


def test_second_turn_flow_is_graph_followup():
    from sophyane.conversational_graph import (
        is_conversational_graph_followup,
    )

    assert (
        is_conversational_graph_followup(
            "show me the flow"
        )
        is True
    )
