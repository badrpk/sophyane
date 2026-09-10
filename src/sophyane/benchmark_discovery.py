"""Complementary benchmark selection.

Selection prefers benchmarks that collectively cover the requested
product model instead of selecting three near-duplicates.

Network/search/provider discovery is intentionally outside this module.
Callers supply structured candidates derived from trusted research.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sophyane.benchmark_contract import BenchmarkReference


@dataclass(frozen=True)
class BenchmarkCandidate:
    reference: BenchmarkReference

    domain_similarity: float
    workflow_similarity: float
    product_model_similarity: float
    design_quality: float

    def intrinsic_score(self) -> float:
        return (
            float(self.domain_similarity)
            + float(self.workflow_similarity)
            + float(self.product_model_similarity)
            + float(self.design_quality)
        )


def _capability_overlap(
    left: BenchmarkReference,
    right: BenchmarkReference,
) -> float:
    a = {
        item.strip().lower()
        for item in left.capabilities
        if item.strip()
    }

    b = {
        item.strip().lower()
        for item in right.capabilities
        if item.strip()
    }

    if not a or not b:
        return 0.0

    union = a | b

    if not union:
        return 0.0

    return len(a & b) / len(union)


def select_complementary_benchmarks(
    candidates: Iterable[BenchmarkCandidate],
    *,
    limit: int = 3,
    duplicate_penalty: float = 2.0,
    role_duplicate_penalty: float = 0.75,
) -> tuple[BenchmarkReference, ...]:
    pool = list(candidates)

    if limit <= 0 or not pool:
        return ()

    selected: list[BenchmarkCandidate] = []

    while pool and len(selected) < limit:
        best = None
        best_score = None

        for candidate in pool:
            score = candidate.intrinsic_score()

            for prior in selected:
                score -= (
                    duplicate_penalty
                    * _capability_overlap(
                        candidate.reference,
                        prior.reference,
                    )
                )

                if (
                    candidate.reference.role
                    == prior.reference.role
                ):
                    score -= role_duplicate_penalty

            if (
                best is None
                or score > best_score
                or (
                    score == best_score
                    and candidate.reference.benchmark_id
                    < best.reference.benchmark_id
                )
            ):
                best = candidate
                best_score = score

        selected.append(best)
        pool.remove(best)

    return tuple(
        item.reference
        for item in selected
    )


__all__ = [
    "BenchmarkCandidate",
    "select_complementary_benchmarks",
]
