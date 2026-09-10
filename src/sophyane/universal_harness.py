"""Generic execution-harness integration helpers.

This module contains no product-specific semantics.  It only coordinates
repository context, artifact validation, and requirement verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sophyane.artifact_validation import (
    ArtifactValidationResult,
    validate_artifacts,
)
from sophyane.repository_discovery import repository_context
from sophyane.verification_contract import (
    Requirement,
    RequirementResult,
    VerificationReport,
    build_report,
    require_verified,
)


@dataclass(frozen=True)
class UniversalHarnessResult:
    repository_context: str
    artifact_validation: ArtifactValidationResult
    verification: VerificationReport


def build_repository_context(
    request: str,
    *,
    limit: int = 5,
) -> str:
    """Return compact read-only repository evidence."""
    return repository_context(
        request,
        limit=limit,
    )


def validate_task_artifacts(
    paths: Iterable[str | Path],
    *,
    workspace: str | Path,
) -> ArtifactValidationResult:
    """Apply artifact-characteristic validators with workspace containment."""
    return validate_artifacts(
        paths,
        workspace=workspace,
    )


def verify_task_requirements(
    requirements: Iterable[Requirement],
    results: Iterable[RequirementResult],
    *,
    enforce: bool = True,
) -> VerificationReport:
    """Build a generic verification report and optionally enforce it."""
    report = build_report(
        requirements,
        results,
    )

    if enforce:
        require_verified(report)

    return report
