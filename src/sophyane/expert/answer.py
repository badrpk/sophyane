"""Hybrid tough-question answering: expert pack + optional local/frontier LLM."""

from __future__ import annotations

import re
from typing import Any, Callable

from sophyane.expert.knowledge import expert_answer_for

GenerateFn = Callable[[str, str], str]

SYSTEM = (
    "You are Sophyane, a rigorous harness engineering and coding expert. "
    "Answer concisely with concrete mechanisms, failure modes, and implementation "
    "details. Prefer lists and key terms: plan, verify, fallback, sandbox, tests."
)


def score_answer(answer: str, keys: list[str], *, min_len: int = 80) -> dict[str, Any]:
    text = (answer or "").lower()
    hit = [k for k in keys if k.lower() in text]
    key_score = len(hit) / max(1, len(keys))
    len_score = min(1.0, len(answer or "") / float(min_len))
    refuse = bool(re.search(r"\b(i cannot|as an ai|no idea)\b", text))
    total = 0.75 * key_score + 0.25 * len_score
    if refuse:
        total *= 0.3
    return {
        "score": round(total, 3),
        "passed": total >= 0.45 and len(hit) >= max(1, len(keys) // 3),
        "keys_hit": hit,
        "keys_miss": [k for k in keys if k.lower() not in text],
        "length": len(answer or ""),
    }


def answer_tough_question(
    question: str,
    *,
    qid: int | None = None,
    cat: str | None = None,
    keys: list[str] | None = None,
    generate: GenerateFn | None = None,
    mode: str = "hybrid",
) -> dict[str, Any]:
    """Answer a hard harness/coding question."""
    expert = expert_answer_for(question, qid=qid, cat=cat)
    llm_text = ""
    mode = (mode or "hybrid").lower()

    if mode in {"llm", "hybrid"} and generate is not None:
        prompt = question
        if mode == "hybrid":
            prompt = (
                f"Question:\n{question}\n\n"
                f"Authoritative notes (use and expand, do not contradict):\n{expert[:1200]}\n\n"
                "Write a clear final answer for an expert engineer."
            )
        try:
            llm_text = generate(prompt, SYSTEM)
        except Exception as error:  # noqa: BLE001
            llm_text = f"[llm_error] {error}"

    if mode == "expert" or not llm_text or llm_text.startswith("[llm_error]"):
        final = expert
        used = "expert"
    elif mode == "llm":
        final = llm_text
        used = "llm"
    else:
        stripped = llm_text.strip()
        # Exact and concise replies are often the strongest answer for local models.
        # Do not discard successful outputs such as LOCAL_OK, yes/no, identifiers,
        # short facts, or requested one-line responses merely because they are short.
        if stripped and len(stripped) <= 64:
            final = stripped
            used = "llm_short"
        elif score_answer(stripped, keys or []).get("score", 0) >= 0.35:
            final = expert + "\n\nAdditional detail:\n" + stripped
            used = "hybrid"
        else:
            final = expert
            used = "expert_fallback"

    keys = keys or []
    scored = score_answer(final, keys) if keys else {
        "score": 1.0,
        "passed": True,
        "keys_hit": [],
        "keys_miss": [],
        "length": len(final),
    }
    return {
        "ok": True,
        "mode": mode,
        "used": used,
        "answer": final,
        "expert": expert,
        "llm": llm_text,
        "scoring": scored,
    }
