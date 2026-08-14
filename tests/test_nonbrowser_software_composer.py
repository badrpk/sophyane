from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.sli_semantic_intelligence import build_semantic_plan


JOURNAL_REQUEST = (
    "Design a lightweight execution journaling mechanism in "
    "Python/C++ that captures non-deterministic async API "
    "responses and thread interleavings. Provide a complete "
    "code snippet showing how to replay a failed execution path "
    "with bit-for-bit precision to isolate a race condition."
)


def capabilities(text: str) -> set[str]:
    return {
        item.name
        for item in build_semantic_plan(text).capabilities
    }


def test_external_api_response_request_does_not_require_http_endpoint():
    assert "http_endpoint" not in capabilities(
        "Write Python code that records responses returned by an external API."
    )


def test_journaling_request_does_not_require_http_endpoint():
    assert "http_endpoint" not in capabilities(
        JOURNAL_REQUEST
    )


@pytest.mark.parametrize(
    "case",
    (
        "Build a Python REST API with GET and POST endpoints.",
        "Create a FastAPI service with API endpoints.",
        "Build an API endpoint that accepts POST requests.",
    ),
)
def test_real_api_server_requests_keep_http_endpoint(
    case: str,
) -> None:
    assert "http_endpoint" in capabilities(case)


def test_compose_source_contains_no_forced_browser_true():
    source = Path(
        "src/sophyane/code_memory/compose.py"
    ).read_text(encoding="utf-8")

    assert "or True else" not in source


def test_non_web_route_is_not_selected_from_html_chunks():
    source = Path(
        "src/sophyane/code_memory/compose.py"
    ).read_text(encoding="utf-8")

    assert (
        'if _looks_web(message) or any(c.language == "html"'
        not in source
    )
