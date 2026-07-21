"""Native repository, sandbox, evaluation, tracing, compaction, and sub-agent primitives.

The platform kernel is intentionally dependency-free so it works in Termux and
small local installations.  Higher-level runtimes can use these primitives
without requiring LangGraph, LangSmith, Docker, or a database server.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


ROOT = Path.home() / ".sophyane"
PLATFORM_ROOT = ROOT / "platform"
REPOSITORIES_ROOT = PLATFORM_ROOT / "repositories"
AGENTS_ROOT = PLATFORM_ROOT / "agents"
RUNS_ROOT = PLATFORM_ROOT / "runs"
COMPACTION_ROOT = PLATFORM_ROOT / "compaction"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_platform_filesystem() -> dict[str, str]:
    paths = {
        "root": PLATFORM_ROOT,
        "repositories": REPOSITORIES_ROOT,
        "agents": AGENTS_ROOT,
        "runs": RUNS_ROOT,
        "compaction": COMPACTION_ROOT,
        "shared_cache": PLATFORM_ROOT / "cache",
        "knowledge": PLATFORM_ROOT / "knowledge",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    marker = PLATFORM_ROOT / "platform.json"
    _write_json(
        marker,
        {
            "schema": 1,
            "created_or_verified_at": time.time(),
            "filesystem": {name: str(path) for name, path in paths.items()},
            "principles": [
                "workspace-relative writes",
                "checkpoint before mutation",
                "deterministic evaluation",
                "provider-neutral sub-agents",
                "local-first tracing",
            ],
        },
    )
    return {name: str(path) for name, path in paths.items()}


@dataclass
class RepositorySnapshot:
    snapshot_id: str
    created_at: float
    files: dict[str, str]
    root: str


class RepositoryKernel:
    """Small, effective repository index with snapshots, symbols, and rollback."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        digest = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        self.state = REPOSITORIES_ROOT / digest
        self.state.mkdir(parents=True, exist_ok=True)

    def index(self) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        symbols: dict[str, list[str]] = {}
        ignored = {".git", "node_modules", ".venv", "venv", "__pycache__"}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or any(part in ignored for part in path.parts):
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            rel = path.relative_to(self.root).as_posix()
            item = {"path": rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            files.append(item)
            if path.suffix.lower() in {".py", ".js", ".ts", ".tsx", ".jsx", ".cpp", ".h", ".hpp"}:
                text = raw.decode("utf-8", errors="ignore")
                found: list[str] = []
                for line in text.splitlines():
                    stripped = line.strip()
                    for prefix in ("def ", "class ", "function ", "const ", "let ", "var ", "struct "):
                        if stripped.startswith(prefix):
                            token = stripped[len(prefix):].split("(", 1)[0].split("{", 1)[0].split("=", 1)[0].strip()
                            if token:
                                found.append(token[:120])
                if found:
                    symbols[rel] = found[:200]
        payload = {"root": str(self.root), "indexed_at": time.time(), "files": files, "symbols": symbols}
        _write_json(self.state / "index.json", payload)
        return payload

    def checkpoint(self) -> RepositorySnapshot:
        files: dict[str, str] = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                try:
                    files[path.relative_to(self.root).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
        snapshot = RepositorySnapshot(uuid.uuid4().hex[:12], time.time(), files, str(self.root))
        _write_json(self.state / "snapshots" / f"{snapshot.snapshot_id}.json", asdict(snapshot))
        return snapshot

    def rollback(self, snapshot_id: str) -> int:
        path = self.state / "snapshots" / f"{snapshot_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        restored = 0
        for rel, content in data.get("files", {}).items():
            target = (self.root / rel).resolve()
            if target != self.root and self.root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            restored += 1
        return restored


class CodedSandbox:
    """Filesystem-enforced sandbox contract for one task workspace."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def prepare(self) -> dict[str, Any]:
        folders = ["input", "output", "tmp", "logs", "artifacts", ".sophyane/checkpoints", ".sophyane/evals"]
        for rel in folders:
            (self.workspace / rel).mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema": 2,
            "workspace": str(self.workspace),
            "created_at": time.time(),
            "policy": {
                "writes": "workspace-only",
                "relative_paths": True,
                "checkpoint_before_mutation": True,
                "network": "runtime-controlled",
                "commands": "bounded-and-logged",
            },
            "capabilities": self.capabilities(),
        }
        _write_json(self.workspace / ".sophyane" / "sandbox.json", manifest)
        return manifest

    def resolve(self, relative: str) -> Path:
        target = (self.workspace / relative).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ValueError(f"Path escapes sandbox: {relative}")
        return target

    @staticmethod
    def capabilities() -> dict[str, bool]:
        commands = ["python", "python3", "bash", "sh", "git", "node", "npm", "g++", "clang++", "curl", "termux-open-url"]
        return {command: bool(shutil.which(command)) for command in commands}


class AutoCompactor:
    """Deduplicate snapshots and compact old logs without deleting user sources."""

    def compact(self, root: Path, *, keep_recent: int = 20) -> dict[str, int]:
        root = root.resolve()
        removed_duplicates = 0
        compressed_logs = 0
        seen: dict[str, Path] = {}
        candidates = sorted(root.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for index, path in enumerate(candidates):
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            if digest in seen and index >= keep_recent and ("snapshot" in path.name or "checkpoint" in path.name):
                path.unlink(missing_ok=True)
                removed_duplicates += 1
            else:
                seen[digest] = path
        for path in root.rglob("*.log"):
            try:
                if path.stat().st_size > 2_000_000:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]
                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    compressed_logs += 1
            except OSError:
                continue
        report = {"removed_duplicate_snapshots": removed_duplicates, "compacted_logs": compressed_logs}
        _write_json(COMPACTION_ROOT / f"report-{int(time.time())}.json", report)
        return report


class PromptAdvisor:
    TEMPLATE = "Goal: ...\nConstraints: ...\nExisting files/context: ...\nAcceptance criteria: ...\nTests: ..."

    @classmethod
    def advise(cls, prompt: str) -> list[str]:
        text = " ".join(prompt.split()).lower()
        notes: list[str] = []
        if len(text) < 24:
            notes.append("Add the desired result and one acceptance criterion.")
        if not any(word in text for word in ("must", "should", "accept", "success", "working")):
            notes.append("State how Sophyane should decide the task is complete.")
        if any(word in text for word in ("fix it", "improve it", "make better")):
            notes.append("Name the failing behavior or file instead of using only 'it'.")
        if not notes:
            notes.append("Prompt is actionable; keep constraints and tests explicit.")
        return notes[:2]


@dataclass
class EvaluationResult:
    score: float
    checks: dict[str, bool]
    notes: list[str] = field(default_factory=list)


class EvaluationEngine:
    """Deterministic baseline evals for generated software artifacts."""

    def evaluate(self, workspace: Path) -> EvaluationResult:
        workspace = workspace.resolve()
        files = [p for p in workspace.rglob("*") if p.is_file() and ".sophyane" not in p.parts]
        checks: dict[str, bool] = {
            "artifact_exists": bool(files),
            "nonempty_sources": any(p.stat().st_size > 20 for p in files),
            "has_readable_entrypoint": any(p.name in {"index.html", "main.py", "app.py", "main.cpp", "package.json"} for p in files),
            "no_empty_html": True,
            "tests_or_verification": any("test" in p.name.lower() for p in files),
        }
        html_files = [p for p in files if p.suffix.lower() in {".html", ".htm"}]
        for path in html_files:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            if "<html" not in text or "</html>" not in text:
                checks["no_empty_html"] = False
        score = round(100.0 * sum(checks.values()) / max(1, len(checks)), 1)
        notes = [] if score == 100 else [name.replace("_", " ") for name, passed in checks.items() if not passed]
        result = EvaluationResult(score, checks, notes)
        _write_json(workspace / ".sophyane" / "evals" / f"eval-{int(time.time())}.json", asdict(result))
        return result


@dataclass
class AgentSpec:
    name: str
    role: str
    permissions: tuple[str, ...] = ("read",)
    provider: str = "dispatcher"
    max_steps: int = 8


@dataclass
class AgentResult:
    name: str
    ok: bool
    output: str
    elapsed_seconds: float


class SubAgentRuntime:
    """Provider-neutral sub-agent deployment with bounded execution and tracing."""

    def __init__(self, generate: Callable[[str, str], str], workspace: Path) -> None:
        self.generate = generate
        self.workspace = workspace.resolve()
        self.sandbox = CodedSandbox(self.workspace)
        self.sandbox.prepare()

    def run(self, spec: AgentSpec, task: str, context: str = "") -> AgentResult:
        started = time.monotonic()
        system = (
            f"You are Sophyane sub-agent '{spec.name}', role={spec.role}. "
            f"Permissions: {', '.join(spec.permissions)}. Work only inside {self.workspace}. "
            "Return a concise result with evidence; do not claim unverified success."
        )
        prompt = f"Task: {task}\nContext: {context[:6000]}"
        try:
            output = self.generate(prompt, system)
            result = AgentResult(spec.name, bool(str(output).strip()), str(output), time.monotonic() - started)
        except Exception as error:  # noqa: BLE001
            result = AgentResult(spec.name, False, f"{type(error).__name__}: {error}", time.monotonic() - started)
        TraceStore(self.workspace).record("subagent", asdict(result) | {"role": spec.role})
        return result

    def deploy(self, specs: list[AgentSpec], task: str) -> list[AgentResult]:
        # Deliberately deterministic and bounded on mobile; concurrency can be added
        # by a device policy without changing the agent contract.
        return [self.run(spec, task) for spec in specs]


class TraceStore:
    """Local LangSmith-style event trace, stored as append-only JSONL."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.run_id = uuid.uuid4().hex[:12]
        self.workspace = workspace.resolve() if workspace else None
        self.path = RUNS_ROOT / f"{self.run_id}.jsonl"

    def record(self, event: str, payload: dict[str, Any]) -> None:
        row = {"timestamp": time.time(), "event": event, "workspace": str(self.workspace or ""), "payload": payload}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def platform_status() -> dict[str, Any]:
    filesystem = ensure_platform_filesystem()
    return {
        "ok": True,
        "filesystem": filesystem,
        "agents": ["supervisor", "planner", "repository", "coder", "browser", "validator", "repair", "test", "docs", "learning"],
        "capabilities": CodedSandbox.capabilities(),
        "prompt_template": PromptAdvisor.TEMPLATE,
    }
