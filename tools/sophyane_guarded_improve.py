#!/usr/bin/env python3
"""Guarded, proposal-only recursive self-improvement controller for Sophyane.

This controller never modifies the live Sophyane installation. It:

1. captures a baseline;
2. copies Sophyane into an isolated candidate;
3. runs the existing concurrent multi-agent runtime;
4. extracts a bounded structured file-replacement proposal;
5. applies it only to the candidate;
6. runs syntax, import and benchmark gates;
7. records the evidence in the append-only improvement ledger.

Promotion into the live package is intentionally not implemented here.
"""

from __future__ import annotations

import ast
import base64
import gzip

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import difflib


HOME = Path.home()
INSTALL_ROOT = (
    HOME
    / ".local/share/sophyane/venv/lib/python3.13/site-packages"
)
LIVE_PACKAGE = INSTALL_ROOT / "sophyane"
RUNS_ROOT = HOME / ".local/state/sophyane/self-improve/runs"

MAX_CHANGED_FILES = 8
MAX_FILE_BYTES = 180_000
MAX_TOTAL_BYTES = 600_000

BLOCKED_PATH_PARTS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "site-packages",
    "dist-info",
}

HIGH_RISK_FILES = {
    "permissions.py",
    "harness.py",
    "autonomy.py",
    "interpreter.py",
    "platform_kernel.py",
    "improvement_kernel.py",
    "providers/base.py",
}


@dataclass
class CommandResult:
    name: str
    ok: bool
    returncode: int
    elapsed_seconds: float
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)




def proposal_file_payload(item: dict[str, Any]) -> str:
    """Return complete replacement content from either proposal format."""
    payload = item.get("diff")
    if payload is None:
        payload = item.get("content")

    if not isinstance(payload, str):
        raise KeyError(
            "Proposal file entry missing string 'diff' or 'content'"
        )

    return payload


def emit_event(
    component: str,
    action: str,
    message: str,
    **details: Any,
) -> None:
    """Emit a compact, immediately visible structured progress event."""
    timestamp = time.strftime("%H:%M:%S")
    detail_text = " ".join(
        f"{key}={value}"
        for key, value in details.items()
        if value not in (None, "", [], {})
    )
    suffix = f" | {detail_text}" if detail_text else ""
    print(
        f"◆ [{timestamp}] {component.upper()}:{action} — {message}{suffix}",
        flush=True,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_manifest(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in BLOCKED_PATH_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            result[relative] = {
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        except OSError:
            continue

    return result


def run_command(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> CommandResult:
    started = time.monotonic()

    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return CommandResult(
            name=name,
            ok=result.returncode == 0,
            returncode=result.returncode,
            elapsed_seconds=round(time.monotonic() - started, 3),
            stdout=(result.stdout or "")[-12_000:],
            stderr=(result.stderr or "")[-12_000:],
        )
    except subprocess.TimeoutExpired as error:
        return CommandResult(
            name=name,
            ok=False,
            returncode=124,
            elapsed_seconds=round(time.monotonic() - started, 3),
            stdout=str(error.stdout or "")[-12_000:],
            stderr=f"Timed out after {timeout}s\n{error.stderr or ''}"[-12_000:],
        )
    except Exception as error:  # noqa: BLE001
        return CommandResult(
            name=name,
            ok=False,
            returncode=1,
            elapsed_seconds=round(time.monotonic() - started, 3),
            stdout="",
            stderr=f"{type(error).__name__}: {error}",
        )


def candidate_environment(candidate_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(candidate_root)
        + (os.pathsep + previous if previous else "")
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_gates(package_container: Path) -> list[CommandResult]:
    """Run deterministic gates against package_container/sophyane."""

    env = candidate_environment(package_container)
    python = sys.executable

    checks = [
        run_command(
            "compileall",
            [
                python,
                "-m",
                "compileall",
                "-q",
                str(package_container / "sophyane"),
            ],
            cwd=package_container,
            env=env,
            timeout=180,
        ),
        run_command(
            "import-smoke",
            [
                python,
                "-c",
                (
                    "import sophyane;"
                    "import sophyane.adaptive_execution;"
                    "import sophyane.multiagent;"
                    "import sophyane.improvement_kernel;"
                    "print('IMPORT_OK')"
                ),
            ],
            cwd=package_container,
            env=env,
            timeout=90,
        ),
        run_command(
            "offline-product-benchmark",
            [
                python,
                "-m",
                "sophyane.benchmark_cli",
            ],
            cwd=package_container,
            env=env,
            timeout=240,
        ),
    ]

    return checks


def gate_score(results: list[CommandResult]) -> float:
    if not results:
        return 0.0
    passed = sum(1 for item in results if item.ok)
    return round(100.0 * passed / len(results), 1)



_FAILURE_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "code", "does", "for", "from", "has", "have", "if", "in",
    "into", "is", "it", "make", "more", "not", "of", "on", "or",
    "should", "sophyane", "that", "the", "their", "then", "this", "to",
    "use", "using", "was", "with", "without",
}


def _failure_terms(failure_description: str) -> list[str]:
    """Return meaningful normalized terms from the reported failure."""

    words = re.findall(
        r"[a-zA-Z][a-zA-Z0-9_-]{2,}",
        (failure_description or "").lower(),
    )
    return sorted({
        word.replace("-", "_")
        for word in words
        if word not in _FAILURE_STOP_WORDS
    })



def mobile_artifact_score(package_root: Path, html: str, request: str) -> dict[str, object]:
    """Run isolated Sophyane HTML validation and static mobile-usability checks."""
    import os
    import subprocess
    import sys

    description = str(request or "").lower()
    applicable = any(
        token in description
        for token in (
            "html", "browser", "website", "web app", "game",
            "mobile", "responsive", "button", "control", "touch",
        )
    )
    if not applicable:
        return {
            "applicable": False,
            "score": 0.0,
            "checks": {},
            "problem": "",
        }

    probe = r"""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
request = sys.argv[2]
html = sys.stdin.read()

sys.path.insert(0, str(root.parent))

from sophyane import adaptive_execution

try:
    from sophyane.game_validation import install_game_validation
    install_game_validation()
except Exception:
    pass

problem = adaptive_execution._validate_html(html, request)
print(json.dumps({"problem": str(problem or "")}))
"""

    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_root.parent)

    completed = subprocess.run(
        [sys.executable, "-c", probe, str(package_root), request],
        input=html,
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )

    problem = ""
    validator_completed = completed.returncode == 0
    if validator_completed:
        try:
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            problem = str(result.get("problem") or "")
        except Exception:
            validator_completed = False
            problem = "invalid validator output"
    else:
        problem = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"validator exited {completed.returncode}"
        )[-1000:]

    lower = html.lower()

    checks = {
        "validator_completed": validator_completed,
        "validator_accepts_artifact": validator_completed and not problem,
        "has_viewport": "name=\"viewport\"" in lower or "name='viewport'" in lower,
        "has_responsive_unit": any(
            token in lower
            for token in ("clamp(", "vw", "vh", "dvh", "@media", "min(", "max(")
        ),
        "has_touch_protection": (
            "touch-action" in lower
            or "preventdefault" in lower
            or "pointerdown" in lower
            or "touchstart" in lower
        ),
        "has_large_control_rule": any(
            token in lower
            for token in (
                "min-height:48px",
                "min-height: 48px",
                "height:48px",
                "height: 48px",
                "min-width:48px",
                "min-width: 48px",
                "padding:14px",
                "padding: 14px",
                "padding:16px",
                "padding: 16px",
            )
        ),
    }

    score = round(
        100.0 * sum(checks.values()) / max(1, len(checks)),
        2,
    )

    return {
        "applicable": True,
        "score": score,
        "checks": checks,
        "problem": problem,
    }


def failure_target_score(
    package_root: Path,
    changed_paths: list[str],
    failure_description: str,
) -> dict[str, Any]:
    """Measure whether changed source contains evidence relevant to the failure.

    This is intentionally conservative. It does not replace product tests, but
    prevents a candidate receiving approval merely because generic compile and
    import checks remain at 100%.
    """

    terms = _failure_terms(failure_description)
    inspected: list[dict[str, Any]] = []
    combined = ""
    readable_files = 0
    syntax_valid_files = 0
    implementation_units = 0
    placeholder_penalty = 0

    for relative in changed_paths:
        candidate = package_root / relative

        # apply_proposal may report paths relative either to the package itself
        # or to its parent container.
        if not candidate.is_file() and relative.startswith("sophyane/"):
            candidate = package_root / relative.removeprefix("sophyane/")

        if not candidate.is_file():
            inspected.append({
                "path": relative,
                "readable": False,
                "reason": "file not found under package root",
            })
            continue

        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            inspected.append({
                "path": relative,
                "readable": False,
                "reason": f"{type(error).__name__}: {error}",
            })
            continue

        readable_files += 1
        lowered = text.lower().replace("-", "_")
        combined += "\n" + lowered

        syntax_ok = True
        function_count = 0
        class_count = 0

        if candidate.suffix == ".py":
            try:
                tree = ast.parse(text, filename=str(candidate))
                syntax_valid_files += 1
                function_count = sum(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for node in ast.walk(tree)
                )
                class_count = sum(
                    isinstance(node, ast.ClassDef)
                    for node in ast.walk(tree)
                )
                implementation_units += function_count + class_count
            except SyntaxError:
                syntax_ok = False

        placeholders = len(re.findall(
            r"\b(?:todo|fixme|notimplementederror)\b|^\s*pass\s*(?:#.*)?$",
            lowered,
            flags=re.M,
        ))
        placeholder_penalty += placeholders

        inspected.append({
            "path": relative,
            "readable": True,
            "syntax_ok": syntax_ok,
            "functions": function_count,
            "classes": class_count,
            "placeholders": placeholders,
            "bytes": len(text.encode("utf-8")),
        })

    matched_terms = [term for term in terms if term in combined]
    missing_terms = [term for term in terms if term not in combined]

    # Failure relevance is the principal signal.
    if terms:
        relevance = 70.0 * len(matched_terms) / len(terms)
    else:
        relevance = 0.0

    # Reward concrete implementation structure, but cap it so a large unrelated
    # file cannot overpower failure relevance.
    implementation = min(20.0, implementation_units * 1.5)

    # Reward readable and syntactically valid changed files.
    file_quality = 0.0
    if changed_paths:
        file_quality += 5.0 * readable_files / len(changed_paths)
    if readable_files:
        file_quality += 5.0 * syntax_valid_files / readable_files

    penalty = min(25.0, placeholder_penalty * 5.0)
    score = round(max(0.0, min(100.0, relevance + implementation + file_quality - penalty)), 2)

    return {
        "score": score,
        "terms": terms,
        "matched_terms": matched_terms,
        "missing_terms": missing_terms,
        "readable_files": readable_files,
        "syntax_valid_files": syntax_valid_files,
        "implementation_units": implementation_units,
        "placeholder_penalty": placeholder_penalty,
        "inspected": inspected,
    }


def extract_json_object(text: str) -> dict[str, Any] | None:
    """
    Extract only a complete top-level proposal object.

    Ignore balanced nested objects such as:
        {"path": "...", "content": "..."}
    because those are individual file entries, not proposals.
    """

    def is_proposal(obj: Any) -> bool:
        return (
            isinstance(obj, dict)
            and isinstance(obj.get("hypothesis"), str)
            and isinstance(obj.get("failure_kind"), str)
            and isinstance(obj.get("files"), list)
        )

    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)

    try:
        obj = json.loads(value)
        return obj if is_proposal(obj) else None
    except Exception:
        pass

    starts = [i for i,c in enumerate(value) if c == "{"]

    for start in starts:
        depth = 0
        in_string = False
        escaped = False

        for end in range(start, len(value)):
            ch = value[end]

            if escaped:
                escaped = False
                continue

            if ch == "\\" and in_string:
                escaped = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(value[start:end+1])
                    except Exception:
                        break

                    if is_proposal(obj):
                        return obj

                    # Nested balanced object (typically one file entry).
                    break

    return None


def safe_relative_path(value: str) -> Path:
    relative = Path(str(value or "").strip())

    if not str(relative):
        raise ValueError("empty path")

    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe path: {relative}")

    if any(part in BLOCKED_PATH_PARTS for part in relative.parts):
        raise ValueError(f"blocked path component: {relative}")

    if relative.suffix.lower() not in {
        ".py",
        ".json",
        ".md",
        ".html",
        ".js",
        ".css",
        ".toml",
        ".yaml",
        ".yml",
    }:
        raise ValueError(f"unsupported file type: {relative}")

    return relative


def source_anchor_catalog(
    candidate_package: Path,
    relative_paths: list[str],
) -> dict[str, dict[str, str]]:
    """Build deterministic IDs for unique exact source lines."""
    catalog: dict[str, dict[str, str]] = {}
    package_root = candidate_package.resolve()

    for relative_name in relative_paths:
        relative = safe_relative_path(relative_name)
        target = (candidate_package / relative).resolve()

        if target != package_root and package_root not in target.parents:
            continue

        if not target.is_file():
            continue

        content = target.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for line_number, line in enumerate(
            content.splitlines(keepends=True),
            start=1,
        ):
            stripped = line.strip()

            if (
                not stripped
                or len(stripped) < 8
                or content.count(line) != 1
            ):
                continue

            anchor_id = f"{relative.as_posix()}:L{line_number}"
            catalog[anchor_id] = {
                "path": relative.as_posix(),
                "search": line,
            }

    return catalog


def proposal_searches_are_grounded(
    raw: dict[str, Any] | None,
    candidate_package: Path,
) -> bool:
    """Validate compact searches or machine-generated anchor IDs."""
    if not isinstance(raw, dict):
        return False

    files = raw.get("files")

    if not isinstance(files, list) or not files:
        return False

    for item in files:
        if not isinstance(item, dict):
            return False

        try:
            relative = safe_relative_path(
                str(item.get("path") or "")
            )
        except Exception:
            return False

        target = candidate_package / relative
        edits = item.get("edits")

        if not target.is_file():
            return False

        if not isinstance(edits, list) or not edits:
            return False

        content = target.read_text(
            encoding="utf-8",
            errors="replace",
        )
        catalog = source_anchor_catalog(
            candidate_package,
            [relative.as_posix()],
        )

        for edit in edits:
            if not isinstance(edit, dict):
                return False

            anchor_id = edit.get("anchor_id")

            if isinstance(anchor_id, str) and anchor_id:
                selected = catalog.get(anchor_id)

                if (
                    selected is None
                    or selected["path"] != relative.as_posix()
                ):
                    return False

                continue

            search = edit.get("search")
            expected = edit.get("expected_occurrences", 1)

            if (
                not isinstance(search, str)
                or not search
                or not isinstance(expected, int)
                or isinstance(expected, bool)
                or expected < 1
                or content.count(search) != expected
            ):
                return False

    return True


def normalise_proposal(
    raw: dict[str, Any],
    candidate_package: Path,
) -> dict[str, Any]:
    files = raw.get("files")

    if not isinstance(files, list) or not files:
        raise ValueError("proposal contains no files")

    if len(files) > MAX_CHANGED_FILES:
        raise ValueError(
            f"proposal changes {len(files)} files; limit is {MAX_CHANGED_FILES}"
        )

    normalised_files: list[dict[str, Any]] = []
    total_bytes = 0

    for item in files:
        if not isinstance(item, dict):
            raise ValueError("file proposal is not an object")

        relative = safe_relative_path(str(item.get("path") or ""))
        target = (candidate_package / relative).resolve()
        package_root = candidate_package.resolve()

        if target != package_root and package_root not in target.parents:
            raise ValueError(
                f"path escapes candidate package: {relative}"
            )

        content = item.get("content")
        content_b64 = item.get("content_b64")
        content_gzip_b64 = item.get("content_gzip_b64")
        edits = item.get("edits")

        if isinstance(edits, list) and edits:
            if not target.is_file():
                raise ValueError(
                    f"compact edits require an existing file: {relative}"
                )

            content = target.read_text(
                encoding="utf-8",
                errors="replace",
            )

            if len(edits) > 12:
                raise ValueError(
                    f"{relative} contains too many edits; limit is 12"
                )

            for edit_index, edit in enumerate(edits, start=1):
                if not isinstance(edit, dict):
                    raise ValueError(
                        f"edit {edit_index} for {relative} is not an object"
                    )

                search = edit.get("search")
                anchor_id = edit.get("anchor_id")
                replace = edit.get("replace")
                expected = edit.get("expected_occurrences", 1)

                if isinstance(anchor_id, str) and anchor_id:
                    catalog = source_anchor_catalog(
                        candidate_package,
                        [relative.as_posix()],
                    )
                    selected = catalog.get(anchor_id)

                    if selected is None:
                        raise ValueError(
                            f"edit {edit_index} for {relative} "
                            f"uses unknown anchor_id {anchor_id!r}"
                        )

                    if selected["path"] != relative.as_posix():
                        raise ValueError(
                            f"anchor_id {anchor_id!r} belongs to "
                            f"{selected['path']}, not {relative}"
                        )

                    search = selected["search"]
                    expected = 1

                if not isinstance(search, str) or not search:
                    raise ValueError(
                        f"edit {edit_index} for {relative} has empty search"
                    )

                if not isinstance(replace, str):
                    raise ValueError(
                        f"edit {edit_index} for {relative} has invalid replace"
                    )

                if (
                    not isinstance(expected, int)
                    or isinstance(expected, bool)
                    or expected < 1
                    or expected > 20
                ):
                    raise ValueError(
                        f"edit {edit_index} for {relative} has invalid "
                        "expected_occurrences"
                    )

                actual = content.count(search)

                if actual != expected:
                    raise ValueError(
                        f"edit {edit_index} for {relative} expected "
                        f"{expected} exact occurrence(s), found {actual}"
                    )

                content = content.replace(
                    search,
                    replace,
                    expected,
                )

        elif isinstance(
            content_gzip_b64,
            str,
        ) and content_gzip_b64.strip():
            try:
                compressed = base64.b64decode(
                    content_gzip_b64.encode("ascii"),
                    validate=True,
                )
                content = gzip.decompress(compressed).decode("utf-8")
            except Exception as error:
                raise ValueError(
                    f"invalid content_gzip_b64 for {relative}: "
                    f"{type(error).__name__}: {error}"
                ) from error
        elif isinstance(content_b64, str) and content_b64.strip():
            try:
                content = base64.b64decode(
                    content_b64.encode("ascii"),
                    validate=True,
                ).decode("utf-8")
            except Exception as error:
                raise ValueError(
                    f"invalid content_b64 for {relative}: "
                    f"{type(error).__name__}: {error}"
                ) from error

        if not isinstance(content, str) or not content.strip():
            raise ValueError(
                f"empty content for {relative}; provide compact edits"
            )

        if relative.suffix == ".py":
            try:
                ast.parse(content, filename=relative.as_posix())
            except SyntaxError as error:
                raise ValueError(
                    f"{relative} would become invalid Python after edits: "
                    f"{error.msg} (line {error.lineno})"
                ) from error

        encoded = content.encode("utf-8")

        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError(
                f"{relative} exceeds {MAX_FILE_BYTES} bytes"
            )

        total_bytes += len(encoded)

        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError(
                f"proposal exceeds total limit of {MAX_TOTAL_BYTES} bytes"
            )

        normalised_files.append(
            {
                "path": relative.as_posix(),
                "content": content,
                "exists_in_baseline": target.exists(),
                "high_risk": relative.as_posix() in HIGH_RISK_FILES,
            }
        )

    return {
        "hypothesis": str(raw.get("hypothesis") or "")[:2000],
        "failure_kind": str(
            raw.get("failure_kind") or "unknown"
        )[:80],
        "files": normalised_files,
        "focused_tests": [
            str(item)[:500]
            for item in raw.get("focused_tests") or []
            if str(item).strip()
        ][:12],
        "risks": [
            str(item)[:500]
            for item in raw.get("risks") or []
            if str(item).strip()
        ][:12],
        "rollback_notes": str(
            raw.get("rollback_notes") or ""
        )[:2000],
        "requires_human_review": True,
    }

def apply_proposal(
    candidate_package: Path,
    proposal: dict[str, Any],
) -> list[str]:
    changed: list[str] = []

    event_path = candidate_package.parent / "file-events.jsonl"
    diff_dir = candidate_package.parent / "diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)

    for item in proposal["files"]:
        relative = Path(item["path"])
        target = (candidate_package / relative).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        existed_before = target.is_file()
        old_text = (
            target.read_text(encoding="utf-8", errors="replace")
            if existed_before
            else ""
        )
        new_text = proposal_file_payload(item)

        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()

        unified = "\n".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"baseline/{relative.as_posix()}",
                tofile=f"candidate/{relative.as_posix()}",
                lineterm="",
            )
        )

        safe_name = relative.as_posix().replace("/", "__")
        diff_file = diff_dir / f"{safe_name}.diff"
        diff_file.write_text(unified + ("\n" if unified else ""), encoding="utf-8")

        added = 0
        removed = 0
        for line in unified.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1

        event = {
            "timestamp": time.time(),
            "action": "modified" if existed_before else "created",
            "file": relative.as_posix(),
            "old_lines": len(old_lines),
            "new_lines": len(new_lines),
            "added_lines": added,
            "removed_lines": removed,
            "bytes": len(new_text.encode("utf-8")),
            "diff_file": str(diff_file),
        }

        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

        emit_event(
            "coder",
            "file-write",
            "Amending existing file" if existed_before else "Creating new file",
            file=relative.as_posix(),
            old_lines=len(old_lines),
            new_lines=len(new_lines),
            added=added,
            removed=removed,
            bytes=event["bytes"],
            diff=diff_file.name,
        )

        temporary = target.with_name(target.name + ".candidate.tmp")
        temporary.write_text(new_text, encoding="utf-8")
        temporary.replace(target)

        emit_event(
            "filesystem",
            "committed",
            "Candidate file update committed",
            file=relative.as_posix(),
        )

        changed.append(relative.as_posix())

    return changed


def provider_backend() -> Any:
    """Use Gemini directly; never invoke fallback or local bootstrap."""
    from sophyane.main import get_secret
    from sophyane.providers.gemini import GeminiProvider

    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or get_secret("gemini", "GEMINI_API_KEY")
    )

    if not api_key:
        raise RuntimeError(
            "Gemini API key not found in GEMINI_API_KEY, "
            "GOOGLE_API_KEY, or Sophyane secrets"
        )

    provider = GeminiProvider(
        api_key=api_key,
        model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        timeout=300,
        temperature=0.2,
        max_tokens=8192,
    )

    def generate(prompt: str, system_prompt: str) -> str:
        # This marker selects Gemini text/plain mode rather than the unrelated
        # PLAN_SCHEMA used by Sophyane's planning calls.
        request = (
            "SLI_BENCHMARK_ANALYSIS\n"
            "Return the exact format requested by the task.\n\n"
            + prompt
        )
        response = provider.generate(request, system_prompt)
        text = str(getattr(response, "text", response) or "")
        metadata_getter = getattr(
            provider,
            "get_last_response_metadata",
            None,
        )
        metadata = (
            metadata_getter()
            if callable(metadata_getter)
            else {}
        )
        emit_event(
            "provider",
            "response-metadata",
            "Gemini response metadata captured",
            **metadata,
        )
        return text

    return generate


def improvement_prompt(
    failure_description: str,
    baseline_manifest: dict[str, Any],
    baseline_gates: list[CommandResult],
) -> str:
    gate_summary = [
        {
            "name": item.name,
            "ok": item.ok,
            "returncode": item.returncode,
            "stderr": item.stderr[-1800:],
            "stdout": item.stdout[-1800:],
        }
        for item in baseline_gates
    ]

    important_files = sorted(baseline_manifest)[:400]

    return f"""
You are an OCI product-engineering team improving Sophyane itself.

FAILURE REPORTED BY USER:
{failure_description}

CURRENT OBSERVATION:
Sophyane has produced structurally valid but extremely low-quality products.
A one-shot provider call may return a tiny placeholder page, while HTTP 200
and a closing HTML tag are incorrectly treated as product success.
Sophyane already contains multi-agent orchestration, checkpoints, a benchmark
CLI, an improvement ledger, browser validation, and provider routing.

OBJECTIVE:
Propose a small, general, architecture-level correction. Do not hard-code a
single map, shop, game, or category. Prefer integrating existing benchmarking,
multi-agent decomposition, independent review, deterministic validation and
bounded repair into the browser product workflow.

BASELINE GATES:
{json.dumps(gate_summary, indent=2)}

AVAILABLE SOPHYANE FILES:
{json.dumps(important_files)}

WORKER RESPONSIBILITIES:
- planner: identify the narrow root cause and integration points;
- coder: propose complete replacement contents for changed files;
- tester: define regression and failure-path tests;
- security: check path, network, execution and promotion boundaries;
- operations: ensure rollback and mobile-resource limits;
- reviewer: merge the work into one bounded proposal.

FINAL RESPONSE CONTRACT:
Return exactly one JSON object and nothing else:

{{
  "hypothesis": "root cause and expected improvement",
  "failure_kind": "incomplete_artifact or requirement_missing or other",
  "files": [
    {{
      "path": "relative/path/inside/sophyane",
      "edits": [{{"anchor_id": "relative/file.py:L123", "replace": "BOUNDED_REPLACEMENT_TEXT"}}]
    }}
  ],
  "focused_tests": [
    "specific test to run"
  ],
  "risks": [
    "specific remaining risk"
  ],
  "rollback_notes": "how the change can be reverted"
}}

RULES:
- Modify no more than {MAX_CHANGED_FILES} files.
- Return complete file contents, not diffs and not ellipses.
- Do not edit credentials, API keys, user data, installation scripts or the
  Python standard library.
- Do not add automatic live promotion.
- Do not weaken permissions, sandboxing, rollback, approval or safety gates.
- Do not claim success merely because HTML parses or HTTP returns 200.
- Product success must depend on benchmark and functional evidence.
- Reuse existing Sophyane machinery where practical.
- For browser, HTML, game, responsive-layout, control-size, or touch failures, change code that is executed during artifact generation or validation.
- Trace the failing runtime path before choosing files. Relevant files commonly include adaptive_execution.py, game_validation.py, browser_failure_gate.py, browser_partial_recovery.py, runtime_self_contained_html_patch.py, runtime_premium_asset_pipeline.py, and runtime_sli_builder.py.
- Do not modify sli_schema.py, database migration code, descriptive SLI metadata, documentation, or unrelated schemas unless the reported failure is specifically a database-schema failure.
- A proposal that merely adds requirement words, classes, metrics, or metadata without changing generated HTML, repair prompts, runtime routing, or validation behavior is invalid.
- The proposed change must be observable when the isolated baseline and candidate packages generate the same requested browser artifact.
- Prefer the smallest behavior-owning runtime file over a superficially related file.
- For generated-artifact quality failures, prefer code that changes the produced HTML before changing validators.
- Select adaptive_execution.py, browser repair/prompt code, or a deterministic browser builder when the artifact lacks required CSS, markup, interaction, accessibility, or viewport behavior.
- Select game_validation.py or another validator only when the generated artifact already contains the required behavior but the validator incorrectly rejects or mismeasures it.
- A validator-only change cannot solve a missing generated HTML rule. If the evidence says has_large_control_rule=false, missing viewport, missing responsive units, missing touch protection, or equivalent absent artifact behavior, modify generation or repair code.
- The candidate must cause the same isolated browser request to produce measurably better HTML, not merely change how unchanged HTML is scored.

- Keep the proposal portable on Android Termux.
""".strip()


def record_ledger(
    *,
    run_id: str,
    failure: str,
    proposal: dict[str, Any] | None,
    baseline_score: float,
    candidate_score: float,
    verdict: str,
    run_dir: Path,
) -> None:
    try:
        from sophyane.self_improve.ledger import propose_improvement

        body = {
            "run_id": run_id,
            "failure": failure,
            "hypothesis": (
                proposal.get("hypothesis", "")
                if proposal
                else ""
            ),
            "changed_paths": [
                item["path"]
                for item in (proposal or {}).get("files", [])
            ],
            "baseline_score": baseline_score,
            "candidate_score": candidate_score,
            "verdict": verdict,
            "run_dir": str(run_dir),
            "promotion": "not performed",
        }

        propose_improvement(
            "code_hint",
            f"Guarded candidate {run_id}: {verdict}",
            json.dumps(body, indent=2, ensure_ascii=False),
            evidence={
                "run_dir": str(run_dir),
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "verdict": verdict,
            },
            score=(candidate_score - baseline_score) / 100.0,
        )
    except Exception as error:  # noqa: BLE001
        write_json(
            run_dir / "ledger-error.json",
            {
                "error": f"{type(error).__name__}: {error}",
            },
        )





def generate_isolated_browser_artifact(
    package_root: Path,
    request: str,
) -> dict[str, Any]:
    """Generate and validate HTML using only the selected isolated package."""

    runner = r"""
import json
import os
import sys
from pathlib import Path

payload = json.loads(sys.stdin.read())
package_root = Path(payload["package_root"]).resolve()
request = str(payload["request"])

sys.path.insert(0, str(package_root.parent))

result = {
    "ok": False,
    "html": "",
    "problem": "",
    "attempts": 0,
    "raw_characters": 0,
    "package_root": str(package_root),
}

try:
    from sophyane.main import get_secret
    from sophyane.providers.gemini import GeminiProvider
    from sophyane import adaptive_execution

    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or get_secret("gemini", "GEMINI_API_KEY")
    )
    if not api_key:
        raise RuntimeError("Gemini API key not found")

    provider = GeminiProvider(
        api_key=api_key,
        model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        timeout=300,
        temperature=0.0,
        max_tokens=8192,
    )

    def ask(prompt: str) -> str:
        response = provider.generate(
            (
                "SLI_BENCHMARK_ANALYSIS\n"
                "Return the exact artifact format requested. "
                "Do not include commentary.\n\n"
                + prompt
            ),
            (
                "You generate compact, complete, self-contained browser "
                "artifacts for deterministic evaluation."
            ),
        )
        return str(getattr(response, "text", response) or "")

    raw = ask(adaptive_execution._raw_html_prompt(request))
    result["raw_characters"] = len(raw)

    html = adaptive_execution._extract_html(raw)
    partial = adaptive_execution._extract_partial_html(raw)

    for attempt in range(1, 3):
        result["attempts"] = attempt
        problem = (
            adaptive_execution._validate_html(html, request)
            if html is not None
            else "document has no closing </html>"
        )

        if html is not None and not problem:
            break

        if partial is None and html is not None:
            partial = adaptive_execution._prepare_for_continuation(html)
        elif partial is not None:
            partial = adaptive_execution._prepare_for_continuation(partial)

        if partial is None:
            break

        continuation = ask(
            adaptive_execution._html_continuation_prompt(
                partial,
                problem,
            )
        )
        partial = adaptive_execution._join_html_continuation(
            partial,
            continuation,
        )
        html = adaptive_execution._extract_html(partial)

    if html is None:
        result["problem"] = "provider returned no complete HTML document"
    else:
        result["html"] = html
        result["problem"] = adaptive_execution._validate_html(
            html,
            request,
        )
        result["ok"] = not bool(result["problem"])

except Exception as error:
    result["problem"] = f"{type(error).__name__}: {error}"

print("__SOPHYANE_ARTIFACT_JSON__" + json.dumps(result))
"""

    environment = os.environ.copy()
    package_parent = str(package_root.resolve().parent)
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        package_parent
        if not existing_pythonpath
        else package_parent + os.pathsep + existing_pythonpath
    )

    try:
        completed = subprocess.run(
            [sys.executable, "-c", runner],
            input=json.dumps(
                {
                    "package_root": str(package_root),
                    "request": request,
                }
            ),
            text=True,
            capture_output=True,
            timeout=420,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "html": "",
            "problem": "isolated artifact generation timed out",
            "attempts": 0,
            "raw_characters": 0,
            "returncode": None,
        }

    marker = "__SOPHYANE_ARTIFACT_JSON__"
    parsed: dict[str, Any] | None = None

    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(marker):
            try:
                value = json.loads(line[len(marker):])
                if isinstance(value, dict):
                    parsed = value
            except json.JSONDecodeError:
                parsed = None
            break

    if parsed is None:
        parsed = {
            "ok": False,
            "html": "",
            "problem": "isolated generator returned no parseable result",
            "attempts": 0,
            "raw_characters": 0,
        }

    parsed["returncode"] = completed.returncode
    parsed["stdout_tail"] = completed.stdout[-2000:]
    parsed["stderr_tail"] = completed.stderr[-2000:]
    return parsed


_REQUIRED_EXPORTS = {
    "runtime_browser_patch.py": {
        "functions": {"install_browser_patch"},
        "classes": set(),
    },
}


def _public_api(path: Path) -> tuple[set[str], set[str]]:
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions: set[str] = set()
    classes: set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)

    return functions, classes



def verify_non_destructive_replacements(
    baseline_root: Path,
    candidate_root: Path,
    changed_paths: list[str],
) -> None:
    """Reject suspicious whole-file rewrites before expensive benchmarks."""

    maximum_removed_ratio = float(
        os.environ.get("SOPHYANE_MAX_REMOVED_LINE_RATIO", "0.60")
    )
    minimum_large_file_lines = int(
        os.environ.get("SOPHYANE_DESTRUCTIVE_GATE_MIN_LINES", "80")
    )
    minimum_preserved_ratio = float(
        os.environ.get("SOPHYANE_MIN_PRESERVED_LINE_RATIO", "0.40")
    )
    minimum_content_similarity = float(
        os.environ.get("SOPHYANE_MIN_CONTENT_SIMILARITY", "0.35")
    )

    violations: list[str] = []

    for relative_path in changed_paths:
        baseline_file = baseline_root / relative_path
        candidate_file = candidate_root / relative_path

        if not baseline_file.is_file() or not candidate_file.is_file():
            continue

        try:
            baseline_text = baseline_file.read_text(encoding="utf-8")
            candidate_text = candidate_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        baseline_lines = baseline_text.splitlines()
        candidate_lines = candidate_text.splitlines()

        old_count = len(baseline_lines)
        new_count = len(candidate_lines)

        if old_count < minimum_large_file_lines:
            continue

        removed_count = max(0, old_count - new_count)
        removed_ratio = removed_count / old_count
        preserved_ratio = new_count / old_count

        import difflib

        content_similarity = difflib.SequenceMatcher(
            None,
            baseline_lines,
            candidate_lines,
            autojunk=False,
        ).ratio()

        if (
            removed_ratio > maximum_removed_ratio
            or preserved_ratio < minimum_preserved_ratio
            or content_similarity < minimum_content_similarity
        ):
            violations.append(
                f"{relative_path}: {old_count}→{new_count} lines, "
                f"removed_ratio={removed_ratio:.2%}, "
                f"preserved_ratio={preserved_ratio:.2%}, "
                f"content_similarity={content_similarity:.2%}"
            )

    if violations:
        raise ValueError(
            "destructive candidate replacement rejected; "
            "make a focused amendment instead of rewriting most of a runtime file: "
            + "; ".join(violations)
        )


def verify_required_exports(
    baseline_root: Path,
    candidate_root: Path,
) -> None:
    for relative_path, requirements in _REQUIRED_EXPORTS.items():
        baseline_file = baseline_root / relative_path
        candidate_file = candidate_root / relative_path

        if not baseline_file.is_file():
            raise ValueError(
                f"required baseline runtime module missing: {relative_path}"
            )

        if not candidate_file.is_file():
            raise ValueError(
                f"required candidate runtime module missing: {relative_path}"
            )

        baseline_functions, baseline_classes = _public_api(baseline_file)
        candidate_functions, candidate_classes = _public_api(candidate_file)

        required_functions = (
            set(requirements["functions"]) & baseline_functions
        )
        required_classes = (
            set(requirements["classes"]) & baseline_classes
        )

        missing_functions = required_functions - candidate_functions
        missing_classes = required_classes - candidate_classes

        if missing_functions or missing_classes:
            raise ValueError(
                f"{relative_path} removed required exports: "
                f"functions={sorted(missing_functions)}, "
                f"classes={sorted(missing_classes)}"
            )


def run_improvement(failure_description: str) -> int:
    if not LIVE_PACKAGE.is_dir():
        print(f"ERROR: Sophyane package not found: {LIVE_PACKAGE}")
        return 2

    run_id = (
        time.strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    run_dir = RUNS_ROOT / run_id
    baseline_container = run_dir / "baseline"
    candidate_container = run_dir / "candidate"
    baseline_package = baseline_container / "sophyane"
    candidate_package = candidate_container / "sophyane"

    run_dir.mkdir(parents=True, exist_ok=False)

    print(f"◆ Guarded improvement run: {run_id}")
    print(f"◆ Run directory: {run_dir}")
    print("◆ Copying live package into isolated baseline and candidate…")

    shutil.copytree(
        LIVE_PACKAGE,
        baseline_package,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".git",
        ),
    )
    shutil.copytree(
        LIVE_PACKAGE,
        candidate_package,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".git",
        ),
    )

    baseline_manifest = package_manifest(baseline_package)
    write_json(run_dir / "baseline-manifest.json", baseline_manifest)
    write_json(
        run_dir / "failure.json",
        {
            "run_id": run_id,
            "failure": failure_description,
            "created_at": time.time(),
            "live_package": str(LIVE_PACKAGE),
            "live_mutation_allowed": False,
        },
    )

    print("◆ Running baseline syntax/import/product gates…")
    baseline_gates = run_gates(baseline_container)
    baseline_score = gate_score(baseline_gates)
    write_json(
        run_dir / "baseline-gates.json",
        {
            "score": baseline_score,
            "results": [item.to_dict() for item in baseline_gates],
        },
    )

    for result in baseline_gates:
        marker = "✓" if result.ok else "✗"
        print(f"  {marker} {result.name}")

    print(f"◆ Baseline gate score: {baseline_score}/100")
    print("◆ Launching existing Sophyane multi-agent runtime…")

    from sophyane.multiagent import MultiAgentRuntime

    backend = provider_backend()
    runtime = MultiAgentRuntime(
        backend=backend,
        max_workers=3,
        max_attempts=2,
    )

    emit_event(
        "multiagent",
        "start",
        "Launching planner, coder and reviewer orchestration",
    )
    agent_started_at = time.monotonic()
    agent_result = runtime.run(
        improvement_prompt(
            failure_description,
            baseline_manifest,
            baseline_gates,
        ),
        mode="multi",
    )

    write_json(
        run_dir / "multiagent-result.json",
        agent_result.to_dict(),
    )
    (run_dir / "reviewer-output.txt").write_text(
        agent_result.final_output,
        encoding="utf-8",
    )

    emit_event(
        "multiagent",
        "complete",
        "Agent orchestration returned",
        elapsed=f"{time.monotonic() - agent_started_at:.1f}s",
    )
    raw_proposal = extract_json_object(agent_result.final_output)

    if (
        raw_proposal is not None
        and not proposal_searches_are_grounded(
            raw_proposal,
            candidate_package,
        )
    ):
        emit_event(
            "reviewer",
            "grounding-retry",
            "Initial proposal contains ungrounded edits; retrying with machine-generated anchor IDs",
        )
        raw_proposal = None

    # The generic multi-agent reviewer may receive very large worker outputs and
    # return JSON truncated inside a file-content string. Retry synthesis using
    # a deliberately compact context and the same direct Gemini backend.
    if raw_proposal is None:
        compact_workers = []
        for worker in agent_result.workers:
            if worker.status != "completed" or worker.role == "reviewer":
                continue
            output = str(worker.output or "").strip()
            compact_workers.append(
                f"### {worker.role}\n{output[:1800]}"
            )

        compact_context = "\n\n".join(compact_workers)[:9000]

        grounding_candidates = [
            "runtime_self_contained_html_patch.py",
            "adaptive_execution.py",
            "html_repair_policy.py",
        ]
        grounded_sources: list[str] = []
        grounded_characters = 0
        grounding_limit = 18000

        for relative_name in grounding_candidates:
            source_path = candidate_package / relative_name

            if not source_path.is_file():
                continue

            source_text = source_path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            remaining = grounding_limit - grounded_characters
            if remaining <= 0:
                break

            source_text = source_text[:remaining]
            grounded_sources.append(
                f"===== EXACT FILE: {relative_name} =====\n"
                f"{source_text}"
            )
            grounded_characters += len(source_text)

        grounded_context = "\n\n".join(grounded_sources)

        anchor_catalog = source_anchor_catalog(
            candidate_package,
            grounding_candidates,
        )
        anchor_lines: list[str] = []

        for anchor_id, anchor in anchor_catalog.items():
            display = anchor["search"].rstrip("\r\n")
            anchor_lines.append(
                f"{anchor_id} => {display}"
            )

        exact_anchor_context = "\n".join(anchor_lines)[:18000]

        retry_prompt = f"""
The previous reviewer response was truncated and was not valid JSON.

ORIGINAL FAILURE:
{failure_description}

COMPACT SPECIALIST FINDINGS:
{compact_context}

EXACT CURRENT SOURCE FILES:
{grounded_context}

MACHINE-GENERATED EXACT ANCHORS:
{exact_anchor_context}

Return exactly one valid JSON object and nothing else, using this schema:
{{
  "hypothesis": "concise root cause and expected improvement",
  "failure_kind": "incomplete_artifact or requirement_missing or other",
  "files": [
    {{
      "path": "relative/path/inside/sophyane",
      "edits": [
        {{
          "search": "exact text copied verbatim from an EXACT CURRENT SOURCE FILE",
          "replace": "bounded replacement text",
          "expected_occurrences": 1
        }}
      ]
    }}
  ],
  "focused_tests": ["specific command or test"],
  "risks": ["specific remaining risk"],
  "rollback_notes": "how to revert"
}}

STRICT LIMITS:
- Propose exactly 1 existing file shown under EXACT CURRENT SOURCE FILES.
- Use normally 1 to 3 compact edits.
- Every edit must use anchor_id.
- Copy anchor_id exactly from MACHINE-GENERATED EXACT ANCHORS.
- Never invent an anchor_id or source snippet.
- Choose the correct existing anchor_id from MACHINE-GENERATED EXACT ANCHORS.
- Use only modules, classes and functions shown in the exact source.
- Do not invent conceptual APIs or placeholder imports.
- Do not create a new subsystem.
- Do not return complete file content, Base64, gzip, unified diff, or Markdown.
- Return only compact anchor_id-based edits; do not return a complete file.
- JSON must parse with Python json.loads().
- Never return a complete source file, Base64 payload, gzip payload, unified diff, or Markdown code fence.
- For every proposed file, return `path` and a short `edits` array containing anchor_id-based replacement operations.
- Each edit must contain only `anchor_id` and `replace`; the runtime resolves the exact search text.
- The file object format is exactly: {{"path":"relative/file.py","edits":[{{"anchor_id":"relative/file.py:L123","replace":"REPLACEMENT_TEXT"}}]}}.
- Keep the proposal compact: change one existing behavior-owning file and normally use one to three narrowly targeted edits.
- Before responding, verify every anchor_id exists verbatim under MACHINE-GENERATED EXACT ANCHORS.
- The outer response must parse with Python json.loads().

- Preserve every existing public function.
- Do not invent imports or introduce new third-party dependencies unless the failure explicitly requires them.
- Do not write 'existing content goes here'.
- Produce a bounded incremental change.
""".strip()

        for retry_number in range(1, 3):
            emit_event(
                "reviewer",
                "retry-start",
                "Requesting compact structured proposal",
                retry=retry_number,
            )
            retry_started_at = time.monotonic()
            try:
                retry_output = backend(
                    retry_prompt,
                    (
                        "You are a strict software proposal synthesizer. "
                        "Select only files that execute in the reported failing runtime path. "
                        "For browser or HTML artifact failures, never select sli_schema.py or "
                        "metadata-only files. Prefer generation or repair code over validation code "
                        "when required behavior is absent from the generated HTML. Select a validator "
                        "only when correct HTML is being rejected or measured incorrectly. "
                        "The candidate must produce an observably different generated artifact. "
                        "Return only compact anchor_id-based edits against one existing file; "
                        "never return the complete file or an encoded file payload. "
                        "Return compact, complete, syntactically valid JSON only."
                    ),
                )
            except Exception as error:  # noqa: BLE001
                retry_output = f"BACKEND_ERROR: {type(error).__name__}: {error}"

            emit_event(
                "reviewer",
                "retry-complete",
                "Reviewer retry returned",
                retry=retry_number,
                characters=len(retry_output),
                elapsed=f"{time.monotonic() - retry_started_at:.1f}s",
            )
            (run_dir / f"reviewer-retry-{retry_number}.txt").write_text(
                retry_output,
                encoding="utf-8",
            )
            emit_event(
                "reviewer",
                "saved",
                "Reviewer retry output saved",
                file=f"reviewer-retry-{retry_number}.txt",
            )

            raw_proposal = extract_json_object(retry_output)
            if raw_proposal is not None:
                print(
                    f"✓ Recovered valid compact proposal on reviewer retry "
                    f"{retry_number}."
                )
                break

            retry_prompt += (
                "\n\nYour preceding retry was still invalid or truncated. "
                "Reduce the proposal further: one small behavior-owning file only, concise. "
                    "For browser artifact failures choose an executed generation or repair file when "
                    "the required HTML behavior is missing. Choose validation code only when valid HTML "
                    "is incorrectly rejected—not when has_large_control_rule or another artifact check is false. "
                    "Never choose sli_schema.py, metadata, documentation, or database code. "
                    "The replacement must alter observable generated HTML behavior. "
                    "Return one to three compact edits containing only anchor_id and replace; copy each anchor_id exactly from MACHINE-GENERATED EXACT ANCHORS; "
                    "do not serialize or encode the complete source file. "
                "strings, and valid JSON with every quote and brace closed."
            )

    if raw_proposal is None:
        verdict = "rejected_invalid_structured_proposal"
        print("✗ Reviewer did not return a valid JSON proposal.")
        record_ledger(
            run_id=run_id,
            failure=failure_description,
            proposal=None,
            baseline_score=baseline_score,
            candidate_score=0.0,
            verdict=verdict,
            run_dir=run_dir,
        )
        write_json(
            run_dir / "verdict.json",
            {
                "ok": False,
                "verdict": verdict,
                "live_modified": False,
            },
        )
        return 1

    try:
        proposal = normalise_proposal(
            raw_proposal,
            candidate_package,
        )
    except Exception as error:  # noqa: BLE001
        verdict = "rejected_unsafe_or_invalid_proposal"
        print(f"✗ Proposal rejected: {error}")
        write_json(
            run_dir / "proposal-rejection.json",
            {
                "error": f"{type(error).__name__}: {error}",
                "raw_proposal": raw_proposal,
            },
        )
        record_ledger(
            run_id=run_id,
            failure=failure_description,
            proposal=None,
            baseline_score=baseline_score,
            candidate_score=0.0,
            verdict=verdict,
            run_dir=run_dir,
        )
        return 1

    emit_event(
        "proposal",
        "accepted",
        "Structured proposal validated",
        files=len(proposal["files"]),
        failure_kind=proposal.get("failure_kind", "unknown"),
        hypothesis=proposal.get("hypothesis", "")[:180],
    )
    for proposed_file in proposal["files"]:
        emit_event(
            "proposal",
            "file",
            "Proposal includes candidate file",
            file=proposed_file["path"],
            characters=len(proposal_file_payload(proposed_file)),
            exists=proposed_file.get("exists_in_baseline"),
            high_risk=proposed_file.get("high_risk"),
        )

    write_json(run_dir / "candidate-proposal.json", proposal)

    high_risk = [
        item["path"]
        for item in proposal["files"]
        if item.get("high_risk")
    ]

    if high_risk:
        print(
            "⚠ Proposal touches high-risk files: "
            + ", ".join(high_risk)
        )

    print(
        f"◆ Applying {len(proposal['files'])} proposed file replacement(s) "
        "inside isolated candidate only…"
    )

    changed_paths = apply_proposal(candidate_package, proposal)
    candidate_manifest = package_manifest(candidate_package)
    write_json(run_dir / "candidate-manifest.json", candidate_manifest)

    emit_event(
        "destructive-change-gate",
        "start",
        "Checking candidate files for destructive whole-file replacement",
    )
    verify_non_destructive_replacements(
        baseline_package,
        candidate_package,
        changed_paths,
    )
    emit_event(
        "destructive-change-gate",
        "complete",
        "Candidate replacements preserve sufficient existing implementation",
    )

    emit_event(
        "validator",
        "start",
        "Checking required public functions and classes",
    )
    verify_required_exports(
        baseline_package,
        candidate_package,
    )
    emit_event(
        "validator",
        "complete",
        "Required public API preserved",
    )

    emit_event(
        "benchmark",
        "start",
        "Running candidate syntax, import and product gates",
    )
    print("◆ Running candidate syntax/import/product gates…", flush=True)
    candidate_gates = run_gates(candidate_container)
    candidate_score = gate_score(candidate_gates)
    emit_event(
        "benchmark",
        "complete",
        "Candidate gates finished",
        score=f"{candidate_score:.1f}/100",
        gates=len(candidate_gates),
    )

    write_json(
        run_dir / "candidate-gates.json",
        {
            "score": candidate_score,
            "results": [item.to_dict() for item in candidate_gates],
        },
    )

    for result in candidate_gates:
        marker = "✓" if result.ok else "✗"
        print(f"  {marker} {result.name}")

    regressions = [
        candidate.name
        for baseline, candidate in zip(
            baseline_gates,
            candidate_gates,
            strict=False,
        )
        if baseline.ok and not candidate.ok
    ]

    all_candidate_gates_pass = all(
        result.ok for result in candidate_gates
    )
    non_regression = not regressions
    score_not_worse = candidate_score >= baseline_score

    emit_event(
        "improvement-gate",
        "start",
        "Comparing failure-targeted evidence in baseline and candidate",
    )

    baseline_target = failure_target_score(
        baseline_package,
        changed_paths,
        failure_description,
    )
    candidate_target = failure_target_score(
        candidate_package,
        changed_paths,
        failure_description,
    )
    target_improvement = round(
        candidate_target["score"] - baseline_target["score"],
        2,
    )
    minimum_target_improvement = float(
        os.environ.get("SOPHYANE_MIN_TARGET_IMPROVEMENT", "0.1")
    )
    measurable_improvement = (
        target_improvement >= minimum_target_improvement
    )

    write_json(
        run_dir / "failure-target-evaluation.json",
        {
            "minimum_required_improvement": minimum_target_improvement,
            "actual_improvement": target_improvement,
            "measurable_improvement": measurable_improvement,
            "baseline": baseline_target,
            "candidate": candidate_target,
        },
    )

    emit_event(
        "improvement-gate",
        "complete",
        "Failure-targeted comparison finished",
        baseline=baseline_target["score"],
        candidate=candidate_target["score"],
        improvement=target_improvement,
        required=minimum_target_improvement,
        passed=measurable_improvement,
    )

    bad_mobile_html = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body{margin:0;width:100vw;min-height:100vh}
button{width:30px;height:24px;font-size:10px}
</style>
</head>
<body>
<main>
<h1>Guess the Word</h1>
<p id="score">Score: 0</p>
<button id="start">Go</button>
<button id="answer">A</button>
</main>
<script>
document.querySelector("#start").addEventListener("click",()=>{});
document.querySelector("#answer").addEventListener("click",()=>{});
</script>
</body>
</html>"""

    good_mobile_html = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
html,body{margin:0;width:100%;min-height:100%}
body{min-height:100vh;min-height:100dvh;display:grid;place-items:center}
main{width:min(100%,42rem);padding:clamp(16px,4vw,32px)}
.controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
button{
min-width:48px;
min-height:48px;
padding:14px 18px;
font-size:clamp(1rem,4vw,1.35rem);
touch-action:manipulation
}
@media(max-width:480px){
.controls{grid-template-columns:1fr}
button{width:100%;min-height:52px}
}
</style>
</head>
<body>
<main>
<h1>Guess the Word</h1>
<p id="score">Score: 0</p>
<div class="controls">
<button id="start">Start game</button>
<button id="answer">Submit answer</button>
</div>
</main>
<script>
document.querySelector("#start").addEventListener("pointerdown",()=>{});
document.querySelector("#answer").addEventListener("pointerdown",()=>{});
</script>
</body>
</html>"""

    emit_event(
        "artifact-gate",
        "start",
        "Comparing observable mobile artifact validation",
    )

    baseline_bad_artifact = mobile_artifact_score(
        baseline_package,
        bad_mobile_html,
        failure_description,
    )
    baseline_good_artifact = mobile_artifact_score(
        baseline_package,
        good_mobile_html,
        failure_description,
    )
    candidate_bad_artifact = mobile_artifact_score(
        candidate_package,
        bad_mobile_html,
        failure_description,
    )
    candidate_good_artifact = mobile_artifact_score(
        candidate_package,
        good_mobile_html,
        failure_description,
    )

    artifact_applicable = any(
        result.get("applicable")
        for result in (
            baseline_bad_artifact,
            baseline_good_artifact,
            candidate_bad_artifact,
            candidate_good_artifact,
        )
    )

    baseline_artifact_checks = {
        "rejects_undersized_controls": bool(
            baseline_bad_artifact.get("problem")
        ),
        "accepts_responsive_controls": not bool(
            baseline_good_artifact.get("problem")
        ),
    }
    candidate_artifact_checks = {
        "rejects_undersized_controls": bool(
            candidate_bad_artifact.get("problem")
        ),
        "accepts_responsive_controls": not bool(
            candidate_good_artifact.get("problem")
        ),
    }

    baseline_artifact_score = round(
        100.0
        * sum(baseline_artifact_checks.values())
        / len(baseline_artifact_checks),
        2,
    )
    candidate_artifact_score = round(
        100.0
        * sum(candidate_artifact_checks.values())
        / len(candidate_artifact_checks),
        2,
    )
    artifact_improvement = round(
        candidate_artifact_score - baseline_artifact_score,
        2,
    )

    minimum_artifact_improvement = float(
        os.environ.get("SOPHYANE_MIN_ARTIFACT_IMPROVEMENT", "0.1")
    )
    artifact_measurable = (
        not artifact_applicable
        or artifact_improvement >= minimum_artifact_improvement
    )

    artifact_evaluation = {
        "applicable": artifact_applicable,
        "minimum_required_improvement": (
            minimum_artifact_improvement if artifact_applicable else 0.0
        ),
        "actual_improvement": artifact_improvement,
        "measurable_improvement": artifact_measurable,
        "baseline": {
            "score": baseline_artifact_score,
            "checks": baseline_artifact_checks,
            "bad_fixture": baseline_bad_artifact,
            "good_fixture": baseline_good_artifact,
        },
        "candidate": {
            "score": candidate_artifact_score,
            "checks": candidate_artifact_checks,
            "bad_fixture": candidate_bad_artifact,
            "good_fixture": candidate_good_artifact,
        },
    }

    write_json(
        run_dir / "artifact-behavior-evaluation.json",
        artifact_evaluation,
    )

    emit_event(
        "artifact-gate",
        "complete",
        "Observable mobile artifact comparison finished",
        baseline=baseline_artifact_score,
        candidate=candidate_artifact_score,
        improvement=artifact_improvement,
        required=(
            minimum_artifact_improvement
            if artifact_applicable
            else 0.0
        ),
        passed=artifact_measurable,
    )

    emit_event(
        "generated-artifact-gate",
        "start",
        "Generating equivalent browser artifacts from isolated baseline and candidate",
    )

    generated_artifact_applicable = bool(artifact_applicable)

    if generated_artifact_applicable:
        baseline_generated = generate_isolated_browser_artifact(
            baseline_package,
            failure_description,
        )
        candidate_generated = generate_isolated_browser_artifact(
            candidate_package,
            failure_description,
        )

        generated_dir = run_dir / "generated-artifacts"
        generated_dir.mkdir(parents=True, exist_ok=True)

        baseline_generated_html = str(
            baseline_generated.get("html", "")
        )
        candidate_generated_html = str(
            candidate_generated.get("html", "")
        )

        if baseline_generated_html:
            (
                generated_dir / "baseline.html"
            ).write_text(
                baseline_generated_html,
                encoding="utf-8",
            )

        if candidate_generated_html:
            (
                generated_dir / "candidate.html"
            ).write_text(
                candidate_generated_html,
                encoding="utf-8",
            )

        baseline_generated_validation = mobile_artifact_score(
            baseline_package,
            baseline_generated_html,
            failure_description,
        )
        candidate_generated_validation = mobile_artifact_score(
            candidate_package,
            candidate_generated_html,
            failure_description,
        )

        baseline_generated_score = float(
            baseline_generated_validation.get(
                "score",
                (
                    100.0
                    if baseline_generated.get("ok")
                    and not baseline_generated_validation.get("problem")
                    else 0.0
                ),
            )
        )
        candidate_generated_score = float(
            candidate_generated_validation.get(
                "score",
                (
                    100.0
                    if candidate_generated.get("ok")
                    and not candidate_generated_validation.get("problem")
                    else 0.0
                ),
            )
        )
    else:
        baseline_generated = {
            "ok": True,
            "html": "",
            "problem": "",
            "skipped": True,
        }
        candidate_generated = {
            "ok": True,
            "html": "",
            "problem": "",
            "skipped": True,
        }
        baseline_generated_validation = {
            "applicable": False,
            "problem": "",
        }
        candidate_generated_validation = {
            "applicable": False,
            "problem": "",
        }
        baseline_generated_score = 0.0
        candidate_generated_score = 0.0

    generated_artifact_improvement = round(
        candidate_generated_score - baseline_generated_score,
        2,
    )

    maximum_generated_regression = float(
        os.environ.get(
            "SOPHYANE_MAX_GENERATED_ARTIFACT_REGRESSION",
            "0.0",
        )
    )

    generated_artifact_non_regression = (
        not generated_artifact_applicable
        or generated_artifact_improvement
        >= -maximum_generated_regression
    )

    minimum_generated_artifact_improvement = float(
        os.environ.get(
            "SOPHYANE_MIN_GENERATED_ARTIFACT_IMPROVEMENT",
            "0.1",
        )
    )
    generated_artifact_measurable = (
        not generated_artifact_applicable
        or generated_artifact_improvement
        >= minimum_generated_artifact_improvement
    )

    generated_artifact_evaluation = {
        "applicable": generated_artifact_applicable,
        "maximum_allowed_regression": (
            maximum_generated_regression
            if generated_artifact_applicable
            else 0.0
        ),
        "actual_improvement": generated_artifact_improvement,
        "minimum_required_improvement": (
            minimum_generated_artifact_improvement
            if generated_artifact_applicable
            else 0.0
        ),
        "measurable_improvement": generated_artifact_measurable,
        "non_regression": generated_artifact_non_regression,
        "baseline": {
            "score": baseline_generated_score,
            "generation": baseline_generated,
            "validation": baseline_generated_validation,
            "artifact_file": (
                "generated-artifacts/baseline.html"
                if baseline_generated.get("html")
                else None
            ),
        },
        "candidate": {
            "score": candidate_generated_score,
            "generation": candidate_generated,
            "validation": candidate_generated_validation,
            "artifact_file": (
                "generated-artifacts/candidate.html"
                if candidate_generated.get("html")
                else None
            ),
        },
    }

    write_json(
        run_dir / "generated-artifact-evaluation.json",
        generated_artifact_evaluation,
    )

    emit_event(
        "generated-artifact-gate",
        "complete",
        "Generated browser artifact comparison finished",
        baseline=baseline_generated_score,
        candidate=candidate_generated_score,
        improvement=generated_artifact_improvement,
        maximum_regression=maximum_generated_regression,
        minimum_improvement=minimum_generated_artifact_improvement,
        non_regression=generated_artifact_non_regression,
        measurable=generated_artifact_measurable,
        passed=(
            generated_artifact_non_regression
            and generated_artifact_measurable
        ),
    )

    eligible = (
        all_candidate_gates_pass
        and non_regression
        and score_not_worse
        and measurable_improvement
        and artifact_measurable
        and generated_artifact_non_regression
        and generated_artifact_measurable
    )

    if not all_candidate_gates_pass or not non_regression or not score_not_worse:
        verdict = "rejected_by_candidate_gates"
    elif not measurable_improvement:
        verdict = "rejected_no_measurable_improvement"
    elif not artifact_measurable:
        verdict = "rejected_no_artifact_behavior_improvement"
    elif not generated_artifact_non_regression:
        verdict = "rejected_generated_artifact_regression"
    elif not generated_artifact_measurable:
        verdict = "rejected_no_generated_artifact_improvement"
    else:
        verdict = "eligible_for_human_review"

    verdict_payload = {
        "ok": eligible,
        "verdict": verdict,
        "run_id": run_id,
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "changed_paths": changed_paths,
        "high_risk_paths": high_risk,
        "regressions": regressions,
        "all_candidate_gates_pass": all_candidate_gates_pass,
        "benchmark_non_regression": non_regression,
        "score_not_worse": score_not_worse,
        "baseline_target_score": baseline_target["score"],
        "candidate_target_score": candidate_target["score"],
        "target_improvement": target_improvement,
        "minimum_target_improvement": minimum_target_improvement,
        "measurable_improvement": measurable_improvement,
        "artifact_applicable": artifact_applicable,
        "baseline_artifact_score": baseline_artifact_score,
        "candidate_artifact_score": candidate_artifact_score,
        "artifact_improvement": artifact_improvement,
        "minimum_artifact_improvement": minimum_artifact_improvement,
        "artifact_measurable": artifact_measurable,
        "generated_artifact_applicable": generated_artifact_applicable,
        "baseline_generated_artifact_score": baseline_generated_score,
        "candidate_generated_artifact_score": candidate_generated_score,
        "generated_artifact_improvement": generated_artifact_improvement,
        "minimum_generated_artifact_improvement": minimum_generated_artifact_improvement,
        "maximum_generated_artifact_regression": maximum_generated_regression,
        "generated_artifact_non_regression": generated_artifact_non_regression,
        "generated_artifact_measurable": generated_artifact_measurable,
        "fixture_artifact_gate_diagnostic_only": False,
        "human_approval_required": True,
        "promotion_available": False,
        "live_modified": False,
        "candidate_package": str(candidate_package),
    }

    write_json(run_dir / "verdict.json", verdict_payload)

    record_ledger(
        run_id=run_id,
        failure=failure_description,
        proposal=proposal,
        baseline_score=baseline_score,
        candidate_score=candidate_score,
        verdict=verdict,
        run_dir=run_dir,
    )

    print()
    evidence_files = sorted(
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    emit_event(
        "evidence",
        "inventory",
        "Run evidence written",
        files=len(evidence_files),
        directory=run_dir,
    )

    print("════════════════════════════════════════")
    print(f"Verdict: {verdict}")
    print(f"Baseline: {baseline_score}/100")
    print(f"Candidate: {candidate_score}/100")
    print(
        "Failure target: "
        f"{baseline_target['score']} → {candidate_target['score']} "
        f"(Δ {target_improvement:+.2f}, required "
        f"{minimum_target_improvement:+.2f})"
    )
    print(
        "Artifact behavior: "
        f"{baseline_artifact_score:.2f} → "
        f"{candidate_artifact_score:.2f} "
        f"(Δ {artifact_improvement:+.2f}, required "
        f"{minimum_artifact_improvement if artifact_applicable else 0.0:+.2f})"
    )
    print(
        "Generated artifact: "
        f"{baseline_generated_score:.2f} → "
        f"{candidate_generated_score:.2f} "
        f"(Δ {generated_artifact_improvement:+.2f}, required "
        f"{minimum_generated_artifact_improvement if generated_artifact_applicable else 0.0:+.2f}, "
        f"maximum regression "
        f"{maximum_generated_regression if generated_artifact_applicable else 0.0:+.2f})"
    )
    print(f"Changed files: {len(changed_paths)}")
    print(f"Evidence: {run_dir}")
    print("Live Sophyane modified: NO")
    print("Automatic promotion: DISABLED")
    print("════════════════════════════════════════")

    return 0 if eligible else 1


def doctor() -> int:
    checks = {
        "live_package": LIVE_PACKAGE.is_dir(),
        "python": bool(sys.executable),
        "multiagent": (LIVE_PACKAGE / "multiagent.py").is_file(),
        "improvement_kernel": (
            LIVE_PACKAGE / "improvement_kernel.py"
        ).is_file(),
        "benchmark_cli": (
            LIVE_PACKAGE / "benchmark_cli.py"
        ).is_file(),
        "ledger": (
            LIVE_PACKAGE / "self_improve/ledger.py"
        ).is_file(),
    }

    print(json.dumps(checks, indent=2))
    return 0 if all(checks.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-self-improve",
        description=(
            "Generate and test an isolated Sophyane self-improvement "
            "candidate without modifying the live installation."
        ),
    )
    parser.add_argument(
        "failure",
        nargs="*",
        help="failure or weakness Sophyane should investigate",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="verify prerequisites only",
    )
    args = parser.parse_args()

    if args.doctor:
        return doctor()

    description = " ".join(args.failure).strip()

    if not description:
        parser.error("provide a failure description or use --doctor")

    return run_improvement(description)


if __name__ == "__main__":
    raise SystemExit(main())
