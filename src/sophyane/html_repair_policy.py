"""Repair policy for provider-generated browser artifacts.

Structural truncation may be continued. Semantic failures must never append code
outside an already closed document; they are handled by a complete rewrite.
"""
from __future__ import annotations

import re
from typing import Callable


_STRUCTURAL_PREFIXES = (
    "document has no closing </html>",
    "HTML structure is incomplete",
    "HTML body tag is not closed",
    "HTML script tag is not closed",
    "JavaScript has an unmatched",
    "JavaScript has ",
    "JavaScript ends inside",
)


def is_structural_problem(problem: str) -> bool:
    return any(problem.startswith(prefix) for prefix in _STRUCTURAL_PREFIXES)


def install_html_repair_policy() -> None:
    """Patch continuation preparation so appended output remains inside the body."""
    from sophyane import adaptive_execution as adaptive

    current: Callable[[str], str] = adaptive._prepare_for_continuation
    if getattr(current, "_sophyane_safe_continuation", False):
        return

    def prepare(html: str) -> str:
        value = html.rstrip()
        value = re.sub(r"</html>\s*$", "", value, flags=re.I)
        value = re.sub(r"</body>\s*$", "", value, flags=re.I)
        return value.rstrip()

    setattr(prepare, "_sophyane_safe_continuation", True)
    adaptive._prepare_for_continuation = prepare

    original_prompt = adaptive._html_continuation_prompt

    def guarded_prompt(partial: str, problem: str = "") -> str:
        if problem and not is_structural_problem(problem):
            return (
                "Rewrite the following complete index.html as one corrected self-contained document. "
                f"Fix this functional problem: {problem}. Preserve the UI and working features. "
                "Output raw HTML only, beginning <!doctype html> and ending </html>. "
                "Do not append a fragment and do not use markdown.\n"
                f"CURRENT HTML:\n{partial[:7000]}"
            )
        return original_prompt(partial, problem)

    adaptive._html_continuation_prompt = guarded_prompt

    original_join = adaptive._join_html_continuation

    def guarded_join(partial: str, continuation: str) -> str:
        lower = (continuation or "").lower()
        if "<!doctype html" in lower or "<html" in lower:
            extracted = adaptive._extract_html(continuation)
            if extracted is not None:
                return extracted
        return original_join(partial, continuation)

    adaptive._join_html_continuation = guarded_join
