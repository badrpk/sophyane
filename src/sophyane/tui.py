"""Compatibility entry point for the observable Sophyane terminal UI."""
from __future__ import annotations

from typing import Any


def run_grok_style_tui(*, config: dict[str, Any], verbose: bool) -> int:
    """Launch the observable TUI with provider-driven adaptive execution."""
    from sophyane.adaptive_execution import install, run_adaptive_loop

    # Patch the source runtime first, then bind the adaptive function directly into
    # tui_v2 as well. The explicit assignment remains correct even when tui_v2 was
    # imported and cached earlier during startup.
    install()
    from sophyane import tui_v2

    tui_v2.run_structured_loop = run_adaptive_loop
    return tui_v2.run_observable_tui(config=config, verbose=verbose)
