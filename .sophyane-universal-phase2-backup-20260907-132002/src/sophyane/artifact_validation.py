"""Domain-agnostic artifact validation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import json
import re
from typing import Callable, Iterable


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    message: str
    path: str = ""
    severity: str = "error"


@dataclass(frozen=True)
class ArtifactValidationResult:
    ok: bool
    findings: tuple[ValidationFinding, ...]


Validator = Callable[
    [Path, str],
    Iterable[ValidationFinding],
]


_VALIDATORS: list[
    tuple[
        Callable[[Path], bool],
        Validator,
    ]
] = []


def register_validator(
    predicate: Callable[[Path], bool],
    validator: Validator,
) -> None:
    _VALIDATORS.append(
        (
            predicate,
            validator,
        )
    )


def _validate_nonempty(
    path: Path,
    text: str,
) -> Iterable[ValidationFinding]:
    if not text.strip():
        yield ValidationFinding(
            code="EMPTY_ARTIFACT",
            message="artifact is empty",
            path=str(path),
        )


def _validate_python(
    path: Path,
    text: str,
) -> Iterable[ValidationFinding]:
    try:
        ast.parse(
            text,
            filename=str(path),
        )
    except SyntaxError as exc:
        yield ValidationFinding(
            code="PYTHON_SYNTAX",
            message=(
                f"{exc.msg} "
                f"at line {exc.lineno or '?'}"
            ),
            path=str(path),
        )


def _validate_json(
    path: Path,
    text: str,
) -> Iterable[ValidationFinding]:
    try:
        json.loads(text)
    except Exception as exc:
        yield ValidationFinding(
            code="JSON_PARSE",
            message=str(exc),
            path=str(path),
        )


def _validate_html(
    path: Path,
    text: str,
) -> Iterable[ValidationFinding]:
    lower = text.lower()

    if "<html" not in lower:
        yield ValidationFinding(
            code="HTML_ROOT",
            message="HTML document has no <html> element",
            path=str(path),
        )

    if "<body" not in lower:
        yield ValidationFinding(
            code="HTML_BODY",
            message="HTML document has no <body> element",
            path=str(path),
        )

    opens = len(
        re.findall(
            r"<script(?:\s|>)",
            text,
            re.I,
        )
    )
    closes = len(
        re.findall(
            r"</script\s*>",
            text,
            re.I,
        )
    )

    if opens != closes:
        yield ValidationFinding(
            code="HTML_SCRIPT_BALANCE",
            message=(
                "script tags are unbalanced: "
                f"{opens} opening / {closes} closing"
            ),
            path=str(path),
        )


def _validate_file(
    path: Path,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []

    if not path.exists():
        return [
            ValidationFinding(
                code="MISSING_ARTIFACT",
                message="artifact does not exist",
                path=str(path),
            )
        ]

    if not path.is_file():
        return [
            ValidationFinding(
                code="NOT_A_FILE",
                message="artifact path is not a file",
                path=str(path),
            )
        ]

    try:
        text = path.read_text(
            errors="strict",
        )
    except UnicodeDecodeError:
        # Binary files are valid artifacts; structural verification
        # should be supplied by a registered binary validator.
        return findings
    except OSError as exc:
        return [
            ValidationFinding(
                code="READ_FAILURE",
                message=str(exc),
                path=str(path),
            )
        ]

    findings.extend(
        _validate_nonempty(
            path,
            text,
        )
    )

    for predicate, validator in _VALIDATORS:
        if predicate(path):
            findings.extend(
                validator(
                    path,
                    text,
                )
            )

    return findings


def validate_artifacts(
    paths: Iterable[str | Path],
    *,
    workspace: str | Path | None = None,
) -> ArtifactValidationResult:
    """Validate arbitrary artifacts and enforce workspace containment."""

    root = (
        Path(workspace).expanduser().resolve()
        if workspace is not None
        else None
    )

    findings: list[ValidationFinding] = []

    for raw in paths:
        path = Path(raw).expanduser()

        if not path.is_absolute() and root is not None:
            path = root / path

        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()

        if root is not None:
            try:
                resolved.relative_to(root)
            except ValueError:
                findings.append(
                    ValidationFinding(
                        code="WORKSPACE_ESCAPE",
                        message=(
                            "artifact is outside execution workspace"
                        ),
                        path=str(resolved),
                    )
                )
                continue

        findings.extend(
            _validate_file(
                resolved,
            )
        )

    return ArtifactValidationResult(
        ok=not any(
            item.severity == "error"
            for item in findings
        ),
        findings=tuple(findings),
    )


register_validator(
    lambda p: p.suffix.lower() == ".py",
    _validate_python,
)

register_validator(
    lambda p: p.suffix.lower() == ".json",
    _validate_json,
)

register_validator(
    lambda p: p.suffix.lower() in {
        ".html",
        ".htm",
    },
    _validate_html,
)
