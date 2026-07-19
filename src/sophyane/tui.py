"""Compatibility entry point for the observable Sophyane terminal UI."""
from __future__ import annotations

from typing import Any


def run_grok_style_tui(*, config: dict[str, Any], verbose: bool) -> int:
    """Launch the observable TUI with real structured-action execution."""
    from sophyane.tui_v2 import run_observable_tui

    return run_observable_tui(config=config, verbose=verbose)
