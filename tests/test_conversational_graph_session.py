from __future__ import annotations

from pathlib import Path


PROCESS = (
    "ingest input -> validate input -> extract content -> "
    "structure content -> chunk content -> understand content -> "
    "prepare output -> generate output -> verify output"
)


class Session:
    def __init__(
        self,
        workspace: Path,
    ):
        self.workspace = workspace


def test_grounded_process_is_retained(
    tmp_path: Path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        retained_grounded_process_context,
        retained_grounded_process_step_count,
    )

    session = Session(
        tmp_path
    )

    assert (
        remember_grounded_process_context(
            session,
            PROCESS,
        )
        is True
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == PROCESS
    )

    assert (
        retained_grounded_process_step_count(
            session
        )
        == 9
    )


def test_plain_answer_is_not_mistaken_for_process(
    tmp_path: Path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        retained_grounded_process_context,
    )

    session = Session(
        tmp_path
    )

    assert (
        remember_grounded_process_context(
            session,
            "Yes, this capability can be implemented.",
        )
        is False
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == ""
    )


def test_followup_uses_retained_context_without_provider(
    tmp_path: Path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        try_conversational_graph_followup,
    )

    session = Session(
        tmp_path
    )

    assert remember_grounded_process_context(
        session,
        PROCESS,
    )

    #
    # No provider object exists anywhere in this test.
    #
    response = (
        try_conversational_graph_followup(
            session,
            "show me the flow",
        )
    )

    assert response is not None

    assert (
        "◆ Sophyane process graph"
        in response
    )

    assert (
        "flowchart TD"
        in response
    )

    assert (
        "ingest_input"
        in response
    )

    assert list(
        tmp_path.rglob(
            "*.mmd"
        )
    )

    assert list(
        tmp_path.rglob(
            "*.json"
        )
    )


def test_graph_followup_without_context_falls_through(
    tmp_path: Path,
):
    from sophyane.conversational_graph_session import (
        try_conversational_graph_followup,
    )

    session = Session(
        tmp_path
    )

    result = (
        try_conversational_graph_followup(
            session,
            "show me the flow",
        )
    )

    assert result is None

    assert not list(
        tmp_path.rglob(
            "*.mmd"
        )
    )


def test_non_graph_followup_does_not_intercept(
    tmp_path: Path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        try_conversational_graph_followup,
    )

    session = Session(
        tmp_path
    )

    assert remember_grounded_process_context(
        session,
        PROCESS,
    )

    assert (
        try_conversational_graph_followup(
            session,
            "can you explain the third step?",
        )
        is None
    )


def test_new_grounded_process_replaces_old_process(
    tmp_path: Path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        retained_grounded_process_context,
    )

    session = Session(
        tmp_path
    )

    first = (
        "collect -> normalize -> verify"
    )

    second = (
        "load -> parse -> transform -> save"
    )

    assert remember_grounded_process_context(
        session,
        first,
    )

    assert remember_grounded_process_context(
        session,
        second,
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == second
    )


def test_process_flow_line_has_retention_authority_over_surrounding_prose(
    tmp_path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        retained_grounded_process_context,
        retained_grounded_process_step_count,
    )

    class Session:
        workspace = tmp_path

    session = Session()

    assistant_text = """1. Capability goal

A detailed explanation may span many lines.

2. Processing architecture

More explanatory prose appears here.

PROCESS_FLOW: input ingestion -> validation -> content extraction -> chunking -> semantic processing -> output generation -> verification
"""

    assert (
        remember_grounded_process_context(
            session,
            assistant_text,
        )
        is True
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == (
            "input ingestion -> validation -> content extraction -> "
            "chunking -> semantic processing -> output generation -> "
            "verification"
        )
    )

    assert (
        retained_grounded_process_step_count(
            session
        )
        == 7
    )


def test_process_flow_retention_strips_marker_from_first_node(
    tmp_path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        try_conversational_graph_followup,
    )

    class Session:
        workspace = tmp_path

    session = Session()

    assert remember_grounded_process_context(
        session,
        (
            "Architecture explanation.\n\n"
            "PROCESS_FLOW: ingest -> normalize -> understand -> verify"
        ),
    )

    response = try_conversational_graph_followup(
        session,
        "show me the flow",
    )

    assert response is not None

    assert "ingest[ingest]" in response
    assert "process_flow_ingest" not in response.lower()
    assert "architecture_explanation" not in response.lower()


def test_generic_arrow_process_retention_remains_supported(
    tmp_path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        retained_grounded_process_context,
    )

    class Session:
        workspace = tmp_path

    session = Session()

    flow = (
        "discover -> inspect -> modify -> verify"
    )

    assert (
        remember_grounded_process_context(
            session,
            flow,
        )
        is True
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == flow
    )


def test_process_flow_without_real_sequence_does_not_override_fallback(
    tmp_path,
):
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        retained_grounded_process_context,
    )

    class Session:
        workspace = tmp_path

    session = Session()

    text = (
        "inspect -> validate -> verify\n"
        "PROCESS_FLOW: incomplete"
    )

    assert (
        remember_grounded_process_context(
            session,
            text,
        )
        is True
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == "inspect -> validate -> verify"
    )


def test_long_systematic_response_prefers_explicit_inline_arrow_chain():
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

Long prose explanation.

content ingestion → understanding/transformation → voice/audio generation → media processing → delivery/reuse

2. User-facing abilities

More prose.
""".strip()

    assert remember_grounded_process_context(
        session,
        response,
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == (
            "content ingestion → understanding/transformation → "
            "voice/audio generation → media processing → delivery/reuse"
        )
    )

    assert (
        retained_grounded_process_step_count(
            session
        )
        == 5
    )


def test_process_flow_beats_other_arrow_chain():
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
        retained_grounded_process_context,
    )

    class Session:
        pass

    session = Session()

    response = """
example one -> example two -> example three

PROCESS_FLOW: ingest -> validate -> generate -> verify
""".strip()

    assert remember_grounded_process_context(
        session,
        response,
    )

    assert (
        retained_grounded_process_context(
            session
        )
        == "ingest -> validate -> generate -> verify"
    )


def test_multiline_prose_without_explicit_arrows_is_not_retained():
    from sophyane.conversational_graph_session import (
        remember_grounded_process_context,
    )

    class Session:
        pass

    session = Session()

    response = """
1. Capability goal

A normal explanation.

2. Architecture

There are several independent components.

3. Verification

Each component is tested.
""".strip()

    assert (
        remember_grounded_process_context(
            session,
            response,
        )
        is False
    )
