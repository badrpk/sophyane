from __future__ import annotations

from pathlib import Path

import pytest

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
        "open this in browser",
        "open it",
        "preview it",
        "show the output",
        "view the result",
        "launch the website",
        "run the game",
        "test the html",
        "reopen this in browser",
    ),
)
def test_real_preview_commands_match(
    case: str,
) -> None:
    assert router._is_preview(case) is True


@pytest.mark.parametrize(
    "case",
    (
        FAILED_REQUEST,
        "Replay the failed thread schedule bit-for-bit.",
        "Implement deterministic replay.",
        "Write a replay engine in Python.",
        "Explain bit manipulation.",
        "Design a test runner.",
        "Run unit tests for the Python module.",
        "Show a C++ implementation example.",
        "Provide code to replay API responses.",
    ),
)
def test_non_browser_code_requests_do_not_match_preview(
    case: str,
) -> None:
    assert router._is_preview(case) is False


def test_failed_request_does_not_call_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Leave a stale HTML file intentionally. The software request must
    # not preview it.
    stale = tmp_path / "index.html"
    stale.write_text(
        "<!doctype html><title>OLD CATS SITE</title>",
        encoding="utf-8",
    )

    called = []

    import sophyane.sli_capability_engine as engine

    def forbidden_preview(*args, **kwargs):
        called.append("preview")
        raise AssertionError(
            "software request attempted stale browser preview"
        )

    monkeypatch.setattr(
        engine,
        "preview_sli_artifact",
        forbidden_preview,
    )

    result = router.try_sli_chunks(
        FAILED_REQUEST,
        workspace=tmp_path,
        progress=lambda _message: None,
    )

    assert called == []
    assert "OLD CATS SITE" not in str(result)
