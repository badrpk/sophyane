from pathlib import Path
from unittest.mock import patch

from sophyane.code_memory.sli_product_app_compose import (
    ProductDesign,
    compose_product_app,
    is_product_app_request,
    validate_product_document,
)
from sophyane.sli_graph import (
    SLIState,
    classify,
    run_sli_graph,
)


REQUEST = (
    "make a website that provide email service "
    "as good as gmail and it should offer all "
    "services that gmail offer"
)


def test_gmail_style_request_is_product_app() -> None:
    assert is_product_app_request(
        REQUEST
    )

    state = classify(
        SLIState(
            request=REQUEST,
            workspace=".",
        ),
        lambda _message:
            None,
    )

    assert (
        state.route
        ==
        "product_app"
    )


def test_email_product_has_required_behaviors(
    tmp_path: Path,
) -> None:
    from sophyane.code_memory import (
        sli_product_app_compose,
    )

    document = (
        sli_product_app_compose
        ._email_document(
            REQUEST,
            ProductDesign(
                generated=False,
                concept=
                    "Focused Mail Workspace",
                accent=
                    "#5b7cfa",
                accent2=
                    "#8d63ff",
                density=
                    "comfortable",
                mood=
                    "calm productivity",
            ),
        )
    )

    failures = validate_product_document(
        REQUEST,
        document,
    )

    assert failures == []

    assert "Inbox" in document
    assert "Starred" in document
    assert "Sent" in document
    assert "Drafts" in document
    assert "Archive" in document
    assert "Spam" in document
    assert "Trash" in document
    assert "Reply" in document
    assert "Forward" in document
    assert "localStorage" in document

    # The artifact must not falsely claim production transport.
    assert "SMTP/IMAP" in document


def test_product_synthesis_reports_success_only_after_browser_proof(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "sophyane.code_memory."
            "sli_product_app_compose._local_design",
            return_value=ProductDesign(
                generated=True,
                concept=
                    "Signal Inbox",
                accent=
                    "#4466ee",
                accent2=
                    "#7857dd",
                density=
                    "comfortable",
                mood=
                    "focused editorial productivity",
            ),
        ),
        patch(
            "sophyane.code_memory."
            "sli_product_app_compose._browser_validate",
            return_value=(
                True,
                (
                    "Browser file: test/index.html\n"
                    "HTTP verification: SHA-256 matched abcdef\n"
                    "Rendered evidence: PASS; "
                    "backend=termux-headless-shell-cdp"
                ),
            ),
        ),
    ):
        result = compose_product_app(
            REQUEST,
            tmp_path,
            acquisition_report=(
                "SLI strict acquisition failed.\n"
                "Success: False"
            ),
        )

    assert "Success: True" in result
    assert "LLM used: local-product-design" in result
    assert "Product family: email-workspace" in result
    assert (tmp_path / "index.html").is_file()


def test_failed_browser_proof_deletes_product_artifact(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "sophyane.code_memory."
            "sli_product_app_compose._local_design",
            return_value=ProductDesign(
                generated=False,
                concept=
                    "Focused Mail Workspace",
                accent=
                    "#5b7cfa",
                accent2=
                    "#8d63ff",
                density=
                    "comfortable",
                mood=
                    "calm productivity",
            ),
        ),
        patch(
            "sophyane.code_memory."
            "sli_product_app_compose._browser_validate",
            return_value=(
                False,
                "Rendered evidence: FAIL",
            ),
        ),
    ):
        result = compose_product_app(
            REQUEST,
            tmp_path,
            acquisition_report=(
                "strict acquisition failed"
            ),
        )

    assert "Success: False" in result

    assert not (
        tmp_path
        / "index.html"
    ).exists()


def test_graph_recovers_after_acquisition_failure(
    tmp_path: Path,
) -> None:
    failed_acquisition = (
        "SLI strict acquisition failed.\n"
        "No candidate satisfied both licence "
        "and behavioral validation.\n"
        "Files: none\n"
        "Success: False"
    )

    product_success = (
        "Sophyane product-app synthesis\n"
        "Product family: email-workspace\n"
        "Success: True"
    )

    with (
        patch(
            "sophyane.sli_graph.try_memory_router",
            side_effect=lambda state, _progress:
                _failed_state(
                    state,
                    failed_acquisition,
                ),
        ),
        patch(
            "sophyane.sli_graph.try_product_app",
            side_effect=lambda state, _progress:
                _successful_state(
                    state,
                    product_success,
                ),
        ),
    ):
        state = run_sli_graph(
            REQUEST,
            workspace=tmp_path,
            max_retries=1,
        )

    assert state.route == "product_app"
    assert state.success is True
    assert "Success: True" in state.report


def _failed_state(
    state,
    report,
):
    state.report = report
    state.success = False
    return state


def _successful_state(
    state,
    report,
):
    state.report = report
    state.success = True
    return state


def test_local_design_rejects_unsupported_gmail_equivalence() -> None:
    from sophyane.code_memory.sli_product_app_compose import (
        _design_claim_problem,
    )

    assert _design_claim_problem(
        "Focused Mail Workspace",
        "calm productivity",
    ) == ""

    assert (
        "unsupported capability claim"
        in _design_claim_problem(
            "All Gmail features",
            "modern",
        )
    )

    assert (
        "unsupported capability claim"
        in _design_claim_problem(
            "Mail",
            "as good as Gmail",
        )
    )


def test_mobile_product_contract_includes_reading_transition() -> None:
    from sophyane.code_memory import (
        sli_product_app_compose,
    )

    document = (
        sli_product_app_compose
        ._email_document(
            REQUEST,
            ProductDesign(
                generated=False,
                concept=
                    "Focused Mail Workspace",
                accent=
                    "#5b7cfa",
                accent2=
                    "#8d63ff",
                density=
                    "comfortable",
                mood=
                    "calm productivity",
            ),
        )
    )

    assert (
        '.compose-btn span'
        in document
    )

    assert (
        "backToListButton"
        in document
    )

    assert (
        "mobile-open"
        in document
    )

    assert (
        "mobile-hidden"
        in document
    )

    assert (
        'id="listPane"'
        in document
    )

    failures = validate_product_document(
        REQUEST,
        document,
    )

    assert (
        "mobile_message_reader"
        not in failures
    )

    assert (
        "compact_compose"
        not in failures
    )


def test_product_title_never_claims_gmail_equivalence() -> None:
    from sophyane.code_memory import (
        sli_product_app_compose,
    )

    document = (
        sli_product_app_compose
        ._email_document(
            REQUEST,
            ProductDesign(
                generated=False,
                concept=
                    "Focused Mail Workspace",
                accent=
                    "#5b7cfa",
                accent2=
                    "#8d63ff",
                density=
                    "comfortable",
                mood=
                    "calm productivity",
            ),
        )
    )

    title = document.split(
        "<title>",
        1,
    )[1].split(
        "</title>",
        1,
    )[0].casefold()

    assert "gmail" not in title
    assert "all features" not in title
    assert "all services" not in title


def test_product_pipeline_uses_dedicated_reuse_step() -> None:
    import inspect

    from sophyane import (
        sli_graph,
    )

    source = inspect.getsource(
        sli_graph.run_sli_graph
    )

    assert (
        '"product_app": ['
        in source
    )

    product_segment = source.split(
        '"product_app": [',
        1,
    )[1].split(
        "],",
        1,
    )[0]

    assert (
        "try_product_reuse"
        in product_segment
    )

    assert (
        "try_memory_router"
        not in product_segment
    )


def test_graph_product_recovery_uses_product_reuse(
    tmp_path: Path,
) -> None:
    failed_acquisition = (
        "SLI strict acquisition failed.\n"
        "Success: False"
    )

    product_success = (
        "Sophyane product-app synthesis\n"
        "Product family: email-workspace\n"
        "Success: True"
    )

    with (
        patch(
            "sophyane.sli_graph.try_product_reuse",
            side_effect=lambda state, _progress:
                _failed_state(
                    state,
                    failed_acquisition,
                ),
        ),
        patch(
            "sophyane.sli_graph.try_product_app",
            side_effect=lambda state, _progress:
                _successful_state(
                    state,
                    product_success,
                ),
        ),
        patch(
            "sophyane.sli_graph.try_memory_router",
            side_effect=AssertionError(
                "generic memory router must not "
                "run for product_app"
            ),
        ),
    ):
        state = run_sli_graph(
            REQUEST,
            workspace=tmp_path,
            max_retries=1,
        )

    assert state.success is True
    assert state.route == "product_app"
