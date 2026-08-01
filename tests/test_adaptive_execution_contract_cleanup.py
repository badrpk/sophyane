from __future__ import annotations

from pathlib import Path


def test_adaptive_loop_has_no_dead_execution_contract_variable() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "adaptive_execution.py"
    ).read_text(encoding="utf-8")

    assert "execution_contract =" not in source

    # Repair prompts must still receive the deterministic execution policy.
    assert "def execution_prefix_for_repair" in source
    assert "+ execution_prefix_for_repair(request)" in source


def test_adaptive_execution_does_not_import_unused_json() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "adaptive_execution.py"
    ).read_text(encoding="utf-8")

    assert "\nimport json\n" not in f"\n{source}"
