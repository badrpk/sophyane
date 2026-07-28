"""Final routing patch for semantic browser-game repair.

Complete HTML documents with semantic defects must be rewritten, not treated as
truncated byte streams.  This patch also recognises common vector-based Snake
reverse guards used by frontier models.
"""
from __future__ import annotations

import re
from typing import Any


def _vector_reverse_guard(source: str) -> bool:
    """Recognise safe opposite-direction checks beyond name-based templates."""
    compact = re.sub(r"\s+", "", source.lower())

    # Reject a new vector when it is the exact negative of the current vector.
    component_sum = bool(
        re.search(r"(?:new|next|pending)?(?:dir|direction)\.x\+(?:dir|direction)\.x(?:===?|!==?)0", compact)
        and re.search(r"(?:new|next|pending)?(?:dir|direction)\.y\+(?:dir|direction)\.y(?:===?|!==?)0", compact)
    )
    negated_components = bool(
        re.search(r"(?:new|next|pending)?(?:dir|direction)\.x(?:===?|!==?)-(?:dir|direction)\.x", compact)
        and re.search(r"(?:new|next|pending)?(?:dir|direction)\.y(?:===?|!==?)-(?:dir|direction)\.y", compact)
    )
    dot_product = bool(
        re.search(
            r"(?:new|next|pending)?(?:dir|direction)\.x\*(?:dir|direction)\.x\+"
            r"(?:new|next|pending)?(?:dir|direction)\.y\*(?:dir|direction)\.y(?:===?|<=)-1",
            compact,
        )
    )
    coordinate_pair = bool(
        re.search(r"\.x\s*===?\s*-\s*\w+\.x", source, re.I)
        and re.search(r"\.y\s*===?\s*-\s*\w+\.y", source, re.I)
    )
    return component_sum or negated_components or dot_product or coordinate_pair


def _semantic_rewrite_prompt(html: str, problem: str) -> str:
    return (
        "REPAIR A COMPLETE SELF-CONTAINED HTML PRODUCT. The document below is structurally complete, "
        "so do not continue or append bytes. Return ONE full replacement index.html only, beginning "
        "<!doctype html> and ending </html>. Preserve all working UI and game features. Fix this exact "
        f"semantic defect: {problem}. For Snake direction input, reject a requested direction when both "
        "components are the negatives of the current direction; queue at most one direction per game tick. "
        "Keep exactly one active timer or animation loop. No JSON, markdown, tools, or explanation.\n\n"
        f"CURRENT COMPLETE HTML:\n{html}"
    )


def install_snake_semantic_repair() -> None:
    from sophyane import adaptive_execution, game_validation
    from sophyane.html_repair_policy import is_structural_problem

    current_guard = game_validation._snake_has_reverse_guard
    if not getattr(current_guard, "_sophyane_vector_guard", False):
        def guard(source: str) -> bool:
            return current_guard(source) or _vector_reverse_guard(source)

        setattr(guard, "_sophyane_vector_guard", True)
        game_validation._snake_has_reverse_guard = guard

    current_prompt = adaptive_execution._html_continuation_prompt
    if not getattr(current_prompt, "_sophyane_semantic_rewrite", False):
        def repair_prompt(partial: str, problem: str = "") -> str:
            lower = partial.lower()
            complete = (
                ("<!doctype html" in lower or "<html" in lower)
                and "</html>" in lower
                and lower.count("<script") == lower.count("</script>")
                and lower.count("<body") == lower.count("</body>")
            )
            if complete and problem and not is_structural_problem(problem):
                return _semantic_rewrite_prompt(partial, problem)
            return current_prompt(partial, problem)

        setattr(repair_prompt, "_sophyane_semantic_rewrite", True)
        adaptive_execution._html_continuation_prompt = repair_prompt
