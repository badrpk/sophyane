from __future__ import annotations

from sophyane.tui_v2 import _friendly_progress_event, _source_label


def test_source_labels_hide_internal_worker_ids() -> None:
    assert _source_label("harness:codex_cli") == "Codex CLI"
    assert _source_label("api:gemini:external_api") == "Gemini"
    assert _source_label("local") == "Local GGUF"


def test_progress_events_render_as_capability_dashboard() -> None:
    assert _friendly_progress_event("ORIGINAL_OBJECTIVE_HASH=abc") is None
    assert _friendly_progress_event("ELIGIBLE_SOURCES=local:local_gguf") is None
    assert _friendly_progress_event("Adaptive race round 1/3") == (
        "── Round 1 of 3 · finding the best route"
    )
    assert _friendly_progress_event(
        "Race harness:agy worker: creating isolated provider"
    ) is None
    assert _friendly_progress_event(
        "RACE_WAITING_SECONDS=20;REMAINING_SECONDS=30"
    ) == "◌ Still working · 20s elapsed · timeout in 30s"
    assert _friendly_progress_event(
        "STARTED_SOURCES=harness:agy:external_harness,"
        "harness:codex_cli:external_harness,local:local_gguf"
    ) == "◌ Racing  Antigravity · Codex CLI · Local GGUF"
    assert _friendly_progress_event(
        "Race harness:codex_cli worker: requesting proposal via codex_cli"
    ) == "◌ Codex CLI · working"
    assert _friendly_progress_event(
        "Race harness:agy: route agy complete · tokens n/a"
    ) == "✓ Antigravity · response received"
    assert _friendly_progress_event(
        "REJECTED_UNUSABLE_SOURCES=api:gemini,browser:nifdu_browser,local"
    ) == "○ Unavailable  Gemini · ChatGPT Browser · Local GGUF"
