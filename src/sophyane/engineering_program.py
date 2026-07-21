"""Sophyane 20 stabilization program and executable release quality gate."""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sophyane.platform_kernel import CodedSandbox, EvaluationEngine, PromptAdvisor, RepositoryKernel, ensure_platform_filesystem
from sophyane.version import __version__

WORKSTREAMS = {
    "runtime": "dispatcher, provider truth, launchers, diagnostics",
    "repository": "index, symbols, checkpoints, rollback, compaction",
    "coi": "task contracts, agents, events, scheduling, recovery",
    "sandbox": "workspace isolation, capabilities, bounded execution",
    "evaluation": "deterministic checks, reports, regression gates",
    "prompting": "templates, prompt advice, acceptance criteria",
}

REQUIRED_MODULES = (
    "sophyane.cli_entry",
    "sophyane.platform_cli",
    "sophyane.coi_cli",
    "sophyane.platform_kernel",
    "sophyane.coi",
    "sophyane.mcp_bridge",
    "sophyane.runtime_provider_context_patch",
)

REQUIRED_COMMANDS = {
    "sophyane": ("--version",),
    "sophyane-platform": ("status",),
    "sophyane-coi": ("status",),
    "sophyane-release": ("status",),
}

@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str

@dataclass
class GateReport:
    ok: bool
    version: str
    generated_at: float
    checks: list[GateCheck]
    workstreams: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["score"] = round(100 * sum(c.passed for c in self.checks) / max(1, len(self.checks)), 1)
        return value

class ReleaseGate:
    """Verify packaging, launchers, modules, filesystem, docs, and baseline engines."""

    def __init__(self, repository: Path | None = None) -> None:
        self.repository = (repository or Path.cwd()).resolve()

    def run(self, *, execute_commands: bool = True) -> GateReport:
        checks: list[GateCheck] = []
        for module in REQUIRED_MODULES:
            try:
                importlib.import_module(module)
                checks.append(GateCheck(f"module:{module}", True, "imported"))
            except Exception as error:  # noqa: BLE001
                checks.append(GateCheck(f"module:{module}", False, f"{type(error).__name__}: {error}"))

        paths = ensure_platform_filesystem()
        checks.append(GateCheck("platform-filesystem", all(Path(p).is_dir() for p in paths.values()), json.dumps(paths, sort_keys=True)))

        for command, args in REQUIRED_COMMANDS.items():
            executable = shutil.which(command)
            if not executable:
                checks.append(GateCheck(f"command:{command}", False, "not found on PATH"))
                continue
            if not execute_commands:
                checks.append(GateCheck(f"command:{command}", True, executable))
                continue
            try:
                result = subprocess.run([executable, *args], capture_output=True, text=True, timeout=30, check=False)
                detail = (result.stdout or result.stderr).strip()[-500:]
                checks.append(GateCheck(f"command:{command}", result.returncode == 0, detail or f"exit={result.returncode}"))
            except Exception as error:  # noqa: BLE001
                checks.append(GateCheck(f"command:{command}", False, f"{type(error).__name__}: {error}"))

        docs = ["README.md", "docs/COI.md", "docs/MCP.md", "docs/PROMPT_GUIDE.md", "docs/EVALUATION.md"]
        for rel in docs:
            path = self.repository / rel
            checks.append(GateCheck(f"docs:{rel}", path.is_file() and path.stat().st_size > 100, str(path)))

        try:
            index = RepositoryKernel(self.repository).index()
            checks.append(GateCheck("repository-index", bool(index.get("files")), f"{len(index.get('files', []))} files"))
        except Exception as error:  # noqa: BLE001
            checks.append(GateCheck("repository-index", False, str(error)))

        try:
            sandbox = CodedSandbox(self.repository / ".sophyane" / "gate-sandbox").prepare()
            checks.append(GateCheck("coded-sandbox", sandbox.get("policy", {}).get("writes") == "workspace-only", sandbox["workspace"]))
        except Exception as error:  # noqa: BLE001
            checks.append(GateCheck("coded-sandbox", False, str(error)))

        advice = PromptAdvisor.advise("Build a tested responsive app; success means keyboard and touch controls work.")
        checks.append(GateCheck("prompt-advisor", bool(advice), "; ".join(advice)))

        evaluation = EvaluationEngine().evaluate(self.repository)
        checks.append(GateCheck("evaluation-engine", evaluation.score > 0, f"score={evaluation.score}"))

        return GateReport(all(c.passed for c in checks), __version__, time.time(), checks, WORKSTREAMS)


def program_status() -> dict[str, Any]:
    return {
        "ok": True,
        "version": __version__,
        "program": "Sophyane 20 Platform Stabilization & Engineering Foundation",
        "workstreams": WORKSTREAMS,
        "python": sys.version.split()[0],
        "filesystem": ensure_platform_filesystem(),
    }
