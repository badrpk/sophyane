from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "src"
    / "sophyane"
    / "runtime_provider_context_patch.py"
)


def _source() -> str:
    return SOURCE.read_text(
        encoding="utf-8",
    )


def test_provider_context_does_not_clamp_timeout_to_six_seconds() -> None:
    text = _source()

    assert "min(float(timeout), 6.0)" not in text


def test_provider_context_preserves_bounded_caller_timeout() -> None:
    text = _source()

    assert "timeout = max(1.0, float(timeout))" in text


def test_provider_context_still_enforces_a_real_deadline() -> None:
    text = _source()

    assert "deadline = started + float(timeout)" in text
    assert "time.monotonic() >= deadline" in text
    assert "cancel_generation(generation)" in text
    assert "did not respond within" in text


def test_provider_context_keeps_late_result_rejection() -> None:
    text = _source()

    assert "completed_at >= deadline" in text
    assert "response exceeded" in text
    assert "was discarded" in text
