from __future__ import annotations

from pathlib import Path


def test_execution_runtime_accepts_per_action_timeout() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "execution_runtime.py"
    ).read_text(encoding="utf-8")

    assert "timeout: int = 60" in source
    assert 'action.get("timeout") or 60' in source
    assert "min(requested_timeout, 1800)" in source
    assert "timeout=timeout" in source
    assert "elapsed >= timeout" in source
    assert "timed out after {timeout}s" in source
    assert "timed out after 60s" not in source
