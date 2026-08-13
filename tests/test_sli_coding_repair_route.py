from __future__ import annotations

from pathlib import Path

from sophyane.sli_capability_engine import (
    is_web_request,
)

from sophyane.sli_harness_orchestrator import (
    is_harness_execution_request,
)


LIVE_REPAIR_REQUEST = """
Repair the existing Python project.

The existing tests are authoritative and must not be modified.

Run the existing pytest suite, inspect the failure, repair only
the production code needed to satisfy the tests, and re-run
deterministic verification until the project is green.
""".strip()


def test_live_repair_is_nonweb_harness():
    assert (
        is_web_request(
            LIVE_REPAIR_REQUEST
        )
        is False
    )

    assert (
        is_harness_execution_request(
            LIVE_REPAIR_REQUEST
        )
        is True
    )


def test_general_pytest_repair_is_nonweb_harness():
    request = (
        "Run pytest, inspect the traceback, "
        "repair the production source file "
        "and rerun verification."
    )

    assert (
        is_web_request(
            request
        )
        is False
    )

    assert (
        is_harness_execution_request(
            request
        )
        is True
    )


def test_website_is_still_web_request():
    request = (
        "Build a website with HTML, CSS "
        "and JavaScript."
    )

    assert (
        is_web_request(
            request
        )
        is True
    )


def test_dashboard_is_still_web_request():
    request = (
        "Create a web app dashboard "
        "with interactive controls."
    )

    assert (
        is_web_request(
            request
        )
        is True
    )


def test_sli_graph_retains_distinct_product_and_harness_routes():
    source = Path(
        "src/sophyane/sli_graph.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"product_app"'
        in source
    )

    assert (
        '"harness_execution"'
        in source
    )

    assert (
        "is_harness_execution_request"
        in source
    )
