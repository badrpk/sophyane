from __future__ import annotations

from pathlib import Path


def test_adaptive_loop_has_deterministic_post_bundle_verification() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "adaptive_execution.py"
    ).read_text(encoding="utf-8")

    # The post-bundle workflow must progress deterministically through an
    # isolated environment, dependency installation and project testing.
    assert 'deterministic_verification_stage = ""' in source
    assert 'deterministic_verification_stage = "prepare"' in source
    assert 'deterministic_verification_stage = "install"' in source
    assert 'deterministic_verification_stage = "test"' in source

    assert "-m venv .venv" in source
    assert "-m pip install" in source
    assert "-m pytest -q" in source

    assert '"timeout": 900' in source
    assert '"timeout": 300' in source

    assert "deterministic_post_bundle_verification" in source
    assert "dependency installation failed" in source
    assert "Project implementation and verification completed" in source
