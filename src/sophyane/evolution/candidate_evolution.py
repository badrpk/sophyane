"""Evidence-grounded candidate evolution from recurrent principles.

Safety model:

1. Only recurrent principles are eligible.
2. Objective capability boundaries select the component.
3. Cloud analysis may generate a candidate diff.
4. The diff is restricted to one logical source component plus an optional
   regression test.
5. The diff is applied only inside a disposable Git worktree.
6. Representative failures are replayed against baseline and candidate.
7. Targeted tests and the full regression suite must pass.
8. Held-out performance cannot regress.
9. A passing candidate may be committed to an evolution/* branch.
10. This module never merges or pushes main.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .engine import COMPONENT_PATHS, EvolutionEngine
from .evidence_pipeline import EvidenceStore, LocalAnalyst
from .models import (
    EvolutionConfig,
    ExecutionTrace,
    PatchProposal,
    TaskSpec,
)
from .validators import validate


SOURCE_COMPONENT_PATHS: dict[str, tuple[str, ...]] = {
    "filesystem": (
        "src/sophyane/runtime_filesystem_capabilities_v20.py",
        "src/sophyane/capability_executors.py",
        "src/sophyane/execution_runtime.py",
        "src/sophyane/sli_chunk_router.py",
        "src/sophyane/tui_v2.py",
    ),
    "python": (
        "src/sophyane/capability_executors.py",
        "src/sophyane/local_coding_capability.py",
        "src/sophyane/execution_runtime.py",
        "src/sophyane/sli_chunk_router.py",
        "src/sophyane/tui_v2.py",
    ),
    "html": (
        "src/sophyane/code_memory/",
        "src/sophyane/local_site_refinement.py",
        "src/sophyane/sli_chunk_router.py",
        "src/sophyane/tui_v2.py",
    ),
    "shell": (
        "src/sophyane/execution_runtime.py",
        "src/sophyane/capability_executors.py",
        "src/sophyane/sli_chunk_router.py",
        "src/sophyane/tui_v2.py",
    ),
    "security": (
        "src/sophyane/security/",
        "src/sophyane/harness_task_policy.py",
        "src/sophyane/capability_executors.py",
        "src/sophyane/tui_v2.py",
    ),
    "semantic_router": (
        "src/sophyane/semantic_intent_router.py",
        "src/sophyane/personal_fact_resolver.py",
        "src/sophyane/sli_personal_connector.py",
        "src/sophyane/tui_v2.py",
    ),
}

COMPONENT_CAPABILITY = {
    "filesystem": "filesystem",
    "python": "python",
    "html": "html",
    "shell": "shell",
    "security": "security",
    "semantic_router": "semantic_routing",
}

MAX_SOURCE_FILES = 1
MAX_TEST_FILES = 1
MAX_CHANGED_LINES = 20

INDEXED_EDIT_PLACEHOLDERS = {
    "maximum five source lines",
    "maximum five replacement lines",
    "brief reusable reason",
    "actual_code",
    "<actual code>",
    "<replacement code>",
}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _json_object(value: str) -> dict[str, Any]:
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        str(value or "").strip(),
        flags=re.I,
    )
    text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start < 0 or end <= start:
        raise ValueError("No JSON object returned")

    return json.loads(text[start : end + 1])


def _normalise_patch_text(
    value: str,
) -> str:
    """Normalize model-produced unified diffs without weakening patch gates."""
    patch = str(value or "").strip()

    fenced = re.fullmatch(
        r"```(?:diff|patch)?\s*(.*?)\s*```",
        patch,
        flags=re.I | re.S,
    )

    if fenced:
        patch = fenced.group(1).strip()

    start = patch.find("diff --git ")

    if start >= 0:
        return patch[start:].strip()

    # Gemini sometimes emits conventional ---/+++ unified diffs but omits
    # the required Git file header. Add it only when both paths are explicit.
    lines = patch.splitlines()
    output: list[str] = []
    index = 0
    converted = False

    while index < len(lines):
        line = lines[index]

        if (
            line.startswith("--- a/")
            and index + 1 < len(lines)
            and lines[index + 1].startswith("+++ b/")
        ):
            old_path = line[len("--- a/"):].strip()
            new_path = lines[index + 1][len("+++ b/"):].strip()

            output.append(
                f"diff --git a/{old_path} b/{new_path}"
            )
            output.append(line)
            output.append(lines[index + 1])

            converted = True
            index += 2
            continue

        output.append(line)
        index += 1

    normalized = "\n".join(output).strip()

    if converted:
        return normalized

    return patch


def _indexed_edit_payload(
    value: str,
) -> dict[str, Any]:
    """Parse a compact operation over a preselected numbered source window."""
    payload = _json_object(value)

    operation = str(
        payload.get("op")
        or "replace"
    ).strip().casefold()

    if operation not in {
        "replace",
        "insert_before",
        "insert_after",
        "delete",
    }:
        raise ValueError(
            f"Unsupported indexed-edit operation: {operation}"
        )

    try:
        start = int(payload.get("start"))
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Indexed edit requires an integer start line"
        ) from error

    try:
        end = int(
            payload.get(
                "end",
                start,
            )
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Indexed edit requires an integer end line"
        ) from error

    code = str(
        payload.get("code")
        or ""
    )

    if operation != "delete" and not code:
        raise ValueError(
            "Indexed edit requires replacement code"
        )

    normalized_code = " ".join(
        code.casefold().split()
    )

    if any(
        marker in normalized_code
        for marker in INDEXED_EDIT_PLACEHOLDERS
    ):
        raise ValueError(
            "Indexed edit copied a schema placeholder "
            "instead of producing source code"
        )

    return {
        "op": operation,
        "start": start,
        "end": end,
        "code": code,
        "rationale": str(
            payload.get("reason")
            or payload.get("rationale")
            or "Apply one bounded indexed edit."
        ).strip(),
        "confidence": float(
            payload.get("confidence")
            or 0.70
        ),
    }


def _window_keywords(
    value: str,
) -> set[str]:
    return {
        token
        for token in re.findall(
            r"[a-z_][a-z0-9_]{3,}",
            str(value or "").casefold(),
        )
        if token not in {
            "this",
            "that",
            "with",
            "from",
            "must",
            "before",
            "after",
            "task",
            "failure",
            "python",
            "source",
            "component",
        }
    }


def _select_indexed_window(
    *,
    repo: Path,
    component: str,
    principle: str,
    records: list[tuple[Path, dict[str, Any]]],
    window_size: int = 48,
) -> dict[str, Any]:
    """Select one deterministic source window using failure-keyword overlap."""
    if component not in SOURCE_COMPONENT_PATHS:
        raise ValueError(
            f"Unknown indexed-edit component: {component}"
        )

    evidence_parts = [principle]

    for _, record in records:
        evidence_parts.append(
            str(
                record.get(
                    "task",
                    {},
                ).get(
                    "prompt"
                )
                or ""
            )
        )
        evidence_parts.extend(
            str(item)
            for item in (
                record.get(
                    "validation",
                    {},
                ).get(
                    "errors",
                    [],
                )
                or []
            )
        )

    keywords = _window_keywords(
        "\n".join(evidence_parts)
    )

    candidates: list[
        tuple[int, str, int, list[str]]
    ] = []

    for allowed in SOURCE_COMPONENT_PATHS[
        component
    ]:
        allowed_path = Path(repo) / allowed

        files: list[Path]

        if allowed_path.is_file():
            files = [allowed_path]
        elif allowed_path.is_dir():
            files = sorted(
                allowed_path.rglob("*.py")
            )[:8]
        else:
            continue

        for source_path in files:
            relative = str(
                source_path.relative_to(repo)
            ).replace("\\", "/")

            lines = source_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines(
                keepends=True
            )

            if not lines:
                continue

            step = max(
                12,
                window_size // 2,
            )

            for offset in range(
                0,
                len(lines),
                step,
            ):
                chunk = lines[
                    offset:
                    offset + window_size
                ]

                chunk_text = "".join(
                    chunk
                ).casefold()

                score = sum(
                    chunk_text.count(keyword)
                    for keyword in keywords
                )

                # Prefer executable regions over import/header-only regions.
                score += 3 * sum(
                    marker in chunk_text
                    for marker in (
                        "def ",
                        "if ",
                        "return ",
                        "raise ",
                        "except ",
                    )
                )

                candidates.append(
                    (
                        score,
                        relative,
                        offset,
                        chunk,
                    )
                )

    if not candidates:
        raise RuntimeError(
            f"No indexed-edit source window found for {component}"
        )

    score, relative, offset, lines = max(
        candidates,
        key=lambda item: (
            item[0],
            -item[2],
            item[1],
        ),
    )

    numbered = "".join(
        f"{index:02d}|{line}"
        for index, line in enumerate(
            lines,
            start=1,
        )
    )

    return {
        "file": relative,
        "offset": offset,
        "lines": lines,
        "numbered": numbered,
        "score": score,
    }


def _leading_whitespace(value: str) -> str:
    """Return the leading spaces or tabs from one source line."""
    match = re.match(
        r"^[ \t]*",
        str(value or ""),
    )

    return (
        match.group(0)
        if match
        else ""
    )


def _normalize_indexed_code_indentation(
    *,
    operation: str,
    selected_lines: list[str],
    code: str,
) -> str:
    """Apply the selected source indentation to compact model output.

    The model supplies relative indentation only. Sophyane supplies the
    absolute indentation from the selected source block.
    """
    raw_lines = str(code or "").splitlines()

    if not raw_lines:
        return ""

    non_empty = [
        line
        for line in raw_lines
        if line.strip()
    ]

    if not non_empty:
        return ""

    # Remove the model's common leading indentation first.
    common_indent = min(
        len(line) - len(line.lstrip(" \t"))
        for line in non_empty
    )

    relative_lines = [
        (
            line[common_indent:]
            if line.strip()
            else ""
        )
        for line in raw_lines
    ]

    if operation in {
        "replace",
        "insert_before",
        "insert_after",
    }:
        reference = (
            selected_lines[0]
            if selected_lines
            else ""
        )

        absolute_indent = (
            _leading_whitespace(
                reference
            )
        )
    else:
        absolute_indent = ""

    normalized = "\n".join(
        (
            absolute_indent + line
            if line
            else ""
        )
        for line in relative_lines
    )

    return normalized


def _indexed_edit_terms(
    value: str,
) -> set[str]:
    """Extract meaningful identifiers used to anchor a repair to source."""
    ignored = {
        "and",
        "as",
        "assert",
        "class",
        "def",
        "else",
        "false",
        "for",
        "from",
        "if",
        "import",
        "in",
        "is",
        "none",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "true",
        "try",
        "while",
        "with",
    }

    return {
        token
        for token in re.findall(
            r"[A-Za-z_][A-Za-z0-9_]{2,}",
            str(value or ""),
        )
        if token.casefold() not in ignored
    }


def _validate_indexed_repair_anchor(
    *,
    original_payload: dict[str, Any],
    repaired_payload: dict[str, Any],
    window: dict[str, Any],
) -> None:
    """Require a repair to remain on the failed range and source topic."""
    original_start = int(
        original_payload["start"]
    )
    original_end = int(
        original_payload["end"]
    )

    repaired_start = int(
        repaired_payload["start"]
    )
    repaired_end = int(
        repaired_payload["end"]
    )

    if (
        repaired_start != original_start
        or repaired_end != original_end
    ):
        raise ValueError(
            "Indexed repair changed the original source range: "
            f"{original_start}-{original_end} became "
            f"{repaired_start}-{repaired_end}"
        )

    window_lines = list(
        window.get("lines")
        or []
    )

    if (
        repaired_start < 1
        or repaired_end > len(window_lines)
    ):
        raise ValueError(
            "Indexed repair range is outside the selected window"
        )

    selected_text = "".join(
        window_lines[
            repaired_start - 1:
            repaired_end
        ]
    )

    nearby_start = max(
        0,
        repaired_start - 4,
    )
    nearby_end = min(
        len(window_lines),
        repaired_end + 3,
    )

    nearby_text = "".join(
        window_lines[
            nearby_start:
            nearby_end
        ]
    )

    repair_code = str(
        repaired_payload.get("code")
        or ""
    )

    source_terms = (
        _indexed_edit_terms(selected_text)
        | _indexed_edit_terms(nearby_text)
        | _indexed_edit_terms(
            original_payload.get("code")
            or ""
        )
    )

    repair_terms = _indexed_edit_terms(
        repair_code
    )

    # Punctuation-only and literal-only edits can legitimately have no
    # identifiers, so require overlap only when both sides contain terms.
    if (
        source_terms
        and repair_terms
        and not (
            source_terms
            & repair_terms
        )
    ):
        raise ValueError(
            "Indexed repair is unrelated to the selected source window"
        )


def _indexed_edit_to_patch(
    *,
    repo: Path,
    component: str,
    window: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    """Convert a bounded numbered-window edit into a deterministic Git patch."""
    relative = str(
        window["file"]
    )

    if not _path_allowed(
        relative,
        SOURCE_COMPONENT_PATHS[
            component
        ],
    ):
        raise ValueError(
            "Indexed edit escaped its component boundary"
        )

    target = (
        Path(repo).resolve()
        / relative
    ).resolve()

    repository = Path(repo).resolve()

    try:
        target.relative_to(repository)
    except ValueError as error:
        raise ValueError(
            "Indexed edit resolved outside the repository"
        ) from error

    original = target.read_text(
        encoding="utf-8"
    )

    original_lines = original.splitlines(
        keepends=True
    )

    window_lines = list(
        window["lines"]
    )

    start = int(
        payload["start"]
    )
    end = int(
        payload["end"]
    )

    if (
        start < 1
        or end < start
        or end > len(window_lines)
    ):
        raise ValueError(
            "Indexed edit range is outside the selected window"
        )

    operation = str(
        payload["op"]
    )

    selected_window_lines = (
        window_lines[
            start - 1:
            end
        ]
    )

    code = (
        _normalize_indexed_code_indentation(
            operation=operation,
            selected_lines=selected_window_lines,
            code=str(
                payload.get("code")
                or ""
            ),
        )
    )

    code_lines = (
        code.splitlines(
            keepends=True
        )
        if code
        else []
    )

    code_lines = [
        line
        if line.endswith("\n")
        else line + "\n"
        for line in code_lines
    ]

    if len(code_lines) > 5:
        raise ValueError(
            "Indexed edit may emit at most five code lines"
        )

    selected_nonempty = [
        line
        for line in selected_window_lines
        if line.strip()
    ]

    selected_opens_block = bool(
        selected_nonempty
        and selected_nonempty[-1].rstrip().endswith(":")
    )

    replaced_line_count = (
        end - start + 1
    )

    if (
        operation == "replace"
        and replaced_line_count == 1
        and len(code_lines) > 1
        and not selected_opens_block
    ):
        raise ValueError(
            "A single non-block source line may only be "
            "replaced by one source line"
        )

    if (
        operation in {
            "insert_before",
            "insert_after",
        }
        and len(code_lines) > 1
        and not selected_opens_block
    ):
        raise ValueError(
            "A multi-line insertion requires a selected "
            "block-opening source line"
        )

    absolute_start = (
        int(window["offset"])
        + start
        - 1
    )

    absolute_end = (
        int(window["offset"])
        + end
    )

    updated_lines = list(
        original_lines
    )

    if operation == "replace":
        updated_lines[
            absolute_start:
            absolute_end
        ] = code_lines

    elif operation == "delete":
        del updated_lines[
            absolute_start:
            absolute_end
        ]

    elif operation == "insert_before":
        updated_lines[
            absolute_start:
            absolute_start
        ] = code_lines

    elif operation == "insert_after":
        updated_lines[
            absolute_end:
            absolute_end
        ] = code_lines

    updated = "".join(
        updated_lines
    )

    if updated == original:
        raise ValueError(
            "Indexed edit produced no source change"
        )

    # Reject adjacent duplicated non-empty statements created by a bounded
    # edit. This catches repeated closing calls and repeated evidence lines.
    normalized_updated_lines = [
        line.strip()
        for line in updated_lines
        if line.strip()
    ]

    for previous, current in zip(
        normalized_updated_lines,
        normalized_updated_lines[1:],
    ):
        if (
            previous == current
            and previous not in {
                ")",
                "]",
                "}",
            }
        ):
            raise ValueError(
                "Indexed edit created duplicate adjacent source lines"
            )

    # Python candidates must remain parseable before a Git worktree is made.
    if relative.endswith(".py"):
        try:
            compile(
                updated,
                relative,
                "exec",
            )
        except SyntaxError as error:
            raise ValueError(
                "Indexed edit produced invalid Python syntax: "
                f"{error.msg} at line {error.lineno}"
            ) from error

    selected_text = "".join(
        original_lines[
            absolute_start:
            absolute_end
        ]
    )

    changed_material = (
        selected_text
        + "\n"
        + code
    )

    if _EXACT_BENCHMARK_LITERAL_RE.search(
        changed_material
    ):
        raise ValueError(
            "Indexed edit contains an exact benchmark literal"
        )

    changed_lines = (
        end - start + 1
        + len(code_lines)
    )

    if changed_lines > MAX_CHANGED_LINES:
        raise ValueError(
            "Indexed edit exceeds the changed-line limit"
        )

    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(
                keepends=True
            ),
            updated.splitlines(
                keepends=True
            ),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
            n=3,
        )
    )

    if not diff_lines:
        raise ValueError(
            "Indexed edit generated an empty patch"
        )

    patch = (
        f"diff --git a/{relative} b/{relative}\n"
        + "".join(diff_lines)
    )

    structural_errors = (
        _validate_unified_diff_structure(
            patch
        )
    )

    if structural_errors:
        raise ValueError(
            "Indexed patch failed structural validation: "
            + "; ".join(
                structural_errors
            )
        )

    return patch


def _micro_edit_payload(
    value: str,
    *,
    component: str,
) -> dict[str, Any]:
    """Parse one compact exact-replacement edit from an analyst response."""
    payload = _json_object(value)

    file_path = str(
        payload.get("file")
        or payload.get("path")
        or ""
    ).strip()

    find_text = str(
        payload.get("find")
        or payload.get("old")
        or ""
    )

    replace_text = str(
        payload.get("replace")
        or payload.get("new")
        or ""
    )

    if not file_path:
        raise ValueError(
            "Micro-edit response has no file path"
        )

    if not find_text:
        raise ValueError(
            "Micro-edit response has no exact find text"
        )

    if find_text == replace_text:
        raise ValueError(
            "Micro-edit find and replace values are identical"
        )

    return {
        "component": component,
        "file": file_path,
        "find": find_text,
        "replace": replace_text,
        "rationale": str(
            payload.get("rationale")
            or payload.get("reason")
            or "Apply one bounded exact replacement."
        ).strip(),
        "confidence": float(
            payload.get("confidence")
            or 0.70
        ),
        "tests": [
            str(item)
            for item in (
                payload.get("tests")
                or []
            )
            if str(item).strip()
        ],
    }


def _micro_edit_to_patch(
    *,
    repo: Path,
    component: str,
    payload: dict[str, Any],
) -> str:
    """Construct a valid Git diff from one exact, uniquely matched edit."""
    if component not in SOURCE_COMPONENT_PATHS:
        raise ValueError(
            f"Unknown micro-edit component: {component}"
        )

    relative = str(
        payload.get("file")
        or ""
    ).strip().replace("\\", "/")

    if (
        not relative
        or relative.startswith("/")
        or ".." in Path(relative).parts
    ):
        raise ValueError(
            "Micro-edit file path is unsafe"
        )

    allowed = SOURCE_COMPONENT_PATHS[
        component
    ]

    if not _path_allowed(
        relative,
        allowed,
    ):
        raise ValueError(
            "Micro-edit targets a file outside the "
            f"{component!r} component: {relative}"
        )

    target = (
        Path(repo).resolve()
        / relative
    ).resolve()

    repository = Path(repo).resolve()

    try:
        target.relative_to(repository)
    except ValueError as error:
        raise ValueError(
            "Micro-edit resolved outside the repository"
        ) from error

    if not target.is_file():
        raise ValueError(
            f"Micro-edit target does not exist: {relative}"
        )

    original = target.read_text(
        encoding="utf-8"
    )

    find_text = str(
        payload.get("find")
        or ""
    )

    replace_text = str(
        payload.get("replace")
        or ""
    )

    occurrences = original.count(
        find_text
    )

    if occurrences == 0:
        raise ValueError(
            "Micro-edit exact find text was not found "
            f"in {relative}"
        )

    if occurrences != 1:
        raise ValueError(
            "Micro-edit exact find text must occur once; "
            f"observed {occurrences} occurrences in {relative}"
        )

    updated = original.replace(
        find_text,
        replace_text,
        1,
    )

    if updated == original:
        raise ValueError(
            "Micro-edit produced no file change"
        )

    changed_lines = (
        len(find_text.splitlines())
        + len(replace_text.splitlines())
    )

    if changed_lines > MAX_CHANGED_LINES:
        raise ValueError(
            "Micro-edit exceeds changed-line limit: "
            f"{changed_lines} > {MAX_CHANGED_LINES}"
        )

    changed_material = (
        find_text
        + "\n"
        + replace_text
    )

    if _EXACT_BENCHMARK_LITERAL_RE.search(
        changed_material
    ):
        raise ValueError(
            "Micro-edit contains an exact benchmark literal"
        )

    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(
                keepends=True
            ),
            updated.splitlines(
                keepends=True
            ),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
            n=3,
        )
    )

    if not diff_lines:
        raise ValueError(
            "Micro-edit generated an empty diff"
        )

    patch = (
        f"diff --git a/{relative} b/{relative}\n"
        + "".join(diff_lines)
    )

    structural_errors = (
        _validate_unified_diff_structure(
            patch
        )
    )

    if structural_errors:
        raise ValueError(
            "Deterministically generated micro-patch "
            "failed structural validation: "
            + "; ".join(structural_errors)
        )

    return patch


def _candidate_payload(
    value: str,
    *,
    component: str,
) -> dict[str, Any]:
    """Recover a candidate from JSON or a model-produced diff block.

    Unified diffs contain many quotes and literal newlines, so models
    frequently return a valid diff inside Markdown while failing to encode
    it as a valid JSON string. The diff remains subject to all normal path,
    size, security, application and regression gates.
    """
    raw = str(value or "").strip()

    if not raw:
        raise ValueError(
            "Gemini returned an empty candidate response"
        )

    try:
        payload = _json_object(raw)

        patch = _normalise_patch_text(
            str(payload.get("patch") or "")
        )

        if patch:
            payload["patch"] = patch

            if not payload.get("tests"):
                payload["tests"] = [
                    item
                    for item in _diff_paths(patch)
                    if item.startswith("tests/")
                ]

            return payload
    except (
        ValueError,
        json.JSONDecodeError,
    ):
        pass

    fenced = re.search(
        r"```diff\s*"
        r"(diff --git\s+.+?)"
        r"(?:```|\Z)",
        raw,
        flags=re.I | re.S,
    )

    if fenced:
        patch = _normalise_patch_text(
            fenced.group(1)
        )
    else:
        start = raw.find("diff --git ")

        if start >= 0:
            patch = raw[start:].strip()
        else:
            patch = _normalise_patch_text(raw)

            if not patch.startswith("diff --git "):
                raise ValueError(
                    "Gemini response contained neither valid JSON "
                    "nor a unified Git diff"
                )

    tests = [
        item
        for item in _diff_paths(patch)
        if item.startswith("tests/")
    ]

    rationale_text = re.sub(
        r"```diff.*",
        "",
        raw,
        flags=re.I | re.S,
    )

    rationale = " ".join(
        rationale_text.split()
    )[:1200]

    return {
        "component": component,
        "rationale": (
            rationale
            or "Recovered unified diff from Gemini response."
        ),
        "patch": patch,
        "tests": tests,
        "confidence": 0.70,
        "response_format_recovered": True,
    }


def _diff_paths(patch: str) -> list[str]:
    paths = re.findall(
        r"^\+\+\+\s+b/(.+)$",
        patch,
        flags=re.M,
    )

    return [
        path.strip()
        for path in paths
        if path.strip() != "/dev/null"
    ]


_PLACEHOLDER_INDEX_RE = re.compile(
    r"^index\s+"
    r"(?:1234567|abcdef0|deadbee|0000000)"
    r"\.\."
    r"(?:89abcdef|7654321|abcdef0|deadbee)"
    r"(?:\s+\d+)?$",
    re.I | re.M,
)

_EXACT_BENCHMARK_LITERAL_RE = re.compile(
    r"""
    (?:
        add\s*\(\s*20\s*,\s*22\s*\)\s*==\s*42
        |
        HARNESS_OK
        |
        STDERR_OK
        |
        STDOUT_OK
        |
        harness_probe\.txt
        |
        exit_probe\.sh
    )
    """,
    re.I | re.X,
)

_HUNK_HEADER_RE = re.compile(
    r"^@@\s+"
    r"-(\d+)(?:,(\d+))?\s+"
    r"\+(\d+)(?:,(\d+))?\s+@@",
    re.M,
)


def _validate_unified_diff_structure(
    patch: str,
) -> list[str]:
    """Return structural or benchmark-specific patch violations."""
    value = str(patch or "")
    errors: list[str] = []

    if not value.startswith("diff --git "):
        errors.append(
            "missing Git diff header"
        )

    if _PLACEHOLDER_INDEX_RE.search(value):
        errors.append(
            "fabricated placeholder Git index hashes"
        )

    if _EXACT_BENCHMARK_LITERAL_RE.search(value):
        errors.append(
            "exact benchmark literal hardcoded into candidate patch"
        )

    paths = _diff_paths(value)

    if not paths:
        errors.append(
            "no modified file paths detected"
        )

    hunks = list(
        _HUNK_HEADER_RE.finditer(value)
    )

    if not hunks:
        errors.append(
            "no valid unified-diff hunk header"
        )

    lines = value.splitlines()

    for index, match in enumerate(hunks):
        start = (
            value[:match.end()]
            .count("\n")
            + 1
        )

        next_match = (
            hunks[index + 1]
            if index + 1 < len(hunks)
            else None
        )

        end = (
            value[:next_match.start()]
            .count("\n")
            if next_match
            else len(lines)
        )

        body = lines[start:end]

        old_expected = int(
            match.group(2)
            or "1"
        )
        new_expected = int(
            match.group(4)
            or "1"
        )

        old_actual = sum(
            1
            for line in body
            if (
                line.startswith((" ", "-"))
                and not line.startswith("---")
            )
        )

        new_actual = sum(
            1
            for line in body
            if (
                line.startswith((" ", "+"))
                and not line.startswith("+++")
            )
        )

        if old_actual != old_expected:
            errors.append(
                "hunk old-line count mismatch: "
                f"expected {old_expected}, observed {old_actual}"
            )

        if new_actual != new_expected:
            errors.append(
                "hunk new-line count mismatch: "
                f"expected {new_expected}, observed {new_actual}"
            )

        if (
            old_expected > 0
            and not any(
                line.startswith((" ", "-"))
                and not line.startswith("---")
                for line in body
            )
        ):
            errors.append(
                "existing-file hunk contains no source context or removals"
            )

    return list(dict.fromkeys(errors))


def _changed_lines(patch: str) -> int:
    return sum(
        1
        for line in patch.splitlines()
        if (
            line.startswith("+")
            or line.startswith("-")
        )
        and not line.startswith(("+++", "---"))
    )


def _path_allowed(
    path: str,
    allowed: tuple[str, ...],
) -> bool:
    return any(
        path == item
        or path.startswith(
            item.rstrip("/") + "/"
        )
        for item in allowed
    )


@dataclass
class ReplayResult:
    task_id: str
    capability: str
    passed: bool
    checks: dict[str, bool]
    errors: list[str]
    stdout_tail: str = ""
    stderr_tail: str = ""


@dataclass
class CandidateEvaluation:
    candidate_id: str
    component: str
    capability: str
    principle_id: str
    principle: str
    branch: str
    worktree: str
    proposal: dict[str, Any]
    baseline_replays: list[ReplayResult]
    candidate_replays: list[ReplayResult]
    baseline_score: float
    candidate_score: float
    representative_improved: bool
    targeted_tests_passed: bool
    full_suite_passed: bool
    held_out_baseline_score: float
    held_out_candidate_score: float
    held_out_not_regressed: bool
    security_gate_passed: bool
    promotable: bool
    committed: bool
    status: str
    details: dict[str, Any] = field(default_factory=dict)

    def write(self, root: Path) -> Path:
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            root
            / f"{self.candidate_id}.json"
        )

        path.write_text(
            json.dumps(
                asdict(self),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        return path


class CandidateEvolver:
    def __init__(
        self,
        repo: Path,
    ) -> None:
        self.repo = Path(repo).resolve()
        self.store = EvidenceStore(self.repo)
        self.engine = EvolutionEngine(
            EvolutionConfig(
                repo=self.repo,
                allow_cloud_analysis=True,
                allow_candidate_patches=False,
                allow_promotion=False,
            )
        )
        self.local = LocalAnalyst()

        self.root = (
            self.repo
            / ".sophyane-evolution"
        )
        self.worktrees = (
            self.root
            / "worktrees"
        )
        self.candidates = (
            self.root
            / "candidates"
        )

        self.worktrees.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.candidates.mkdir(
            parents=True,
            exist_ok=True,
        )

    def cloud_available(self) -> bool:
        return bool(
            self.engine._gemini_key()
        )

    def recurrent_principles(
        self,
        *,
        component: str = "",
    ) -> list[dict[str, Any]]:
        return (
            self.store.principles
            .recurrent_principles(
                component=component,
            )
        )

    def select_principle(
        self,
        *,
        component: str = "",
    ) -> dict[str, Any]:
        principles = self.recurrent_principles(
            component=component,
        )

        if not principles:
            raise RuntimeError(
                "No recurrent principle is available "
                f"for component {component or '(any)'}."
            )

        preferred = {
            "python": 0,
            "filesystem": 1,
            "html": 2,
            "shell": 3,
            "semantic_router": 4,
            "security": 5,
        }

        principles.sort(
            key=lambda item: (
                preferred.get(
                    str(item.get("component")),
                    99,
                ),
                -len(
                    item.get(
                        "distinct_tasks",
                        [],
                    )
                ),
                -float(
                    item.get(
                        "maximum_confidence",
                        0.0,
                    )
                ),
            )
        )

        return principles[0]

    def representative_records(
        self,
        *,
        component: str,
        limit: int = 3,
    ) -> list[tuple[Path, dict[str, Any]]]:
        capability = COMPONENT_CAPABILITY[
            component
        ]

        selected: list[
            tuple[Path, dict[str, Any]]
        ] = []

        for path in self.store.record_paths():
            data = self.store.read(path)

            if (
                data.get("task", {}).get(
                    "capability"
                )
                != capability
            ):
                continue

            if data.get(
                "validation",
                {},
            ).get("passed"):
                continue

            selected.append((path, data))

        # Prefer failures with different task text.
        unique: list[
            tuple[Path, dict[str, Any]]
        ] = []
        seen_prompts: set[str] = set()

        for item in selected:
            prompt = " ".join(
                str(
                    item[1]
                    .get("task", {})
                    .get("prompt")
                    or ""
                ).casefold().split()
            )

            if prompt in seen_prompts:
                continue

            seen_prompts.add(prompt)
            unique.append(item)

            if len(unique) >= limit:
                break

        if len(unique) < limit:
            for item in selected:
                if item in unique:
                    continue

                unique.append(item)

                if len(unique) >= limit:
                    break

        return unique

    def _source_context(
        self,
        *,
        component: str,
    ) -> str:
        allowed = SOURCE_COMPONENT_PATHS[
            component
        ]

        parts: list[str] = []

        for item in allowed:
            path = self.repo / item

            if path.is_file():
                text = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

                parts.append(
                    f"\n===== {item} =====\n"
                    + text[:18_000]
                )

                continue

            if path.is_dir():
                for child in sorted(
                    path.rglob("*.py")
                )[:6]:
                    relative = str(
                        child.relative_to(
                            self.repo
                        )
                    )

                    text = child.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )

                    parts.append(
                        f"\n===== {relative} =====\n"
                        + text[:10_000]
                    )

        return "\n".join(parts)[
            :50_000
        ]

    def _representative_context(
        self,
        records: list[
            tuple[Path, dict[str, Any]]
        ],
    ) -> str:
        payload = []

        for path, data in records:
            analysis = (
                data.get(
                    "analysis_pipeline"
                )
                or {}
            )

            payload.append(
                {
                    "record": path.name,
                    "task": data.get("task"),
                    "validation": data.get(
                        "validation"
                    ),
                    "trace": {
                        "exit_code": (
                            data.get(
                                "trace",
                                {},
                            ).get(
                                "exit_code"
                            )
                        ),
                        "files": (
                            data.get(
                                "trace",
                                {},
                            ).get(
                                "files"
                            )
                        ),
                        "stdout_tail": str(
                            data.get(
                                "trace",
                                {},
                            ).get(
                                "stdout"
                            )
                            or ""
                        )[-2500:],
                        "stderr_tail": str(
                            data.get(
                                "trace",
                                {},
                            ).get(
                                "stderr"
                            )
                            or ""
                        )[-1500:],
                    },
                    "final_analysis": (
                        analysis.get("final")
                    ),
                    "arbitration": (
                        analysis.get(
                            "arbitration"
                        )
                    ),
                }
            )

        return json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )

    def _local_patch_critique(
        self,
        proposal: PatchProposal,
        *,
        principle: str,
    ) -> dict[str, Any]:
        if not self.local.available():
            return {
                "available": False,
                "accepted": True,
                "reason": (
                    "Local analyst unavailable; "
                    "objective gates remain authoritative."
                ),
            }

        prompt = f"""
Review this candidate patch conservatively.

The patch must implement a reusable harness improvement for this principle:

{principle}

It may modify one source component and one regression test only.
Reject:
- exact-prompt hardcoding;
- exact benchmark filenames or answers in production routing;
- security weakening;
- bypassing validators;
- broad unrelated rewrites.

Return JSON only:
{{
  "accepted": true,
  "reason": "...",
  "risks": ["..."]
}}

Patch:
{proposal.patch}
"""

        try:
            raw = self.local.analyze(
                {
                    "task": {
                        "prompt": prompt,
                        "capability": (
                            COMPONENT_CAPABILITY[
                                proposal.component
                            ]
                        ),
                    },
                    "trace": {
                        "exit_code": 0,
                        "stdout": proposal.patch,
                        "stderr": "",
                        "files": _diff_paths(
                            proposal.patch
                        ),
                    },
                }
            )

            if raw is None:
                return {
                    "available": True,
                    "accepted": True,
                    "reason": (
                        "Local analyst returned no "
                        "structured critique."
                    ),
                }

            lowered = (
                raw.summary
                + " "
                + raw.general_principle
            ).casefold()

            rejected = any(
                term in lowered
                for term in (
                    "reject",
                    "unsafe",
                    "hardcode",
                    "bypass",
                    "unrelated",
                )
            )

            return {
                "available": True,
                "accepted": not rejected,
                "reason": raw.summary,
                "evidence": raw.evidence,
            }

        except Exception as error:
            return {
                "available": True,
                "accepted": True,
                "reason": (
                    "Local critique failed safely: "
                    f"{type(error).__name__}: {error}"
                ),
            }

    def _save_raw_candidate_response(
        self,
        *,
        component: str,
        stage: str,
        response: str,
    ) -> Path:
        """Preserve model output without exposing credentials."""
        root = (
            self.root
            / "raw-proposals"
        )
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            root
            / (
                component
                + "-"
                + time.strftime(
                    "%Y%m%d-%H%M%S"
                )
                + "-"
                + stage
                + ".txt"
            )
        )

        path.write_text(
            str(response or ""),
            encoding="utf-8",
        )

        return path

    def generate_proposal(
        self,
        *,
        principle_item: dict[str, Any],
        records: list[
            tuple[Path, dict[str, Any]]
        ],
    ) -> PatchProposal:
        component = str(
            principle_item["component"]
        )

        allowed = SOURCE_COMPONENT_PATHS[
            component
        ]

        source_context = self._source_context(
            component=component,
        )

        records_context = (
            self._representative_context(
                records
            )
        )

        indexed_window = (
            _select_indexed_window(
                repo=self.repo,
                component=component,
                principle=str(
                    principle_item.get(
                        "principle"
                    )
                    or ""
                ),
                records=records,
            )
        )

        prompt = f"""
You are generating one constrained candidate patch for Sophyane.

Objective component:
{component}

Recurrent principle:
{principle_item["principle"]}

Distinct supporting failures:
{len(principle_item.get("distinct_tasks", []))}

Allowed production paths:
{json.dumps(allowed)}

Patch constraints:
- Produce one micro-patch only.
- Modify at most one production source file.
- Change no more than 20 total added/removed lines.
- Touch one function or one adjacent code block only.
- Do not perform architectural rewrites.
- Do not include explanations inside the diff.
- Omit the optional regression test when it cannot fit safely; existing
  objective replay and regression gates will still evaluate the patch.
- Optionally modify or create one very small regression test under tests/.
- Do not change any other file.
- Do not weaken security or validators.
- Do not alter tests merely to hide failure.
- Do not hardcode exact benchmark wording, expected literal output, or one
  benchmark filename into a general route.
- Preserve Option 2 strict local-only policy.
- Preserve private/public semantic boundaries.
- Maximum changed lines: {MAX_CHANGED_LINES}.
- Do not generate Git diff headers, index hashes, or hunk numbers.
- Return one exact replacement only.
- The "find" value must be copied exactly from the supplied source.
- Keep "find" and "replace" as short as possible.
- The combined find and replace blocks must stay within
  {MAX_CHANGED_LINES} lines.
- Do not include Markdown fences.
- Do not invent source code that is absent from the supplied context.

Representative failure:
{records_context}

Selected production file:
{indexed_window["file"]}

Numbered source window:
{indexed_window["numbered"]}

Return compact JSON only:
{{
  "op": "replace",
  "start": 1,
  "end": 1,
  "code": "ACTUAL_CODE"
}}

Rules for the indexed operation:
- start and end refer only to the numbered window above;
- use replace, insert_before, insert_after or delete;
- output no file path, find text, diff, Markdown or explanation;
- modify the smallest possible range;
- code may contain at most five lines;
- ACTUAL_CODE is a schema label and must never be returned literally;
- preserve indentation exactly;
- stay below 100 output tokens.
"""

        raw_response = self.engine._analyst_llm(
            prompt
        )

        raw_path = (
            self._save_raw_candidate_response(
                component=component,
                stage="initial",
                response=raw_response,
            )
        )

        original_indexed_payload: dict[str, Any] | None = None

        try:
            parsed = _indexed_edit_payload(
                raw_response
            )

            original_indexed_payload = dict(
                parsed
            )

            parsed["file"] = (
                indexed_window["file"]
            )

            parsed["patch"] = (
                _indexed_edit_to_patch(
                    repo=self.repo,
                    component=component,
                    window=indexed_window,
                    payload=parsed,
                )
            )

        except ValueError as first_error:
            single_line_repair = (
                "single non-block source line"
                in str(first_error).casefold()
            )

            repair_shape = (
                "The code value must contain exactly one source line. "
                "Do not add parentheses, blocks, return objects, or "
                "neighbouring statements."
                if single_line_repair
                else (
                    "The code value may contain at most five short "
                    "source lines."
                )
            )

            repair_prompt = f"""
Repair one indexed edit.

Window:
{indexed_window["numbered"]}

The original failed operation used:
start={(
    original_indexed_payload or {}
).get("start")}
end={(
    original_indexed_payload or {}
).get("end")}

Return one minified JSON object only using those exact start/end values:
{{"op":"replace","start":{(
    original_indexed_payload or {}
).get("start")},"end":{(
    original_indexed_payload or {}
).get("end")},"code":"ACTUAL_CODE"}}

Rules:
- no Markdown or explanation;
- no file path or Git diff;
- do not change start or end;
- remain semantically related to the selected source lines;
- choose the smallest valid edit;
- {repair_shape}
- ACTUAL_CODE is a label; replace it with real source;
- preserve relative indentation;
- total response below 80 tokens.

Error:
{first_error}
"""

            repaired_response = (
                self.engine._analyst_llm(
                    repair_prompt,
                    max_tokens=80,
                )
            )

            repaired_path = (
                self._save_raw_candidate_response(
                    component=component,
                    stage="indexed-edit-repair",
                    response=repaired_response,
                )
            )

            try:
                parsed = _indexed_edit_payload(
                    repaired_response
                )

                if original_indexed_payload is None:
                    raise ValueError(
                        "Original indexed edit could not be parsed, "
                        "so its repair cannot be safely anchored"
                    )

                _validate_indexed_repair_anchor(
                    original_payload=original_indexed_payload,
                    repaired_payload=parsed,
                    window=indexed_window,
                )

                parsed["file"] = (
                    indexed_window["file"]
                )

                parsed["patch"] = (
                    _indexed_edit_to_patch(
                        repo=self.repo,
                        component=component,
                        window=indexed_window,
                        payload=parsed,
                    )
                )

            except ValueError as repair_error:
                raise ValueError(
                    "Indexed candidate failed after one "
                    "bounded repair attempt. "
                    f"Initial response: {raw_path}. "
                    f"Repair response: {repaired_path}. "
                    f"Initial error: {first_error}. "
                    f"Repair error: {repair_error}."
                ) from repair_error

        proposal = PatchProposal(
            component=component,
            rationale=str(
                parsed.get("rationale")
                or ""
            ),
            patch=str(
                parsed.get("patch")
                or ""
            ),
            tests=[
                str(item)
                for item in (
                    parsed.get("tests")
                    or []
                )
                if str(item).strip()
            ],
            confidence=float(
                parsed.get("confidence")
                or 0.0
            ),
            allowed_paths=list(allowed),
        )

        self.validate_proposal(
            proposal
        )

        return proposal

    def validate_proposal(
        self,
        proposal: PatchProposal,
    ) -> None:
        if proposal.component not in (
            SOURCE_COMPONENT_PATHS
        ):
            raise ValueError(
                "Unknown proposal component"
            )

        if not proposal.patch.startswith(
            "diff --git "
        ):
            raise ValueError(
                "Proposal did not contain a unified Git diff"
            )

        structural_errors = (
            _validate_unified_diff_structure(
                proposal.patch
            )
        )

        if structural_errors:
            raise ValueError(
                "Candidate patch failed structural policy: "
                + "; ".join(structural_errors)
            )

        paths = _diff_paths(
            proposal.patch
        )

        if not paths:
            raise ValueError(
                "Candidate patch modifies no files"
            )

        source_paths = [
            path
            for path in paths
            if path.startswith("src/")
        ]

        test_paths = [
            path
            for path in paths
            if path.startswith("tests/")
        ]

        other_paths = [
            path
            for path in paths
            if (
                path not in source_paths
                and path not in test_paths
            )
        ]

        if other_paths:
            raise ValueError(
                "Candidate modifies forbidden paths: "
                + ", ".join(other_paths)
            )

        if (
            not source_paths
            or len(set(source_paths))
            > MAX_SOURCE_FILES
        ):
            raise ValueError(
                "Candidate must modify exactly one "
                "production source file"
            )

        if (
            len(set(test_paths))
            > MAX_TEST_FILES
        ):
            raise ValueError(
                "Candidate may modify at most one test file"
            )

        allowed = SOURCE_COMPONENT_PATHS[
            proposal.component
        ]

        for path in source_paths:
            if not _path_allowed(
                path,
                allowed,
            ):
                raise ValueError(
                    "Candidate source path is outside "
                    f"component boundary: {path}"
                )

        if _changed_lines(
            proposal.patch
        ) > MAX_CHANGED_LINES:
            raise ValueError(
                "Candidate patch is too large"
            )

        lowered = proposal.patch.casefold()

        forbidden = (
            "disable security",
            "skip validation",
            "always return true",
            "pytest.skip",
            "@pytest.mark.skip",
            "public internet fallback: allowed",
            "sophyane_disable_cloud_fallback=0",
            "/etc/shadow",
        )

        for term in forbidden:
            if term in lowered:
                raise ValueError(
                    "Forbidden candidate content: "
                    + term
                )

    def _runtime_command(
        self,
        *,
        source_repo: Path,
    ) -> tuple[list[str], dict[str, str]]:
        python = (
            self.repo
            / ".venv"
            / "bin"
            / "python"
        )

        command = [
            str(python),
            "-m",
            "sophyane.tui_v2",
        ]

        env = os.environ.copy()

        candidate_src = str(
            source_repo / "src"
        )

        existing = env.get(
            "PYTHONPATH",
            "",
        )

        env["PYTHONPATH"] = (
            candidate_src
            if not existing
            else candidate_src
            + os.pathsep
            + existing
        )

        env.update(
            {
                "SOPHYANE_SESSION_MODE": "sli_chunks",
                "SOPHYANE_SLI_ONLY": "1",
                "SOPHYANE_NO_BROWSER": "1",
                "SOPHYANE_DISABLE_GOAL_DIALOGUE": "1",
            }
        )

        return command, env

    def replay_task(
        self,
        *,
        source_repo: Path,
        task: TaskSpec,
    ) -> ReplayResult:
        workspace = Path(
            tempfile.mkdtemp(
                prefix=(
                    "sophyane-candidate-replay-"
                    + task.task_id
                    + "-"
                )
            )
        )

        command, env = self._runtime_command(
            source_repo=source_repo,
        )

        try:
            result = subprocess.run(
                command,
                input=task.prompt + "\nexit\n",
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )

            files = [
                str(
                    path.relative_to(
                        workspace
                    )
                )
                for path in workspace.rglob("*")
                if path.is_file()
            ]

            trace = ExecutionTrace(
                task_id=task.task_id,
                workspace=str(workspace),
                command=command,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                elapsed_seconds=0.0,
                files=files,
            )

            verdict = validate(
                task,
                trace,
            )

            return ReplayResult(
                task_id=task.task_id,
                capability=task.capability,
                passed=verdict.passed,
                checks=verdict.checks,
                errors=verdict.errors,
                stdout_tail=(
                    result.stdout[-2500:]
                ),
                stderr_tail=(
                    result.stderr[-1500:]
                ),
            )

        except subprocess.TimeoutExpired:
            return ReplayResult(
                task_id=task.task_id,
                capability=task.capability,
                passed=False,
                checks={
                    "timeout": False,
                },
                errors=[
                    "candidate replay timed out",
                ],
            )

        finally:
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )

    @staticmethod
    def _task_from_record(
        data: dict[str, Any],
    ) -> TaskSpec:
        task = data.get("task") or {}

        return TaskSpec(
            task_id=str(
                task.get("task_id")
                or "representative"
            ),
            prompt=str(
                task.get("prompt")
                or ""
            ),
            capability=str(
                task.get("capability")
                or ""
            ),
            validator=str(
                task.get("validator")
                or task.get("capability")
                or ""
            ),
            expected=(
                task.get("expected")
                if isinstance(
                    task.get("expected"),
                    dict,
                )
                else {}
            ),
            held_out=bool(
                task.get("held_out")
            ),
        )

    def replay_records(
        self,
        *,
        source_repo: Path,
        records: list[
            tuple[Path, dict[str, Any]]
        ],
    ) -> list[ReplayResult]:
        return [
            self.replay_task(
                source_repo=source_repo,
                task=self._task_from_record(
                    data
                ),
            )
            for _path, data in records
        ]

    def held_out_tasks(
        self,
        *,
        capability: str,
    ) -> list[TaskSpec]:
        tasks = list(
            self.engine
            ._generalization_tasks(
                capability
            )
        )

        extra: dict[
            str,
            list[TaskSpec],
        ] = {
            "filesystem": [
                TaskSpec(
                    task_id=(
                        "heldout-filesystem-exact"
                    ),
                    prompt=(
                        "Create verify.txt containing exactly "
                        "VERIFIED and verify its exact bytes."
                    ),
                    capability="filesystem",
                    validator="filesystem",
                    held_out=True,
                )
            ],
            "python": [
                TaskSpec(
                    task_id=(
                        "heldout-python-function"
                    ),
                    prompt=(
                        "Create math_probe.py with multiply(a, b), "
                        "create a pytest proving multiply(6, 7) "
                        "equals 42, and run the test."
                    ),
                    capability="python",
                    validator="python",
                    held_out=True,
                )
            ],
        }

        tasks.extend(
            extra.get(
                capability,
                [],
            )
        )

        return tasks

    def replay_tasks(
        self,
        *,
        source_repo: Path,
        tasks: list[TaskSpec],
    ) -> list[ReplayResult]:
        return [
            self.replay_task(
                source_repo=source_repo,
                task=task,
            )
            for task in tasks
        ]

    @staticmethod
    def score(
        results: list[ReplayResult],
    ) -> float:
        if not results:
            return 1.0

        return sum(
            1
            for item in results
            if item.passed
        ) / len(results)

    def _git_apply_check(
        self,
        patch: str,
    ) -> tuple[bool, str]:
        """Validate patch syntax and context without modifying the repository."""
        staging = (
            self.root
            / "staging"
        )
        staging.mkdir(
            parents=True,
            exist_ok=True,
        )

        patch_path = (
            staging
            / (
                "candidate-"
                + time.strftime(
                    "%Y%m%d-%H%M%S"
                )
                + "-"
                + str(
                    time.time_ns()
                )
                + ".patch"
            )
        )

        patch_path.write_text(
            str(patch or "").rstrip()
            + "\n",
            encoding="utf-8",
        )

        try:
            result = subprocess.run(
                [
                    "git",
                    "apply",
                    "--check",
                    "--verbose",
                    str(patch_path),
                ],
                cwd=self.repo,
                capture_output=True,
                text=True,
                check=False,
            )

            output = (
                result.stdout
                + result.stderr
            ).strip()

            return (
                result.returncode == 0,
                output,
            )
        finally:
            patch_path.unlink(
                missing_ok=True
            )

    def _preserve_failed_patch(
        self,
        *,
        component: str,
        stage: str,
        patch: str,
        error: str,
    ) -> Path:
        """Preserve rejected patch material for diagnosis."""
        root = (
            self.root
            / "failed-proposals"
        )
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        stem = (
            component
            + "-"
            + time.strftime(
                "%Y%m%d-%H%M%S"
            )
            + "-"
            + stage
        )

        patch_path = (
            root
            / f"{stem}.patch"
        )
        error_path = (
            root
            / f"{stem}.error.txt"
        )

        patch_path.write_text(
            str(patch or "").rstrip()
            + "\n",
            encoding="utf-8",
        )

        error_path.write_text(
            str(error or "").rstrip()
            + "\n",
            encoding="utf-8",
        )

        return patch_path

    def _repair_unapplicable_patch(
        self,
        proposal: PatchProposal,
        *,
        apply_error: str,
    ) -> PatchProposal:
        """Request exactly one syntax/context repair from the active analyst."""
        repair_prompt = f"""
Repair this unified Git diff so that `git apply --check` succeeds against the
current Sophyane repository.

Objective component:
{proposal.component}

Exact Git error:
{apply_error}

Rules:
- Preserve the intended behavior.
- Correct malformed hunk headers and line counts.
- Preserve valid context from the existing source.
- Do not broaden the change.
- Modify at most one production source file.
- Optionally modify one test file.
- Do not weaken security or validators.
- Do not hardcode benchmark prompts, filenames, or expected answers.
- Return either valid JSON containing the complete patch or one fenced
  ```diff block.
- Return no second alternative patch.

Original patch:
{proposal.patch}
"""

        response = self.engine._analyst_llm(
            repair_prompt
        )

        self._save_raw_candidate_response(
            component=proposal.component,
            stage="apply-repair",
            response=response,
        )

        parsed = _candidate_payload(
            response,
            component=proposal.component,
        )

        repaired = PatchProposal(
            component=proposal.component,
            rationale=(
                str(
                    parsed.get(
                        "rationale"
                    )
                    or ""
                )
                or proposal.rationale
            ),
            patch=str(
                parsed.get("patch")
                or ""
            ),
            tests=[
                str(item)
                for item in (
                    parsed.get("tests")
                    or []
                )
                if str(item).strip()
            ],
            confidence=min(
                float(
                    parsed.get(
                        "confidence"
                    )
                    or proposal.confidence
                ),
                proposal.confidence,
            ),
            allowed_paths=list(
                proposal.allowed_paths
            ),
        )

        self.validate_proposal(
            repaired
        )

        return repaired

    def _ensure_applicable_patch(
        self,
        proposal: PatchProposal,
    ) -> tuple[PatchProposal, dict[str, Any]]:
        """Require a valid patch before creating a branch or worktree."""
        valid, first_error = (
            self._git_apply_check(
                proposal.patch
            )
        )

        diagnostics: dict[str, Any] = {
            "initial_apply_check": valid,
            "initial_error": first_error,
            "repair_attempted": False,
            "repair_apply_check": False,
            "repair_error": "",
        }

        if valid:
            return proposal, diagnostics

        self._preserve_failed_patch(
            component=proposal.component,
            stage="initial",
            patch=proposal.patch,
            error=first_error,
        )

        diagnostics[
            "repair_attempted"
        ] = True

        repaired = (
            self._repair_unapplicable_patch(
                proposal,
                apply_error=first_error,
            )
        )

        repaired_valid, repaired_error = (
            self._git_apply_check(
                repaired.patch
            )
        )

        diagnostics[
            "repair_apply_check"
        ] = repaired_valid
        diagnostics[
            "repair_error"
        ] = repaired_error

        if not repaired_valid:
            preserved = (
                self._preserve_failed_patch(
                    component=proposal.component,
                    stage="repair",
                    patch=repaired.patch,
                    error=repaired_error,
                )
            )

            raise RuntimeError(
                "Candidate patch remained invalid after one "
                "Gemini repair attempt. "
                f"Preserved patch: {preserved}. "
                f"Git error: {repaired_error}"
            )

        return repaired, diagnostics

    def _create_worktree(
        self,
        candidate_id: str,
    ) -> tuple[Path, str]:
        worktree = (
            self.worktrees
            / candidate_id
        )

        branch = (
            "evolution/"
            + candidate_id
        )

        if worktree.exists():
            raise RuntimeError(
                f"Worktree already exists: {worktree}"
            )

        result = subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree),
                "HEAD",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Could not create candidate worktree:\n"
                + result.stdout
                + result.stderr
            )

        return worktree, branch

    def _apply_patch(
        self,
        *,
        worktree: Path,
        patch: str,
    ) -> None:
        patch_file = (
            worktree
            / ".sophyane-candidate.patch"
        )

        patch_file.write_text(
            patch,
            encoding="utf-8",
        )

        check = subprocess.run(
            [
                "git",
                "apply",
                "--check",
                str(patch_file),
            ],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )

        if check.returncode != 0:
            raise RuntimeError(
                "Candidate patch does not apply:\n"
                + check.stdout
                + check.stderr
            )

        subprocess.run(
            [
                "git",
                "apply",
                str(patch_file),
            ],
            cwd=worktree,
            check=True,
        )

        patch_file.unlink(
            missing_ok=True
        )

    @staticmethod
    def _worktree_changed_paths(
        worktree: Path,
    ) -> set[str]:
        """Return tracked, staged and untracked worktree paths."""
        commands = (
            [
                "git",
                "diff",
                "--name-only",
                "--relative",
            ],
            [
                "git",
                "diff",
                "--cached",
                "--name-only",
                "--relative",
            ],
            [
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
            ],
        )

        changed: set[str] = set()

        for command in commands:
            result = subprocess.run(
                command,
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    "Could not inspect candidate worktree: "
                    + result.stdout
                    + result.stderr
                )

            for line in result.stdout.splitlines():
                changed_path = (
                    line.strip()
                    .replace("\\", "/")
                )

                if not changed_path:
                    continue

                # Sophyane's own runtime bookkeeping is not candidate code.
                if changed_path.startswith(
                    ".sophyane-evolution/"
                ):
                    continue

                if changed_path == (
                    ".sophyane-candidate.patch"
                ):
                    continue

                changed.add(
                    changed_path
                )

        return changed

    def _worktree_cleanliness(
        self,
        *,
        worktree: Path,
        proposal: PatchProposal,
    ) -> tuple[bool, list[str], list[str]]:
        """Require all worktree mutations to belong to the proposal."""
        expected = set(
            _diff_paths(
                proposal.patch
            )
        )

        observed = self._worktree_changed_paths(
            worktree
        )

        unexpected = sorted(
            observed - expected
        )

        missing = sorted(
            expected - observed
        )

        return (
            not unexpected
            and not missing,
            unexpected,
            missing,
        )

    def _targeted_tests(
        self,
        *,
        worktree: Path,
        proposal: PatchProposal,
    ) -> tuple[bool, str]:
        test_paths = [
            path
            for path in _diff_paths(
                proposal.patch
            )
            if path.startswith("tests/")
        ]

        python = (
            self.repo
            / ".venv"
            / "bin"
            / "python"
        )

        if test_paths:
            command = [
                str(python),
                "-m",
                "pytest",
                "-q",
                *test_paths,
            ]
        else:
            source_paths = [
                path
                for path in _diff_paths(
                    proposal.patch
                )
                if (
                    path.startswith("src/")
                    and path.endswith(".py")
                )
            ]

            command = [
                str(python),
                "-m",
                "py_compile",
                *source_paths,
            ]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(
            worktree / "src"
        )

        result = subprocess.run(
            command,
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            timeout=360,
            check=False,
        )

        return (
            result.returncode == 0,
            result.stdout[-4000:]
            + result.stderr[-4000:],
        )

    def _full_suite(
        self,
        *,
        worktree: Path,
    ) -> tuple[bool, str]:
        python = (
            self.repo
            / ".venv"
            / "bin"
            / "python"
        )

        env = os.environ.copy()
        env["PYTHONPATH"] = str(
            worktree / "src"
        )

        result = subprocess.run(
            [
                str(python),
                "-m",
                "pytest",
                "-q",
            ],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            timeout=1200,
            check=False,
        )

        return (
            result.returncode == 0,
            result.stdout[-6000:]
            + result.stderr[-6000:],
        )

    def evolve(
        self,
        *,
        component: str = "",
        representative_limit: int = 3,
        commit_candidate: bool = False,
    ) -> CandidateEvaluation:
        principle_item = (
            self.select_principle(
                component=component,
            )
        )

        component = str(
            principle_item["component"]
        )

        capability = COMPONENT_CAPABILITY[
            component
        ]

        records = (
            self.representative_records(
                component=component,
                limit=representative_limit,
            )
        )

        if not records:
            raise RuntimeError(
                "No representative failed records "
                f"exist for {component}."
            )

        proposal = self.generate_proposal(
            principle_item=principle_item,
            records=records,
        )

        local_critique = (
            self._local_patch_critique(
                proposal,
                principle=str(
                    principle_item[
                        "principle"
                    ]
                ),
            )
        )

        if not local_critique.get(
            "accepted",
            True,
        ):
            raise RuntimeError(
                "Local analyst rejected candidate: "
                + str(
                    local_critique.get(
                        "reason"
                    )
                )
            )

        # A malformed candidate must never create a branch or worktree.
        proposal, patch_diagnostics = (
            self._ensure_applicable_patch(
                proposal
            )
        )

        candidate_id = (
            component
            + "-"
            + time.strftime(
                "%Y%m%d-%H%M%S"
            )
        )

        worktree, branch = (
            self._create_worktree(
                candidate_id
            )
        )

        self._apply_patch(
            worktree=worktree,
            patch=proposal.patch,
        )

        baseline_replays = (
            self.replay_records(
                source_repo=self.repo,
                records=records,
            )
        )

        candidate_replays = (
            self.replay_records(
                source_repo=worktree,
                records=records,
            )
        )

        baseline_score = self.score(
            baseline_replays
        )

        candidate_score = self.score(
            candidate_replays
        )

        representative_improved = (
            candidate_score
            > baseline_score
            and any(
                candidate.passed
                and not baseline.passed
                for baseline, candidate
                in zip(
                    baseline_replays,
                    candidate_replays,
                )
            )
        )

        held_out_tasks = (
            self.held_out_tasks(
                capability=capability,
            )
        )

        baseline_held_out = (
            self.replay_tasks(
                source_repo=self.repo,
                tasks=held_out_tasks,
            )
        )

        candidate_held_out = (
            self.replay_tasks(
                source_repo=worktree,
                tasks=held_out_tasks,
            )
        )

        held_out_baseline_score = (
            self.score(
                baseline_held_out
            )
        )

        held_out_candidate_score = (
            self.score(
                candidate_held_out
            )
        )

        held_out_not_regressed = (
            held_out_candidate_score
            >= held_out_baseline_score
        )

        (
            targeted_tests_passed,
            targeted_output,
        ) = self._targeted_tests(
            worktree=worktree,
            proposal=proposal,
        )

        (
            full_suite_passed,
            full_suite_output,
        ) = self._full_suite(
            worktree=worktree,
        )

        (
            worktree_clean,
            unexpected_worktree_paths,
            missing_proposal_paths,
        ) = self._worktree_cleanliness(
            worktree=worktree,
            proposal=proposal,
        )

        security_gate_passed = (
            full_suite_passed
            and not any(
                term in proposal.patch.casefold()
                for term in (
                    "disable security",
                    "skip validation",
                    "/etc/shadow",
                    "@pytest.mark.skip",
                )
            )
        )

        promotable = all(
            (
                proposal.confidence
                >= 0.65,
                representative_improved,
                targeted_tests_passed,
                full_suite_passed,
                held_out_not_regressed,
                security_gate_passed,
                worktree_clean,
            )
        )

        committed = False

        if (
            promotable
            and commit_candidate
        ):
            proposal_paths = sorted(
                set(
                    _diff_paths(
                        proposal.patch
                    )
                )
            )

            subprocess.run(
                [
                    "git",
                    "add",
                    "--",
                    *proposal_paths,
                ],
                cwd=worktree,
                check=True,
            )

            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    (
                        "Candidate evolution: "
                        + component
                    ),
                ],
                cwd=worktree,
                check=True,
            )

            committed = True

        status = (
            "candidate_committed"
            if committed
            else "candidate_promotable"
            if promotable
            else "candidate_rejected"
        )

        result = CandidateEvaluation(
            candidate_id=candidate_id,
            component=component,
            capability=capability,
            principle_id=str(
                principle_item["id"]
            ),
            principle=str(
                principle_item[
                    "principle"
                ]
            ),
            branch=branch,
            worktree=str(worktree),
            proposal=asdict(proposal),
            baseline_replays=(
                baseline_replays
            ),
            candidate_replays=(
                candidate_replays
            ),
            baseline_score=baseline_score,
            candidate_score=candidate_score,
            representative_improved=(
                representative_improved
            ),
            targeted_tests_passed=(
                targeted_tests_passed
            ),
            full_suite_passed=(
                full_suite_passed
            ),
            held_out_baseline_score=(
                held_out_baseline_score
            ),
            held_out_candidate_score=(
                held_out_candidate_score
            ),
            held_out_not_regressed=(
                held_out_not_regressed
            ),
            security_gate_passed=(
                security_gate_passed
            ),
            promotable=promotable,
            committed=committed,
            status=status,
            details={
                "created_at": _now(),
                "representative_records": [
                    path.name
                    for path, _data
                    in records
                ],
                "local_patch_critique": (
                    local_critique
                ),
                "patch_diagnostics": (
                    patch_diagnostics
                ),
                "targeted_output": (
                    targeted_output
                ),
                "full_suite_output": (
                    full_suite_output
                ),
                "worktree_clean": (
                    worktree_clean
                ),
                "unexpected_worktree_paths": (
                    unexpected_worktree_paths
                ),
                "missing_proposal_paths": (
                    missing_proposal_paths
                ),
                "observed_worktree_paths": sorted(
                    self._worktree_changed_paths(
                        worktree
                    )
                ),
                "baseline_held_out": [
                    asdict(item)
                    for item
                    in baseline_held_out
                ],
                "candidate_held_out": [
                    asdict(item)
                    for item
                    in candidate_held_out
                ],
                "main_modified": False,
                "main_merged": False,
                "remote_pushed": False,
            },
        )

        result.write(
            self.candidates
        )

        return result
