"""Generic requirement/verification contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Requirement:
    id: str
    description: str
    kind: str = "behavior"
    required: bool = True


@dataclass(frozen=True)
class RequirementResult:
    requirement_id: str
    satisfied: bool
    evidence: str = ""
    problem: str = ""


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    results: tuple[RequirementResult, ...]
    problems: tuple[str, ...]


def build_report(
    requirements: Iterable[Requirement],
    results: Iterable[RequirementResult],
) -> VerificationReport:
    reqs = {
        item.id: item
        for item in requirements
    }

    by_id = {
        item.requirement_id: item
        for item in results
    }

    final: list[RequirementResult] = []
    problems: list[str] = []

    for requirement_id, requirement in reqs.items():
        result = by_id.get(requirement_id)

        if result is None:
            result = RequirementResult(
                requirement_id=requirement_id,
                satisfied=False,
                problem="requirement was not verified",
            )

        final.append(result)

        if (
            requirement.required
            and not result.satisfied
        ):
            problems.append(
                result.problem
                or requirement.description
            )

    return VerificationReport(
        ok=not problems,
        results=tuple(final),
        problems=tuple(problems),
    )
