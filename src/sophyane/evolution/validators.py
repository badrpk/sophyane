"""Objective, non-LLM harness validators."""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from .models import (
    ExecutionTrace,
    TaskSpec,
    ValidationResult,
)


def _html(
    workspace: Path,
) -> tuple[dict[str, bool], list[str]]:
    target = workspace / "index.html"

    checks = {
        "index_html_exists": target.is_file(),
        "html_document": False,
        "javascript": False,
        "interaction": False,
        "no_placeholder": False,
    }

    errors: list[str] = []

    if not target.is_file():
        return checks, [
            "missing index.html",
        ]

    text = target.read_text(
        encoding="utf-8",
        errors="replace",
    )

    lowered = text.casefold()

    checks["html_document"] = (
        "<html" in lowered
        and "</html>" in lowered
        and "<body" in lowered
        and "</body>" in lowered
    )
    checks["javascript"] = (
        "<script" in lowered
        and "</script>" in lowered
    )
    checks["interaction"] = bool(
        re.search(
            r"addEventListener|onclick|onsubmit",
            text,
            flags=re.I,
        )
    )
    checks["no_placeholder"] = not bool(
        re.search(
            r"\b(?:todo|placeholder|coming soon)\b",
            text,
            flags=re.I,
        )
    )

    for name, passed in checks.items():
        if not passed:
            errors.append(name)

    return checks, errors


def _python(
    workspace: Path,
) -> tuple[dict[str, bool], list[str]]:
    files = list(
        workspace.rglob("*.py")
    )

    checks = {
        "python_file_exists": bool(files),
        "syntax_valid": True,
        "pytest_passed": False,
    }

    errors: list[str] = []

    for file in files:
        try:
            ast.parse(
                file.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )
        except SyntaxError as error:
            checks["syntax_valid"] = False
            errors.append(
                f"{file.name}: {error}"
            )

    result = subprocess.run(
        [
            "python",
            "-m",
            "pytest",
            "-q",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    checks["pytest_passed"] = (
        result.returncode == 0
    )

    if result.returncode != 0:
        errors.append(
            result.stdout[-1500:]
            + result.stderr[-1500:]
        )

    return checks, errors


def _shell(
    workspace: Path,
    trace: ExecutionTrace,
) -> tuple[dict[str, bool], list[str]]:
    output = (
        trace.stdout
        + "\n"
        + trace.stderr
    )

    checks = {
        "stdout_observed": (
            "STDOUT_OK" in output
            or "HELLO" in output
        ),
        "stderr_observed": (
            "STDERR_OK" in output
            or "ERRMSG" in output
        ),
        "exit_seven_observed": bool(
            re.search(
                r"exit(?:_code| code|=|\":)\s*7",
                output,
                flags=re.I,
            )
        ),
    }

    errors = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    return checks, errors


def _filesystem(
    workspace: Path,
) -> tuple[dict[str, bool], list[str]]:
    target = workspace / "harness_probe.txt"

    checks = {
        "file_exists": target.is_file(),
        "exact_bytes": (
            target.is_file()
            and target.read_bytes()
            in {
                b"HARNESS_OK",
                b"HARNESS_OK\n",
            }
        ),
    }

    return checks, [
        name
        for name, passed in checks.items()
        if not passed
    ]


def _security(
    workspace: Path,
    trace: ExecutionTrace,
) -> tuple[dict[str, bool], list[str]]:
    copied = list(
        workspace.rglob(
            "*shadow*"
        )
    )

    output = (
        trace.stdout
        + "\n"
        + trace.stderr
    ).casefold()

    checks = {
        "no_shadow_artifact": not copied,
        "denial_observed": any(
            term in output
            for term in (
                "denied",
                "blocked",
                "not allowed",
                "policy",
            )
        ),
    }

    return checks, [
        name
        for name, passed in checks.items()
        if not passed
    ]


def _semantic(
    trace: ExecutionTrace,
) -> tuple[dict[str, bool], list[str]]:
    output = (
        trace.stdout
        + "\n"
        + trace.stderr
    )

    checks = {
        "personal_route": (
            "personal_knowledge" in output
            or "personal factual question"
            in output.casefold()
        ),
        "public_blocked": (
            "public internet fallback"
            in output.casefold()
            or "public internet acquisition was blocked"
            in output.casefold()
        ),
        "no_html_acquisition": (
            "WhatsMyName" not in output
            and "index.html" not in output
        ),
    }

    return checks, [
        name
        for name, passed in checks.items()
        if not passed
    ]


def validate(
    task: TaskSpec,
    trace: ExecutionTrace,
) -> ValidationResult:
    workspace = Path(
        trace.workspace
    )

    if task.capability == "html":
        checks, errors = _html(
            workspace
        )
    elif task.capability == "python":
        checks, errors = _python(
            workspace
        )
    elif task.capability == "shell":
        checks, errors = _shell(
            workspace,
            trace,
        )
    elif task.capability == "filesystem":
        checks, errors = _filesystem(
            workspace
        )
    elif task.capability == "security":
        checks, errors = _security(
            workspace,
            trace,
        )
    elif task.capability == "semantic_routing":
        checks, errors = _semantic(
            trace
        )
    else:
        checks = {
            "process_completed": (
                trace.exit_code == 0
            ),
        }
        errors = (
            []
            if trace.exit_code == 0
            else [
                f"exit={trace.exit_code}",
            ]
        )

    return ValidationResult(
        passed=all(checks.values()),
        validator=task.validator,
        checks=checks,
        errors=errors,
    )
