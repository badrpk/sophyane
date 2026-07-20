"""Durable recovery for provider HTML that is repeatedly truncated.

The best partial document is preserved in the workspace and continuation retries are
bounded by progress, character growth, and attempt count instead of a hard two tries.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


PARTIAL_NAME = ".sophyane-partial-index.html"
MAX_CONTINUATIONS = 6
MAX_TOTAL_CHARS = 24000
MIN_PROGRESS = 24


def _response_text(response: Any) -> str:
    return str(getattr(response, "text", response) or "")


def _finish_reason(response: Any) -> str:
    for name in ("finish_reason", "finishReason", "stop_reason", "stopReason"):
        value = getattr(response, name, None)
        if value:
            return str(value)
    candidates = getattr(response, "candidates", None)
    if candidates:
        value = getattr(candidates[0], "finish_reason", None) or getattr(candidates[0], "finishReason", None)
        if value:
            return str(value)
    return "unknown"


def install_browser_partial_recovery() -> None:
    """Replace the one-shot browser path with progress-aware partial recovery."""
    from sophyane import adaptive_execution as adaptive

    current = adaptive._one_shot_browser_artifact
    if getattr(current, "_sophyane_partial_recovery", False):
        return

    def recovered(*, ask: Callable[[str], Any], original_request: str,
                  workspace: Path, progress: Callable[[str], None]) -> str | None:
        target = workspace / "index.html"
        partial_file = workspace / PARTIAL_NAME
        existing = ""
        if target.is_file():
            try:
                existing = target.read_text(encoding="utf-8")
            except OSError:
                existing = ""

        progress("Requesting one-shot provider-generated HTML edit" if existing else
                 "Requesting one-shot provider-generated HTML artifact")
        response = ask(adaptive._raw_html_prompt(original_request, existing))
        raw = _response_text(response)
        reason = _finish_reason(response)
        if reason != "unknown":
            progress(f"Provider finish reason: {reason}")

        html = adaptive._extract_html(raw)
        partial = adaptive._extract_partial_html(raw)
        if partial:
            partial_file.write_text(partial, encoding="utf-8")

        attempts = 0
        stagnant = 0
        while attempts < MAX_CONTINUATIONS:
            problem = adaptive._validate_html(html, original_request) if html is not None else "document has no closing </html>"
            if html is not None and not problem:
                break
            if partial is None and html is not None:
                partial = adaptive._prepare_for_continuation(html)
            elif partial is not None:
                partial = adaptive._prepare_for_continuation(partial)
            if partial is None or len(partial) >= MAX_TOTAL_CHARS:
                break

            attempts += 1
            before = len(partial)
            partial_file.write_text(partial, encoding="utf-8")
            progress(
                f"Repairing incomplete provider HTML ({attempts}/{MAX_CONTINUATIONS}; "
                f"{before} characters preserved): {problem}"
            )
            response = ask(adaptive._html_continuation_prompt(partial, problem))
            continuation = _response_text(response)
            reason = _finish_reason(response)
            if reason != "unknown":
                progress(f"Continuation finish reason: {reason}")
            candidate = adaptive._join_html_continuation(partial, continuation)
            growth = len(candidate) - before
            if growth < MIN_PROGRESS:
                stagnant += 1
                progress(f"Continuation made insufficient progress ({growth} characters)")
            else:
                stagnant = 0
            partial = candidate
            partial_file.write_text(partial, encoding="utf-8")
            html = adaptive._extract_html(partial)
            if stagnant >= 2:
                progress("Stopping continuation because the provider stopped making progress")
                break

        if html is None:
            if partial:
                partial_file.write_text(partial, encoding="utf-8")
                progress(f"Preserved incomplete HTML at {partial_file} ({len(partial)} characters)")
            return None

        problem = adaptive._validate_html(html, original_request)
        if problem:
            partial_file.write_text(html, encoding="utf-8")
            progress(f"Provider HTML rejected after bounded recovery: {problem}")
            progress(f"Preserved rejected HTML at {partial_file}")
            return None

        temporary = target.with_suffix(".html.tmp")
        temporary.write_text(html, encoding="utf-8")
        temporary.replace(target)
        partial_file.unlink(missing_ok=True)
        progress(f"Wrote {target} ({target.stat().st_size} bytes)")
        from sophyane import execution_runtime as runtime
        progress("Browser artifact passed structural verification; opening demo")
        ok, result = runtime.execute_action({"type": "open_browser"}, workspace, progress)
        if not ok:
            return None
        return (
            "Updated and opened the provider-generated browser project.\n\n"
            f"Workspace: {workspace}\nFile: index.html\n\nExecution evidence:\n"
            f"- index.html exists ({target.stat().st_size} bytes)\n"
            f"- Recovered with {attempts} continuation attempt(s)\n"
            "- HTML body/script structure verified\n"
            "- JavaScript bracket structure verified\n"
            f"- {result}"
        )

    recovered._sophyane_partial_recovery = True  # type: ignore[attr-defined]
    adaptive._one_shot_browser_artifact = recovered
