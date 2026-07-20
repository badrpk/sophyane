"""Stop generic tool execution after browser-specific validation has failed.

Browser requests are handled by the dedicated HTML generation and validation path. If
that path exhausts bounded repair, falling through to the generic JSON action loop can
write an unvalidated ``index.html`` from the same failed response. This patch converts
that terminal ``None`` into an explicit failure result so the adaptive loop returns
immediately and preserves diagnostics.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


FAILURE_RESULT = (
    "Execution stopped safely: browser validation failed and no usable HTML artifact "
    "was produced. Generic write_file and browser actions were not executed."
)


def install_browser_failure_gate() -> None:
    """Make browser validation failure terminal for the current execution request."""
    from sophyane import adaptive_execution as adaptive

    current = adaptive._one_shot_browser_artifact
    if getattr(current, "_sophyane_browser_failure_gate", False):
        return

    def gated(*, ask: Callable[[str], Any], original_request: str,
              workspace: Path, progress: Callable[[str], None]) -> str | None:
        result = current(
            ask=ask,
            original_request=original_request,
            workspace=workspace,
            progress=progress,
        )
        if result is not None:
            return result

        partial = workspace / ".sophyane-partial-index.html"
        if partial.is_file():
            progress(
                "Browser validation failed terminally; blocked generic write_file, "
                "open_browser, and queued tool actions for this request"
            )
        else:
            progress(
                "Browser generation produced no validated artifact; blocked generic "
                "tool fallback for this request"
            )
        return FAILURE_RESULT

    setattr(gated, "_sophyane_browser_failure_gate", True)
    adaptive._one_shot_browser_artifact = gated
