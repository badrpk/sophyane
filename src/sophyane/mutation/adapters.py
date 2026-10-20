"""Static language analysis for mutation-lab source files.

Invariants use ``function:name`` or ``class:name``. Unknown forms fail closed.
Candidate files are parsed as data; they are never imported or executed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class AnalysisResult:
    language: str
    path: str
    ok: bool
    semantic_digest: str | None
    failure_boundary: str | None
    diagnostics: str


def _missing_invariant(invariants: Sequence[str], names: dict[str, set[str]]) -> str | None:
    for invariant in invariants:
        kind, separator, name = invariant.partition(":")
        if not separator or not name or kind not in names:
            return f"unsupported invariant: {invariant!r}"
        if name not in names[kind]:
            return f"missing invariant: {invariant}"
    return None


class PythonAdapter:
    def analyze(self, path: Path, invariants: Sequence[str]) -> AnalysisResult:
        path = Path(path)
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            return AnalysisResult("python", str(path), False, None, "python_io", str(error))
        try:
            # Generates bytecode for validation only; it does not execute source.
            compile(source, str(path), "exec", dont_inherit=True)
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            return AnalysisResult("python", str(path), False, None, "python_syntax", str(error))

        names: dict[str, set[str]] = {"function": set(), "class": set()}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names["function"].add(node.name)
            elif isinstance(node, ast.ClassDef):
                names["class"].add(node.name)
        missing = _missing_invariant(invariants, names)
        if missing:
            return AnalysisResult("python", str(path), False, None, "python_invariant", missing)

        canonical = ast.dump(tree, annotate_fields=True, include_attributes=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return AnalysisResult("python", str(path), True, digest, None, "")


_LOCATION_FIELDS = frozenset({"id", "loc", "range"})


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"nonstandard JSON constant: {value}")


def _normalize_clang_ast(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _normalize_clang_ast(item)
            for key, item in value.items()
            if key not in _LOCATION_FIELDS
        }
    if isinstance(value, list):
        return [_normalize_clang_ast(item) for item in value]
    return value


def _clang_names(root: dict[str, object]) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {"function": set(), "class": set()}
    pending = [root]
    while pending:
        node = pending.pop()
        kind = node.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError("Clang AST node has no kind")
        name = node.get("name")
        if isinstance(name, str):
            if kind in {"FunctionDecl", "CXXMethodDecl", "FunctionTemplateDecl"}:
                names["function"].add(name)
            elif kind in {"CXXRecordDecl", "RecordDecl", "ClassTemplateDecl"}:
                names["class"].add(name)
        children = node.get("inner", [])
        if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
            raise ValueError("Clang AST has unsupported child nodes")
        pending.extend(children)
    return names


class CppAdapter:
    """Analyze C++ syntax; name invariants require declarations, not definitions."""

    def __init__(self, clang_executable: str = "clang++", include_dirs: Sequence[Path] = ()):
        self.clang_executable = clang_executable
        self.include_dirs = tuple(Path(directory) for directory in include_dirs)

    def analyze(self, path: Path, invariants: Sequence[str]) -> AnalysisResult:
        path = Path(path)
        arguments = [
            self.clang_executable,
            "-std=c++17",
            "-fsyntax-only",
            "-Xclang",
            "-ast-dump=json",
            "-x",
            "c++",
        ]
        for directory in self.include_dirs:
            arguments.extend(("-I", str(directory)))
        arguments.extend(("--", str(path.absolute())))
        try:
            completed = subprocess.run(
                arguments, capture_output=True, text=True, check=False, timeout=30
            )
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
            return AnalysisResult("cpp", str(path), False, None, "cpp_tool", str(error))
        if completed.returncode != 0 or completed.stderr.strip():
            diagnostics = completed.stderr.strip() or f"clang++ exited {completed.returncode}"
            return AnalysisResult("cpp", str(path), False, None, "cpp_syntax", diagnostics)

        try:
            tree = json.loads(completed.stdout, parse_constant=_reject_json_constant)
            if (
                not isinstance(tree, dict)
                or tree.get("kind") != "TranslationUnitDecl"
                or not isinstance(tree.get("inner"), list)
            ):
                raise ValueError("Clang did not return a translation-unit AST")
            names = _clang_names(tree)
            canonical = json.dumps(
                _normalize_clang_ast(tree),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        except (ValueError, TypeError, UnicodeError) as error:
            return AnalysisResult("cpp", str(path), False, None, "cpp_ast", str(error))
        missing = _missing_invariant(invariants, names)
        if missing:
            return AnalysisResult("cpp", str(path), False, None, "cpp_invariant", missing)

        return AnalysisResult("cpp", str(path), True, digest, None, "")
