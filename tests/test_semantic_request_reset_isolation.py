from types import SimpleNamespace

from sophyane.runtime_semantic_instruction import (
    apply_live_instruction,
    reset_semantic_request,
)


def test_reset_clears_stale_canonical_snapshot():
    tui = SimpleNamespace(active_request="new independent task")

    tui._semantic_original_request = "old audit task"
    tui._semantic_live_instructions = ["old instruction"]
    tui._sophyane_canonical_request_snapshot = (
        "old audit task plus old instruction"
    )

    reset_semantic_request(tui)

    assert tui._semantic_original_request == ""
    assert tui._semantic_live_instructions == []
    assert not getattr(
        tui,
        "_sophyane_canonical_request_snapshot",
        "",
    )
    assert tui.active_request == "new independent task"


def test_live_instruction_retained_within_same_task():
    tui = SimpleNamespace(active_request="inspect project")

    merged = apply_live_instruction(
        tui,
        "inspect project",
        "also inspect README.md",
    )

    assert "inspect project" in merged
    assert "also inspect README.md" in merged
    assert tui._sophyane_canonical_request_snapshot == merged


def test_reset_prevents_previous_task_instruction_reuse():
    tui = SimpleNamespace(active_request="inspect project")

    apply_live_instruction(
        tui,
        "inspect project",
        "also inspect README.md",
    )

    reset_semantic_request(tui)

    merged = apply_live_instruction(
        tui,
        "create a new calculator",
        "include tests",
    )

    assert "create a new calculator" in merged
    assert "include tests" in merged
    assert "also inspect README.md" not in merged
    assert "inspect project" not in merged
