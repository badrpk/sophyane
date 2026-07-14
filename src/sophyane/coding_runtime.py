"""Repository-aware coding tools for Sophyane v16.

The module intentionally uses the Python standard library so it remains portable.
It provides deterministic repository discovery, symbol indexing, context retrieval,
precise text patches, task queues, Git checkpoints, dependency diagnostics and
mechanical acceptance checks.  LLMs choose work; these classes enforce it.
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".json", ".toml",
    ".yaml", ".yml", ".md", ".html", ".css", ".scss", ".sql", ".sh",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".java", ".go", ".rs",
}
IGNORE_PARTS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "coverage",
}


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    path: str
    line: int
    end_line: int


@dataclass
class RepositorySnapshot:
    root: str
    files: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    imports: dict[str, list[str]] = field(default_factory=dict)
    tests: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": self.files,
            "symbols": [asdict(item) for item in self.symbols],
            "imports": self.imports,
            "tests": self.tests,
            "manifests": self.manifests,
            "digest": self.digest,
        }


class RepositoryIndex:
    """Build a lightweight deterministic semantic map of a repository."""

    MANIFEST_NAMES = {
        "pyproject.toml", "setup.py", "requirements.txt", "package.json",
        "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.toml",
        "go.mod", "pom.xml", "build.gradle", "Dockerfile", "docker-compose.yml",
    }

    def __init__(self, root: str | Path, *, max_file_bytes: int = 512_000) -> None:
        self.root = Path(root).expanduser().resolve()
        self.max_file_bytes = max(1_024, int(max_file_bytes))
        self.snapshot = RepositorySnapshot(str(self.root))

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _ignored(path: Path) -> bool:
        return any(part in IGNORE_PARTS for part in path.parts)

    def _iter_files(self) -> Iterable[Path]:
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or self._ignored(path.relative_to(self.root)):
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in self.MANIFEST_NAMES:
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
            except OSError:
                continue
            yield path

    @staticmethod
    def _python_metadata(path: Path, relative: str) -> tuple[list[Symbol], list[str]]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            return [], []
        symbols: list[Symbol] = []
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                symbols.append(
                    Symbol(
                        node.name,
                        kind,
                        relative,
                        int(getattr(node, "lineno", 1)),
                        int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                    )
                )
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return symbols, sorted(set(imports))

    def build(self) -> RepositorySnapshot:
        files: list[str] = []
        symbols: list[Symbol] = []
        imports: dict[str, list[str]] = {}
        tests: list[str] = []
        manifests: list[str] = []
        digest = hashlib.sha256()
        for path in self._iter_files():
            relative = self._relative(path)
            files.append(relative)
            try:
                payload = path.read_bytes()
            except OSError:
                continue
            digest.update(relative.encode())
            digest.update(hashlib.sha256(payload).digest())
            if path.name in self.MANIFEST_NAMES:
                manifests.append(relative)
            if path.name.startswith("test_") or "/tests/" in f"/{relative}":
                tests.append(relative)
            if path.suffix == ".py":
                found, imported = self._python_metadata(path, relative)
                symbols.extend(found)
                if imported:
                    imports[relative] = imported
        self.snapshot = RepositorySnapshot(
            root=str(self.root),
            files=files,
            symbols=symbols,
            imports=imports,
            tests=tests,
            manifests=manifests,
            digest=digest.hexdigest(),
        )
        return self.snapshot

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self.snapshot.files:
            self.build()
        tokens = set(re.findall(r"[A-Za-z0-9_]{2,}", query.lower()))
        scored: list[tuple[int, dict[str, Any]]] = []
        for symbol in self.snapshot.symbols:
            haystack = f"{symbol.name} {symbol.kind} {symbol.path}".lower()
            score = sum(5 for token in tokens if token in symbol.name.lower())
            score += sum(2 for token in tokens if token in haystack)
            if score:
                scored.append((score, {"type": "symbol", **asdict(symbol)}))
        for relative in self.snapshot.files:
            score = sum(2 for token in tokens if token in relative.lower())
            if score:
                scored.append((score, {"type": "file", "path": relative}))
        scored.sort(key=lambda item: (-item[0], json.dumps(item[1], sort_keys=True)))
        return [item for _, item in scored[: max(1, int(limit))]]

    def context(self, query: str, *, max_chars: int = 16_000) -> str:
        results = self.search(query, limit=30)
        paths: list[str] = []
        for item in results:
            path = str(item.get("path", ""))
            if path and path not in paths:
                paths.append(path)
        chunks: list[str] = []
        used = 0
        for relative in paths:
            path = (self.root / relative).resolve()
            if self.root not in path.parents and path != self.root:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            allowance = max_chars - used
            if allowance <= 0:
                break
            excerpt = text[:allowance]
            chunks.append(f"### {relative}\n{excerpt}")
            used += len(excerpt)
        return "\n\n".join(chunks)


class PatchError(RuntimeError):
    pass


class PatchEngine:
    """Apply precise deterministic edits while preserving unrelated content."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def _path(self, relative: str | Path) -> Path:
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError("patch path escapes workspace")
        return path

    def replace_exact(
        self,
        relative: str | Path,
        old: str,
        new: str,
        *,
        expected_count: int = 1,
    ) -> dict[str, Any]:
        path = self._path(relative)
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count != expected_count:
            raise PatchError(f"expected {expected_count} matches, found {count}")
        updated = text.replace(old, new, expected_count)
        path.write_text(updated, encoding="utf-8")
        return self._evidence(path, operation="replace_exact")

    def replace_lines(
        self,
        relative: str | Path,
        start_line: int,
        end_line: int,
        replacement: str,
    ) -> dict[str, Any]:
        path = self._path(relative)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            raise PatchError("invalid line range")
        replacement_lines = replacement.splitlines(keepends=True)
        if replacement and not replacement.endswith("\n"):
            replacement_lines[-1:] = [replacement_lines[-1] + "\n"]
        updated = lines[: start_line - 1] + replacement_lines + lines[end_line:]
        path.write_text("".join(updated), encoding="utf-8")
        return self._evidence(path, operation="replace_lines")

    @staticmethod
    def _evidence(path: Path, *, operation: str) -> dict[str, Any]:
        payload = path.read_bytes()
        return {
            "operation": operation,
            "path": str(path),
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }


@dataclass
class QueueTask:
    id: str
    objective: str
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)
    attempts: int = 0
    result: dict[str, Any] = field(default_factory=dict)


class TaskQueue:
    """Small durable-ready dependency queue used by project-scale plans."""

    def __init__(self, tasks: Iterable[dict[str, Any]] = ()) -> None:
        self.tasks: dict[str, QueueTask] = {}
        for position, raw in enumerate(tasks, start=1):
            task_id = str(raw.get("id") or f"task-{position}")
            if task_id in self.tasks:
                raise ValueError(f"duplicate task id: {task_id}")
            self.tasks[task_id] = QueueTask(
                id=task_id,
                objective=str(raw.get("objective", "")).strip(),
                depends_on=[str(item) for item in raw.get("depends_on", [])],
            )

    def ready(self) -> list[QueueTask]:
        completed = {task.id for task in self.tasks.values() if task.status == "completed"}
        return [
            task for task in self.tasks.values()
            if task.status == "pending" and set(task.depends_on) <= completed
        ]

    def complete(self, task_id: str, result: dict[str, Any]) -> None:
        task = self.tasks[task_id]
        task.status = "completed"
        task.result = result

    def fail(self, task_id: str, result: dict[str, Any]) -> None:
        task = self.tasks[task_id]
        task.status = "failed"
        task.result = result

    def to_dict(self) -> dict[str, Any]:
        return {"tasks": [asdict(task) for task in self.tasks.values()]}


class GitCheckpoint:
    """Create inspectable local Git checkpoints without pushing remotely."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.root, text=True, capture_output=True, check=False
        )

    def available(self) -> bool:
        return (self.root / ".git").exists() and self._run("rev-parse", "--is-inside-work-tree").returncode == 0

    def status(self) -> dict[str, Any]:
        if not self.available():
            return {"available": False, "clean": False, "diff": ""}
        status = self._run("status", "--porcelain")
        diff = self._run("diff", "--no-ext-diff", "--binary")
        return {
            "available": True,
            "clean": not bool(status.stdout.strip()),
            "status": status.stdout,
            "diff": diff.stdout,
        }

    def checkpoint(self, label: str) -> dict[str, Any]:
        if not self.available():
            return {"created": False, "reason": "not_a_git_repository"}
        head = self._run("rev-parse", "HEAD")
        if head.returncode != 0:
            return {"created": False, "reason": head.stderr.strip()}
        return {
            "created": True,
            "label": label,
            "head": head.stdout.strip(),
            "status": self.status(),
            "created_at": time.time(),
        }


class DependencyAdvisor:
    """Diagnose missing Python dependencies; installation remains policy controlled."""

    MISSING_MODULE = re.compile(r"(?:ModuleNotFoundError|ImportError):.*?['\"]([^'\"]+)['\"]")

    @classmethod
    def diagnose(cls, stderr: str) -> dict[str, Any] | None:
        match = cls.MISSING_MODULE.search(stderr)
        if not match:
            return None
        module = match.group(1).split(".", 1)[0]
        return {
            "kind": "missing_python_dependency",
            "module": module,
            "suggested_argv": [sys.executable, "-m", "pip", "install", module],
            "requires_network": True,
        }


class MechanicalVerifier:
    """Evaluate concrete acceptance checks independently from an LLM."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def _path(self, relative: str | Path) -> Path:
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError("verification path escapes workspace")
        return path

    def verify(
        self,
        checks: Iterable[dict[str, Any]],
        *,
        command_observations: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        observations = list(command_observations)
        results: list[dict[str, Any]] = []
        for check in checks:
            kind = str(check.get("type", ""))
            passed = False
            detail = ""
            if kind == "file_exists":
                path = self._path(str(check.get("path", "")))
                passed = path.is_file()
                detail = str(path)
            elif kind == "contains":
                path = self._path(str(check.get("path", "")))
                needle = str(check.get("text", ""))
                try:
                    passed = needle in path.read_text(encoding="utf-8")
                except OSError:
                    passed = False
                detail = f"{path} contains {needle!r}"
            elif kind == "command_exit_zero":
                executable = str(check.get("executable", ""))
                matching = [
                    item for item in observations
                    if item.get("argv") and Path(str(item["argv"][0])).name == executable
                ]
                passed = bool(matching) and matching[-1].get("exit_code") == 0
                detail = json.dumps(matching[-1] if matching else {}, ensure_ascii=False)
            elif kind == "stdout_contains":
                needle = str(check.get("text", ""))
                passed = any(needle in str(item.get("stdout", "")) for item in observations)
                detail = f"stdout contains {needle!r}"
            elif kind == "no_uncommitted_changes":
                git = GitCheckpoint(self.root).status()
                passed = bool(git.get("available")) and bool(git.get("clean"))
                detail = str(git.get("status", ""))
            else:
                detail = f"unsupported check: {kind}"
            results.append({"check": check, "passed": passed, "detail": detail})
        return {
            "passed": bool(results) and all(item["passed"] for item in results),
            "results": results,
        }
