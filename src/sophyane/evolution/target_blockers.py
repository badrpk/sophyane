"""Classification of authoritative baseline blockers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .target_authoritative_baseline import (
    AuthoritativeBaselineResult,
)


@dataclass(frozen=True)
class ValidationBlocker:
    target_name: str
    validator: str
    category: str
    detail: str


_PATTERNS = (
    (
        "environment-java",
        re.compile(
            r"JAVA_HOME is not set|"
            r"no ['\"]?java['\"]? command",
            re.I,
        ),
    ),
    (
        "dependency-node",
        re.compile(
            r"\bjest: not found\b|"
            r"\breact-scripts: not found\b",
            re.I,
        ),
    ),
    (
        "repository-missing-file",
        re.compile(
            r"No such file or directory|"
            r"failed to read .*Cargo\.toml",
            re.I | re.S,
        ),
    ),
    (
        "repository-manifest",
        re.compile(
            r"error inheriting .* workspace|"
            r"workspace\.package\.",
            re.I | re.S,
        ),
    ),
)


def classify_result(
    result: AuthoritativeBaselineResult,
) -> tuple[ValidationBlocker, ...]:
    blockers: list[
        ValidationBlocker
    ] = []

    for unavailable in result.unavailable:
        category = (
            "environment-python"
            if "pytest" in unavailable.casefold()
            else "validator-unavailable"
        )

        blockers.append(
            ValidationBlocker(
                target_name=result.target_name,
                validator="unavailable",
                category=category,
                detail=unavailable,
            )
        )

    for run in result.runs:
        if run.passed:
            continue

        body = (
            run.stderr
            + "\n"
            + run.stdout
        )

        category = "baseline-failure"

        for candidate, pattern in _PATTERNS:
            if pattern.search(
                body
            ):
                category = candidate
                break

        blockers.append(
            ValidationBlocker(
                target_name=result.target_name,
                validator=(
                    f"{run.kind}@"
                    f"{run.relative_cwd}"
                ),
                category=category,
                detail=(
                    body.strip()[-6000:]
                    or (
                        "validator returned "
                        f"{run.returncode}"
                    )
                ),
            )
        )

    return tuple(
        blockers
    )
