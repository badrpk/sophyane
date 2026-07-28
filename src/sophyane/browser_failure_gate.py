"""Stop generic tool execution after browser-specific validation has failed.

Browser requests are handled by the dedicated HTML generation and validation path. If
that path exhausts bounded repair or the provider raises, falling through to the generic
JSON action loop can drift into unrelated Python files or execute stale planner actions.
This patch makes browser failure terminal while preserving the original diagnostics.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


FAILURE_RESULT = (
    "Execution stopped safely: browser validation failed and no usable HTML artifact "
    "was produced. Generic write_file, Python, and browser actions were not executed."
)


def install_browser_failure_gate() -> None:
    """Make every unvalidated browser-generation outcome terminal for the request."""
    from sophyane import adaptive_execution as adaptive

    current = adaptive._one_shot_browser_artifact
    if getattr(current, "_sophyane_browser_failure_gate", False):
        return

    def gated(*, ask: Callable[[str], Any], original_request: str,
              workspace: Path, progress: Callable[[str], None], **kwargs: Any) -> str | None:
        try:
            result = current(
                ask=ask,
                original_request=original_request,
                workspace=workspace,
                progress=progress,
                **kwargs,
            )
        except Exception as error:  # noqa: BLE001 - provider errors are terminal here
            progress(
                "Browser provider path failed terminally; blocked generic execution "
                f"fallback: {type(error).__name__}: {error}"
            )
            return FAILURE_RESULT + f"\nCause: {type(error).__name__}: {error}"

        if result is not None:
            return result

        partial = workspace / ".sophyane-partial-index.html"
        if partial.is_file():
            progress(
                "Browser validation failed terminally; blocked generic write_file, "
                "Python, open_browser, and queued tool actions for this request"
            )
        else:
            progress(
                "Browser generation produced no validated artifact; blocked generic "
                "tool fallback for this request"
            )
        return FAILURE_RESULT

    setattr(gated, "_sophyane_browser_failure_gate", True)
    adaptive._one_shot_browser_artifact = gated
