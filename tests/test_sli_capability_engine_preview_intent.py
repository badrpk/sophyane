from __future__ import annotations

from pathlib import Path

import pytest

import sophyane.sli_capability_engine as engine
import sophyane.sli_chunk_router as router


FAILED_REQUEST = (
    "Design a lightweight execution journaling mechanism in "
    "Python/C++ that captures non-deterministic async API "
    "responses and thread interleavings. Provide a complete "
    "code snippet showing how to replay a failed execution path "
    "with bit-for-bit precision to isolate a race condition."
)


@pytest.mark.parametrize(
    "case",
    (
        "open it",
        "open this in browser",
        "preview this",
        "show the output",
        "view the result",
        "launch the website",
        "run the game",
        "test the html",
        "reopen this in browser",
    ),
)
def test_real_preview_requests_match(
    case: str,
) -> None:
    assert engine.is_preview_request(case) is True


@pytest.mark.parametrize(
    "case",
    (
        FAILED_REQUEST,
        "Replay the failed thread schedule bit-for-bit.",
        "Implement deterministic replay.",
        "Write a replay engine in Python.",
        "Run unit tests for the Python module.",
        "Test the Python module with pytest.",
        "Show a C++ implementation example.",
        "Provide code to replay API responses.",
        "Design a test runner.",
    ),
)
def test_non_preview_software_requests_do_not_match(
    case: str,
) -> None:
    assert engine.is_preview_request(case) is False


@pytest.mark.parametrize(
    "case",
    (
        "open it",
        "open this in browser",
        "show the output",
        FAILED_REQUEST,
        "Replay the failed thread schedule bit-for-bit.",
        "Run unit tests for the Python module.",
    ),
)
def test_engine_and_chunk_router_agree(
    case: str,
) -> None:
    assert (
        engine.is_preview_request(case)
        == router._is_preview(case)
    )


def test_handle_sli_request_does_not_preview_stale_html(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stale = tmp_path / "index.html"
    stale.write_text(
        "<!doctype html><title>OLD CATS SITE</title>",
        encoding="utf-8",
    )

    preview_calls = []

    def forbidden_preview(*args, **kwargs):
        preview_calls.append("preview")
        raise AssertionError(
            "stale browser artifact was previewed"
        )

    monkeypatch.setattr(
        engine,
        "preview_sli_artifact",
        forbidden_preview,
    )

    # Avoid asserting that current no-LLM generation itself succeeds.
    # We only care that this request does NOT go through preview.
    try:
        engine.handle_sli_request(
            FAILED_REQUEST,
            workspace=tmp_path,
            progress=lambda _message: None,
        )
    except Exception:
        pass

    assert preview_calls == []
