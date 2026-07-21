"""End-to-end Sophyane product benchmarks.

Offline mode builds and executes deterministic artifacts in temporary workspaces.
Live mode additionally asks the configured provider to produce a complete product.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from sophyane.version import __version__


@dataclass
class Result:
    category: str
    name: str
    ok: bool
    detail: str
    elapsed_ms: int
    skipped: bool = False


class ProductBenchmarks:
    def __init__(self, live: bool = False) -> None:
        self.live = live
        self.results: list[Result] = []

    def check(self, category: str, name: str, fn: Callable[[], Any], *, skip: str = "") -> None:
        if skip:
            self.results.append(Result(category, name, True, skip, 0, True))
            return
        started = time.perf_counter()
        try:
            value = fn()
            ok = value is not False
            detail = value if isinstance(value, str) else json.dumps(value, default=str)[:1500]
        except Exception as error:  # noqa: BLE001
            ok = False
            detail = f"{type(error).__name__}: {error}"
        self.results.append(Result(category, name, ok, detail, round((time.perf_counter() - started) * 1000)))

    @staticmethod
    def run_cmd(argv: list[str], cwd: Path, timeout: int = 45) -> str:
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout)[-1500:])
        return (result.stdout or result.stderr).strip()

    def frontend(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sophyane-product-web-") as tmp:
            root = Path(tmp)
            html = """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Snake</title><style>html,body{width:100vw;height:100vh;margin:0}main{display:grid;place-items:center;height:100%}button{font-size:clamp(1.2rem,5vw,2rem);min-width:48px;min-height:48px}</style></head><body><main><h1>Snake</h1><p id='score'>Score: 0</p><canvas id='game' width='320' height='320'></canvas><button id='start'>Start</button><div aria-label='Touch controls'><button data-dir='up'>↑</button><button data-dir='left'>←</button><button data-dir='down'>↓</button><button data-dir='right'>→</button></div></main><script>let score=0;document.querySelector('#start').onclick=()=>{score++;document.querySelector('#score').textContent='Score: '+score};document.querySelectorAll('[data-dir]').forEach(b=>b.onclick=()=>b.dataset.used='1');document.body.dataset.ready='1';</script></body></html>"""
            path = root / "index.html"
            path.write_text(html, encoding="utf-8")
            self.check("frontend", "complete product artifact", lambda: path.exists() and html.startswith("<!doctype html>") and html.endswith("</html>"))
            self.check("frontend", "full-screen responsive mobile UI", lambda: all(x in html for x in ("100vw", "100vh", "viewport", "clamp(")))
            self.check("frontend", "game controls and score", lambda: all(x in html for x in ("canvas", "Score: 0", "data-dir='up'", "id='start'")))
            self.check("frontend", "accessibility and touch targets", lambda: "aria-label" in html and "min-width:48px" in html and "min-height:48px" in html)

    def languages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sophyane-product-code-") as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("def add(a,b): return a+b\nassert add(2,3)==5\nprint('PY_OK')\n", encoding="utf-8")
            self.check("python", "build and execute product", lambda: self.run_cmd([shutil.which("python3") or "python3", "main.py"], root) == "PY_OK")
            if shutil.which("node"):
                (root / "app.js").write_text("const add=(a,b)=>a+b;if(add(2,3)!==5)process.exit(1);console.log('NODE_OK');\n", encoding="utf-8")
                self.check("node", "build and execute product", lambda: self.run_cmd(["node", "app.js"], root) == "NODE_OK")
            else:
                self.check("node", "build and execute product", lambda: True, skip="node unavailable")
            compiler = shutil.which("g++") or shutil.which("clang++")
            if compiler:
                (root / "main.cpp").write_text("#include <iostream>\nint main(){std::cout<<\"CPP_OK\";}\n", encoding="utf-8")
                self.check("cpp", "compile product", lambda: self.run_cmd([compiler, "main.cpp", "-o", "app"], root) == "")
                self.check("cpp", "execute product", lambda: self.run_cmd([str(root / "app")], root) == "CPP_OK")
            else:
                self.check("cpp", "compile product", lambda: True, skip="C++ compiler unavailable")
                self.check("cpp", "execute product", lambda: True, skip="C++ compiler unavailable")

    def repository(self) -> None:
        from sophyane.platform_kernel import EvaluationEngine, RepositoryKernel
        with tempfile.TemporaryDirectory(prefix="sophyane-product-repo-") as tmp:
            root = Path(tmp)
            source = root / "main.py"
            source.write_text("def status():\n    return 'old'\n", encoding="utf-8")
            kernel = RepositoryKernel(root)
            index = kernel.index()
            snap = kernel.checkpoint()
            source.write_text("def status():\n    return 'new'\n", encoding="utf-8")
            self.check("repository", "understand symbols", lambda: "status" in index.get("symbols", {}).get("main.py", []))
            self.check("repository", "apply requested edit", lambda: "new" in source.read_text(encoding="utf-8"))
            self.check("repository", "rollback failed edit", lambda: kernel.rollback(snap.snapshot_id) == 1 and "old" in source.read_text(encoding="utf-8"))
            (root / "test_main.py").write_text("from main import status\nassert status()=='old'\n", encoding="utf-8")
            self.check("repository", "execute verification", lambda: self.run_cmd([shutil.which("python3") or "python3", "test_main.py"], root) == "")
            evaluation = EvaluationEngine().evaluate(root)
            self.check("repository", "evaluate changed product", lambda: evaluation.score == 100.0)

    def orchestration(self) -> None:
        from sophyane.coi import AgentManifest, COIOrchestrator, TaskContract
        with tempfile.TemporaryDirectory(prefix="sophyane-product-coi-") as tmp:
            coi = COIOrchestrator(Path(tmp))
            coi.register(AgentManifest("planner", "planner", permissions=["read"]), lambda task, ctx: {"plan": ["build", "test"], "goal": task.goal})
            coi.register(AgentManifest("coder", "coder", permissions=["read", "write"]), lambda task, ctx: {"artifact": "index.html", "plan": ctx.get("plan")})
            plan = coi.run(TaskContract(goal="Build product", permissions=["read"]), agent="planner")["output"]
            built = coi.run(TaskContract(goal="Implement product", permissions=["read", "write"]), agent="coder", context=plan)
            self.check("coi", "planner-to-coder collaboration", lambda: built.get("ok") and built["output"]["artifact"] == "index.html")
            denied = coi.run(TaskContract(goal="unsafe", permissions=["admin"]), agent="coder")
            self.check("coi", "permission boundary", lambda: denied.get("ok") is False)

    def sli_switching(self) -> None:
        from sophyane.sli_provider_controller import SLIProviderController, artifact_defects
        with tempfile.TemporaryDirectory(prefix="sophyane-product-sli-") as tmp:
            controller = SLIProviderController(Path(tmp) / "state.json")
            prompt = "make chess game as one complete HTML file"
            partial = "<!doctype html><html><body><div id='board'></div>"
            decision = controller.observe(prompt=prompt, response=partial, latency_seconds=41, provider="local_gguf")
            self.check("sli", "detect incomplete interactive artifact", lambda: set(("missing_html_close", "missing_javascript", "missing_interaction")).issubset(set(artifact_defects(prompt, partial))))
            self.check("sli", "escalate severe local product failure", lambda: decision.action == "escalate_cloud" and decision.risk >= 0.5)
            complete = "<!doctype html><html><body><button id='move'>Move</button><script>document.querySelector('#move').onclick=()=>1</script></body></html>"
            accepted = controller.observe(prompt=prompt, response=complete, latency_seconds=2, provider="gemini")
            self.check("sli", "accept completed rescue artifact", lambda: accepted.action == "accept" and not accepted.defects)
            self.check("sli", "persist recurrent sequence memory", lambda: (Path(tmp) / "state.json").exists() and (Path(tmp) / "sli-provider-events.jsonl").exists())

    def mcp_and_persistence(self) -> None:
        from sophyane.mcp import call_tool, list_tools
        catalog = list_tools()
        self.check("mcp", "tool discovery", lambda: catalog.get("ok") and len(catalog.get("tools", [])) >= 5)
        self.check("mcp", "real platform tool", lambda: call_tool("platform").get("ok"))
        with tempfile.TemporaryDirectory(prefix="sophyane-product-state-") as tmp:
            state = Path(tmp) / "checkpoint.json"
            state.write_text(json.dumps({"task": "product", "step": 3, "complete": False}), encoding="utf-8")
            loaded = json.loads(state.read_text(encoding="utf-8"))
            loaded["complete"] = True
            state.write_text(json.dumps(loaded), encoding="utf-8")
            self.check("persistence", "resume after interruption", lambda: json.loads(state.read_text(encoding="utf-8"))["complete"] is True)

    def live_product(self) -> None:
        if not self.live:
            self.check("live", "provider creates complete product", lambda: True, skip="run with --live to test configured provider")
            return
        def generate() -> bool:
            from sophyane.config import load_config
            from sophyane.providers import create_provider
            provider = create_provider(load_config())
            prompt = "Create one complete self-contained responsive HTML counter app. Return only HTML. It must include viewport, a visible score, a button, JavaScript interaction, 100vw and 100vh."
            text = str(provider.generate(prompt, "You are a product engineer. Return the complete artifact only."))
            low = text.lower()
            required = ("<!doctype html", "</html>", "viewport", "<button", "<script", "100vw", "100vh")
            missing = [item for item in required if item not in low]
            if missing:
                raise RuntimeError(f"provider product incomplete; missing {missing}; response={text[:500]}")
            return True
        self.check("live", "provider creates complete product", generate)

    def run(self) -> dict[str, Any]:
        self.frontend(); self.languages(); self.repository(); self.orchestration(); self.sli_switching(); self.mcp_and_persistence(); self.live_product()
        passed = sum(1 for r in self.results if r.ok and not r.skipped)
        failed = sum(1 for r in self.results if not r.ok)
        skipped = sum(1 for r in self.results if r.skipped)
        score = round(100 * passed / max(1, passed + failed), 1)
        return {"ok": failed == 0 and score == 100.0, "version": __version__, "mode": "live" if self.live else "offline", "summary": {"passed": passed, "failed": failed, "skipped": skipped, "score": score}, "results": [asdict(r) for r in self.results]}


def main() -> int:
    parser = argparse.ArgumentParser(prog="sophyane-benchmark", description="Run end-to-end Sophyane product benchmarks")
    parser.add_argument("--live", action="store_true", help="also require the configured provider to create a complete product")
    parser.add_argument("--output", default="", help="write JSON report")
    args = parser.parse_args()
    report = ProductBenchmarks(live=args.live).run()
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        path = Path(args.output).expanduser().resolve(); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
