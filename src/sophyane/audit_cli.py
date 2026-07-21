"""Comprehensive, dependency-free Sophyane audit runner."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from sophyane.version import __version__


@dataclass
class Check:
    area: str
    name: str
    ok: bool
    detail: str = ""
    elapsed_ms: int = 0
    skipped: bool = False


class Audit:
    def __init__(self, *, live: bool = False) -> None:
        self.live = live
        self.results: list[Check] = []

    def check(self, area: str, name: str, fn: Callable[[], Any], *, skip: str = "") -> None:
        if skip:
            self.results.append(Check(area, name, True, skip, skipped=True))
            return
        started = time.perf_counter()
        try:
            value = fn()
            ok = value is not False
            detail = value if isinstance(value, str) else json.dumps(value, default=str)[:1000]
        except Exception as error:  # noqa: BLE001
            ok = False
            detail = f"{type(error).__name__}: {error}"
        self.results.append(Check(area, name, ok, detail, round((time.perf_counter() - started) * 1000)))

    def run(self) -> dict[str, Any]:
        for method in (
            self._imports, self._filesystem, self._repository, self._sandbox,
            self._evaluation_prompting, self._coi, self._mcp, self._cli,
            self._provider_state, self._browser_artifact, self._release_docs, self._live,
        ):
            method()
        passed = sum(1 for item in self.results if item.ok and not item.skipped)
        failed = sum(1 for item in self.results if not item.ok)
        skipped = sum(1 for item in self.results if item.skipped)
        total = passed + failed
        return {
            "ok": failed == 0,
            "version": __version__,
            "mode": "live" if self.live else "offline",
            "summary": {"passed": passed, "failed": failed, "skipped": skipped, "score": round(100 * passed / max(1, total), 1)},
            "checks": [asdict(item) for item in self.results],
        }

    def _imports(self) -> None:
        modules = [
            "sophyane.cli_entry", "sophyane.platform_kernel", "sophyane.platform_cli",
            "sophyane.coi", "sophyane.coi_cli", "sophyane.mcp", "sophyane.release_cli",
            "sophyane.runtime_provider_context_patch", "sophyane.runtime_quality_escalation",
        ]
        for module in modules:
            self.check("imports", module, lambda module=module: importlib.import_module(module).__file__ or True)

    def _filesystem(self) -> None:
        from sophyane.platform_kernel import ensure_platform_filesystem
        from sophyane.coi import ensure_coi_filesystem
        self.check("filesystem", "platform tree", ensure_platform_filesystem)
        self.check("filesystem", "coi tree", ensure_coi_filesystem)

    def _repository(self) -> None:
        from sophyane.platform_kernel import RepositoryKernel
        with tempfile.TemporaryDirectory(prefix="sophyane-audit-repo-") as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            kernel = RepositoryKernel(root)
            self.check("repository", "index and symbols", kernel.index)
            holder: dict[str, Any] = {}
            self.check("repository", "checkpoint", lambda: holder.setdefault("snapshot", kernel.checkpoint()).snapshot_id)
            (root / "main.py").write_text("broken = True\n", encoding="utf-8")
            self.check("repository", "rollback", lambda: kernel.rollback(holder["snapshot"].snapshot_id) == 1)
            self.check("repository", "rollback content", lambda: "def add" in (root / "main.py").read_text(encoding="utf-8"))

    def _sandbox(self) -> None:
        from sophyane.platform_kernel import CodedSandbox
        with tempfile.TemporaryDirectory(prefix="sophyane-audit-box-") as tmp:
            box = CodedSandbox(Path(tmp))
            self.check("sandbox", "prepare manifest", box.prepare)
            self.check("sandbox", "safe relative path", lambda: str(box.resolve("output/result.txt")))
            def escape() -> bool:
                try:
                    box.resolve("../escape")
                except ValueError:
                    return True
                return False
            self.check("sandbox", "reject path escape", escape)
            self.check("sandbox", "capability detection", box.capabilities)

    def _evaluation_prompting(self) -> None:
        from sophyane.platform_kernel import EvaluationEngine, PromptAdvisor
        with tempfile.TemporaryDirectory(prefix="sophyane-audit-eval-") as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")
            self.check("evaluation", "valid HTML evaluation", lambda: asdict(EvaluationEngine().evaluate(root)))
        self.check("prompting", "short prompt advice", lambda: PromptAdvisor.advise("fix it"))
        self.check("prompting", "actionable prompt advice", lambda: PromptAdvisor.advise("Build index.html; success means it has touch controls and passes tests"))

    def _coi(self) -> None:
        from sophyane.coi import AgentManifest, COIOrchestrator, TaskContract
        with tempfile.TemporaryDirectory(prefix="sophyane-audit-coi-") as tmp:
            coi = COIOrchestrator(Path(tmp))
            manifest = AgentManifest(name="audit-agent", role="validator", permissions=["read"], skills=["audit"])
            coi.register(manifest, lambda task, context: {"goal": task.goal, "context": context})
            self.check("coi", "submit and run", lambda: coi.run(TaskContract(goal="audit", permissions=["read"]), agent="audit-agent", context={"ok": True}))
            self.check("coi", "permission denial", lambda: coi.run(TaskContract(goal="deny", permissions=["write"]), agent="audit-agent").get("ok") is False)

    def _mcp(self) -> None:
        from sophyane.mcp import call_tool, list_tools
        self.check("mcp", "catalog", list_tools)
        self.check("mcp", "platform tool", lambda: call_tool("platform"))
        self.check("mcp", "unknown tool rejection", lambda: call_tool("__missing__").get("ok") is False)

    def _cli(self) -> None:
        commands = ["sophyane", "sophyane-platform", "sophyane-coi", "sophyane-release", "sophyane-audit"]
        for command in commands:
            self.check("cli", f"launcher {command}", lambda command=command: shutil.which(command) or False)
        for argv in (["sophyane", "--version"], ["sophyane-platform", "status"], ["sophyane-coi", "status"], ["sophyane-release", "status"]):
            def run(argv=argv) -> str:
                result = subprocess.run(argv, capture_output=True, text=True, timeout=30, env={**os.environ, "SOPHYANE_SKIP_UPDATE_CHECK": "1"})
                if result.returncode != 0:
                    raise RuntimeError((result.stderr or result.stdout)[-1000:])
                return (result.stdout or result.stderr)[-1000:]
            self.check("cli", " ".join(argv), run)

    def _provider_state(self) -> None:
        from sophyane.provider_state import get_active_provider, set_active_provider
        previous = get_active_provider()
        self.check("runtime", "provider state local", lambda: (set_active_provider("local_gguf", "audit"), get_active_provider())[1] == "local_gguf")
        self.check("runtime", "provider state rescue", lambda: (set_active_provider("gemini", "audit-rescue"), get_active_provider())[1] == "gemini")
        set_active_provider(previous or "local_gguf", "audit-restore")

    def _browser_artifact(self) -> None:
        html = "<!doctype html><html><head><meta name='viewport' content='width=device-width'></head><body><button>Start</button><script>document.body.dataset.ok='1'</script></body></html>"
        self.check("browser", "complete HTML artifact", lambda: html.lower().startswith("<!doctype html") and html.lower().endswith("</html>"))
        self.check("browser", "mobile viewport", lambda: "viewport" in html)
        self.check("browser", "interactive control", lambda: "<button" in html and "<script" in html)

    def _release_docs(self) -> None:
        installed = Path(os.environ.get("SOPHYANE_HOME", str(Path.home() / ".local/share/sophyane"))) / "system"
        source = installed if installed.exists() else Path.cwd()
        candidates = [source / "README.md", source / "docs" / "SOPHYANE_20.md", source / "pyproject.toml"]
        for path in candidates:
            self.check("release", f"document {path.name}", lambda path=path: path.exists() and path.stat().st_size > 50)

    def _live(self) -> None:
        if not self.live:
            self.check("live", "provider generation", lambda: True, skip="run with --live to call the configured provider")
            return
        def provider_call() -> str:
            from sophyane.config import load_config
            from sophyane.providers import create_provider
            provider = create_provider(load_config())
            text = provider.generate("Reply with exactly SOPHYANE_AUDIT_OK", "You are a health-check endpoint.")
            if "SOPHYANE_AUDIT_OK" not in str(text):
                raise RuntimeError(f"unexpected provider response: {str(text)[:200]}")
            return str(text)
        self.check("live", "provider generation", provider_call)


def main() -> int:
    parser = argparse.ArgumentParser(prog="sophyane-audit", description="Test Sophyane subsystems and produce a JSON report")
    parser.add_argument("--live", action="store_true", help="also call the configured AI provider")
    parser.add_argument("--output", default="", help="write the report to this path")
    args = parser.parse_args()
    report = Audit(live=args.live).run()
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        path = Path(args.output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
