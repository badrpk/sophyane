"""Bounded deterministic novelty estimation.

This is a filtering signal, not proof of scientific novelty.
"""
from __future__ import annotations

import math
import re

from typing import Iterable


_WORD = re.compile(
    r"[A-Za-z][A-Za-z0-9_-]{2,63}"
)

_STOP = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "been",
    "can",
    "could",
    "does",
    "for",
    "from",
    "have",
    "into",
    "may",
    "new",
    "novel",
    "our",
    "that",
    "the",
    "their",
    "this",
    "using",
    "with",
}


def tokens(
    text: object,
) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _WORD.finditer(
            str(text or "")
        )
        if (
            match.group(0).casefold()
            not in _STOP
        )
    }


def jaccard_similarity(
    left: object,
    right: object,
) -> float:
    a = tokens(left)
    b = tokens(right)

    if not a and not b:
        return 1.0

    if not a or not b:
        return 0.0

    return (
        len(a & b)
        / len(a | b)
    )


def novelty_score(
    candidate: str,
    known_material: Iterable[str],
) -> tuple[float, str]:
    similarities = [
        jaccard_similarity(
            candidate,
            known,
        )
        for known in known_material
        if str(
            known
            or ""
        ).strip()
    ]

    if not similarities:
        return (
            1.0,
            "no_comparison_material",
        )

    maximum = max(
        similarities
    )

    score = max(
        0.0,
        min(
            1.0,
            1.0 - maximum,
        ),
    )

    return (
        round(
            score,
            6,
        ),
        (
            "max_known_similarity="
            f"{maximum:.6f}"
        ),
    )


def novelty_passes(
    score: float,
    *,
    threshold: float = 0.35,
) -> bool:
    if not math.isfinite(
        float(score)
    ):
        return False

    return (
        float(score)
        >= float(threshold)
    )


__all__ = [
    "jaccard_similarity",
    "novelty_passes",
    "novelty_score",
    "tokens",
]
