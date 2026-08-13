from __future__ import annotations

import pytest

from sophyane.sli_graph import (
    SLIState,
    classify,
)


def route(request: str) -> str:
    state = SLIState(
        request=request,
        workspace=".",
    )

    result = classify(
        state,
        lambda _message: None,
    )

    return result.route


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        (
            "Create a web app dashboard with interactive controls.",
            "product_app",
        ),
        (
            "Build a browser app for monitoring servers.",
            "product_app",
        ),
        (
            "Develop a customer management web application dashboard.",
            "product_app",
        ),
        (
            "Build an email app with inbox and compose views.",
            "product_app",
        ),
    ),
)
def test_browser_products_retain_product_routes(
    case: str,
    expected: str,
) -> None:
    assert route(case) == expected


@pytest.mark.parametrize(
    "case",
    (
        (
            "Instruct an AI harness to parse incoming raw payload examples "
            "or rough functional descriptions, autonomously derive strict "
            "JSON schemas or OpenAPI specifications, and generate functional "
            "backend mocking stubs or test client scripts."
        ),
        (
            "Generate an OpenAPI specification and backend stubs plus "
            "a test client script."
        ),
        (
            "Build a REST API for managing users and generate a client SDK."
        ),
        (
            "Create a FastAPI backend with REST endpoints, request "
            "validation, persistent storage, and integration tests."
        ),
        (
            "Create a Python CLI that converts CSV to JSON."
        ),
        (
            "Implement a Python library for retrying HTTP requests."
        ),
    ),
)
def test_non_browser_software_is_not_product_app(
    case: str,
) -> None:
    assert route(case) != "product_app"


def test_openapi_benchmark_does_not_require_index_html_route() -> None:
    request = (
        "Instruct an AI harness to parse incoming raw payload examples or "
        "rough functional descriptions, autonomously derive strict JSON "
        "schemas or OpenAPI specifications, and generate functional backend "
        "mocking stubs or test client scripts."
    )

    assert route(request) == "software_artifact"


def test_existing_repair_request_remains_harness_execution() -> None:
    request = (
        "Repair the existing production code after a pytest "
        "test failure and re-run verification."
    )

    assert route(request) == "harness_execution"
