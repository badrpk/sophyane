"""Validation gate for promoting generated artifacts into SLI memory.

Promotion requires:
* a positive success report;
* no failure marker;
* at least one real product artifact;
* behavior validation for HTML;
* compilation for Python;
* structural parsing for JSON;
* strict licence confirmation when the report references an acquired repo.

The gate does not execute generated or downloaded source.
"""
from __future__ import annotations

import json
import py_compile
import re

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CONTROL_FILES = {
    "request.txt",
    "report.txt",
    "event.json",
    "traceback.txt",
    "stdout.txt",
    "stderr.txt",
    "metadata.json",
}


FAILURE_MARKERS = (
    "success: false",
    "validation: failed",
    "strict acquisition failed",
    "did not meet",
    "could not find compatible chunks",
    "no relevant html",
    "no candidate satisfied",
    "unresolved interfaces",
    "report contains a failure marker",
    "no invalid artifact",
    "traceback",
)


POSITIVE_MARKERS = (
    "success: true",
    "validation: passed",
    "strict behavioral validation: passed",
    "grounded contract smoke test: passed",
    "behavior checks:",
    "component-linker composer",
    "topic-site composer",
    "python-harness composer",
)


INTERNET_SOURCE_MARKERS = (
    "source repository:",
    "repository accepted:",
    "grounded internet acquisition",
    "internet-acquired",
)


LICENCE_PASS_MARKERS = (
    "strict licence gate: passed",
    "licence=mit",
    "licence=apache-2.0",
    "licence=bsd-2-clause",
    "licence=bsd-3-clause",
    "licence=isc",
    "licence=mpl-2.0",
    "licence=unlicense",
    "licence=0bsd",
    "licence=cc0-1.0",
)


@dataclass(frozen=True)
class PromotionValidation:
    ok: bool
    reason: str
    files: tuple[str, ...]
    checks: tuple[str, ...]


def _normalise_report(
    report: object,
) -> str:
    return str(
        report or ""
    ).strip()


def report_is_successful(
    report: object,
) -> tuple[bool, str]:
    text = _normalise_report(
        report
    )

    low = text.lower()

    if not text:
        return (
            False,
            "empty success report",
        )

    failure = next(
        (
            marker
            for marker in FAILURE_MARKERS
            if marker in low
        ),
        None,
    )

    if failure:
        return (
            False,
            f"report contains failure marker: {failure}",
        )

    if not any(
        marker in low
        for marker in POSITIVE_MARKERS
    ):
        return (
            False,
            "report has no positive validation marker",
        )

    acquired = any(
        marker in low
        for marker in INTERNET_SOURCE_MARKERS
    )

    if acquired and not any(
        marker in low
        for marker in LICENCE_PASS_MARKERS
    ):
        return (
            False,
            "internet-acquired artifact lacks strict licence confirmation",
        )

    return (
        True,
        "success report accepted",
    )


def product_files(
    workspace: Path,
) -> list[Path]:
    workspace = Path(
        workspace
    ).expanduser().resolve()

    if not workspace.is_dir():
        return []

    output: list[Path] = []

    for path in workspace.rglob("*"):
        if not path.is_file():
            continue

        relative = path.relative_to(
            workspace
        )

        if relative.name in CONTROL_FILES:
            continue

        if any(
            part in {
                "__pycache__",
                ".git",
                ".sophyane",
            }
            for part in relative.parts
        ):
            continue

        if path.suffix.lower() in {
            ".pyc",
            ".pyo",
            ".tmp",
            ".log",
        }:
            continue

        output.append(
            path
        )

    return sorted(
        output,
        key=lambda item:
            str(
                item.relative_to(
                    workspace
                )
            ),
    )


def _validate_html(
    request: str,
    path: Path,
) -> tuple[bool, str]:
    from sophyane.code_memory.strict_acquisition_guard import (
        validate_browser_artifact,
    )

    ok, issues, _checks = (
        validate_browser_artifact(
            request,
            path,
        )
    )

    if ok:
        return (
            True,
            f"HTML behavior passed: {path.name}",
        )

    return (
        False,
        (
            f"HTML behavior failed for {path.name}: "
            + ", ".join(
                issues
            )
        ),
    )


def _validate_python(
    path: Path,
) -> tuple[bool, str]:
    try:
        py_compile.compile(
            str(path),
            doraise=True,
        )
    except py_compile.PyCompileError as error:
        return (
            False,
            f"Python compilation failed for {path.name}: {error}",
        )

    return (
        True,
        f"Python compilation passed: {path.name}",
    )


def _validate_json(
    path: Path,
) -> tuple[bool, str]:
    try:
        json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except Exception as error:
        return (
            False,
            f"JSON parsing failed for {path.name}: {error}",
        )

    return (
        True,
        f"JSON parsing passed: {path.name}",
    )


def validate_workspace_for_promotion(
    workspace: Path,
    *,
    report: object,
    request: str = "",
) -> PromotionValidation:
    report_ok, report_reason = (
        report_is_successful(
            report
        )
    )

    if not report_ok:
        return PromotionValidation(
            ok=False,
            reason=report_reason,
            files=(),
            checks=(),
        )

    workspace = Path(
        workspace
    ).expanduser().resolve()

    files = product_files(
        workspace
    )

    if not files:
        return PromotionValidation(
            ok=False,
            reason="workspace contains no product artifacts",
            files=(),
            checks=(),
        )

    checks: list[str] = []
    validated_product = False

    for path in files:
        suffix = path.suffix.lower()

        if suffix in {
            ".html",
            ".htm",
        }:
            ok, message = _validate_html(
                request,
                path,
            )

            checks.append(
                message
            )

            if not ok:
                return PromotionValidation(
                    ok=False,
                    reason=message,
                    files=tuple(
                        str(item)
                        for item in files
                    ),
                    checks=tuple(
                        checks
                    ),
                )

            validated_product = True

        elif suffix == ".py":
            ok, message = _validate_python(
                path
            )

            checks.append(
                message
            )

            if not ok:
                return PromotionValidation(
                    ok=False,
                    reason=message,
                    files=tuple(
                        str(item)
                        for item in files
                    ),
                    checks=tuple(
                        checks
                    ),
                )

            validated_product = True

        elif suffix == ".json":
            ok, message = _validate_json(
                path
            )

            checks.append(
                message
            )

            if not ok:
                return PromotionValidation(
                    ok=False,
                    reason=message,
                    files=tuple(
                        str(item)
                        for item in files
                    ),
                    checks=tuple(
                        checks
                    ),
                )

            validated_product = True

        elif suffix in {
            ".css",
            ".js",
            ".mjs",
            ".cjs",
            ".ts",
            ".tsx",
            ".jsx",
            ".md",
            ".txt",
            ".svg",
        }:
            if path.stat().st_size <= 0:
                return PromotionValidation(
                    ok=False,
                    reason=(
                        "empty product file: "
                        + path.name
                    ),
                    files=tuple(
                        str(item)
                        for item in files
                    ),
                    checks=tuple(
                        checks
                    ),
                )

            checks.append(
                f"non-empty supporting artifact: {path.name}"
            )

    if not validated_product:
        return PromotionValidation(
            ok=False,
            reason=(
                "no HTML, Python or JSON product "
                "was available for structural validation"
            ),
            files=tuple(
                str(item)
                for item in files
            ),
            checks=tuple(
                checks
            ),
        )

    return PromotionValidation(
        ok=True,
        reason="promotion validation passed",
        files=tuple(
            str(item)
            for item in files
        ),
        checks=tuple(
            checks
        ),
    )


__all__ = [
    "PromotionValidation",
    "product_files",
    "report_is_successful",
    "validate_workspace_for_promotion",
]
