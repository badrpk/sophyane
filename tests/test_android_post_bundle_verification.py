from __future__ import annotations

from pathlib import Path


def test_post_bundle_verification_is_staged_and_isolated() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "adaptive_execution.py"
    ).read_text(encoding="utf-8")

    assert 'deterministic_verification_stage = "prepare"' in source
    assert 'deterministic_verification_stage = "install"' in source
    assert 'deterministic_verification_stage = "test"' in source

    assert "-m venv .venv" in source
    assert "/ \".venv\" / \"bin\" / \"python\"" in source

    assert '"timeout": 900' in source
    assert '"timeout": 300' in source

    assert "dependency installation failed" in source
    assert "project test suite" in source
