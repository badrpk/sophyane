"""Combined workers: Sophyane (policy) + optional NIFDU + Neuron.

Goals
- Prefer local native work over LLM tokens when a fast path exists.
- Auto-fetch missing NIFDU/Neuron artifacts from GitHub into the user machine.
- Never invent a second SNN/product design; Neuron/NIFDU remain sources of truth.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sophyane.native_backends import probe_nifdu, probe_neuron, status as backend_status

STATE = Path(
    os.environ.get(
        "SOPHYANE_STATE_DIR",
        Path.home() / ".local" / "state" / "sophyane",
    )
).expanduser()
BIN_DIR = Path(
    os.environ.get("SOPHYANE_NATIVE_BIN", Path.home() / ".local" / "bin")
).expanduser()
CACHE = STATE / "native_cache"
GITHUB_NIFDU = os.environ.get("SOPHYANE_NIFDU_REPO", "badrpk/nifdu")
GITHUB_NEURON = os.environ.get("SOPHYANE_NEURON_REPO", "badrpk/neuron")
TAG = os.environ.get("SOPHYANE_NATIVE_TAG", "v2.1.0")

# Task classes that should skip or shrink LLM usage
NATIVE_HINTS = (
    "benchmark",
    "harness",
    "throughput",
    "latency",
    "spiking",
    "snn",
    "neuron",
    "nifdu",
    "graph workflow",
    "agent3",
    "simd",
    "stdp",
    "native status",
)


@dataclass
class WorkerPlan:
    use_llm: bool
    use_nifdu: bool
    use_neuron: bool
    reason: str
    estimated_token_saving: str


@dataclass
class WorkerResult:
    ok: bool
    plan: WorkerPlan
    steps: list[dict[str, Any]] = field(default_factory=list)
    combined_summary: str = ""


def _run(cmd: list[str], timeout: float = 120.0) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": cmd,
            "returncode": p.returncode,
            "stdout": (p.stdout or "")[-4000:],
            "stderr": (p.stderr or "")[-1500:],
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "ok": p.returncode == 0,
        }
    except Exception as exc:
        return {"cmd": cmd, "ok": False, "error": str(exc)}


def plan_workers(request: str) -> WorkerPlan:
    t = " ".join(str(request or "").lower().split())
    want_native = any(h in t for h in NATIVE_HINTS)
    want_neuron = any(
        h in t
        for h in ("spiking", "snn", "neuron", "stdp", "lif", "attractor")
    )
    want_nifdu = want_native or any(
        h in t for h in ("nifdu", "agent3", "graph", "harness", "benchmark", "simd")
    )
    if want_neuron or want_nifdu:
        return WorkerPlan(
            use_llm=False,
            use_nifdu=want_nifdu or not want_neuron,
            use_neuron=want_neuron,
            reason="native-capable task: prefer binaries over tokens",
            estimated_token_saving="high",
        )
    # General engineering still may use LLM, but can attach nifdu for speed later
    return WorkerPlan(
        use_llm=True,
        use_nifdu=False,
        use_neuron=False,
        reason="general task: LLM policy path",
        estimated_token_saving="none",
    )


def _github_tarball_url(repo: str, tag: str) -> str:
    return f"https://github.com/{repo}/archive/refs/tags/{tag}.tar.gz"


def ensure_source_checkout(repo: str, dest: Path, tag: str = TAG) -> dict[str, Any]:
    """Clone or update a shallow checkout under CACHE (user machine)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (dest / ".git").is_dir():
        r = _run(["git", "-C", str(dest), "fetch", "--tags", "--depth", "1", "origin", tag])
        _run(["git", "-C", str(dest), "checkout", tag])
        return {"action": "update", "path": str(dest), "result": r}
    # Prefer git (user already has SSH/HTTPS to GitHub)
    url = f"https://github.com/{repo}.git"
    if dest.exists():
        shutil.rmtree(dest)
    r = _run(
        ["git", "clone", "--depth", "1", "--branch", tag, url, str(dest)],
        timeout=300,
    )
    if not r.get("ok"):
        # fallback: default branch
        r = _run(["git", "clone", "--depth", "1", url, str(dest)], timeout=300)
    return {"action": "clone", "path": str(dest), "result": r}


def ensure_nifdu() -> dict[str, Any]:
    p = probe_nifdu()
    if p.available:
        return {"available": True, "path": p.path, "fetched": False}
    # Try local tree build output
    candidates = [
        Path.home() / "nifdu" / "build" / "nifdu",
        Path("/tmp/nifdu-clean-build/nifdu"),
        BIN_DIR / "nifdu",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            target = BIN_DIR / "nifdu"
            if not target.exists():
                try:
                    target.symlink_to(c)
                except OSError:
                    shutil.copy2(c, target)
                    target.chmod(0o755)
            return {"available": True, "path": str(target), "fetched": False, "linked": str(c)}
    # Auto download sources (not always a prebuilt binary on Linux)
    src = CACHE / "nifdu-src"
    step = ensure_source_checkout(GITHUB_NIFDU, src)
    build = CACHE / "nifdu-build"
    build.mkdir(parents=True, exist_ok=True)
    cfg = _run(["cmake", "-S", str(src), "-B", str(build)], timeout=120)
    bld = _run(["cmake", "--build", str(build), "-j", str(os.cpu_count() or 2), "--target", "nifdu"], timeout=600)
    binary = build / "nifdu"
    if binary.is_file():
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        dest = BIN_DIR / "nifdu"
        shutil.copy2(binary, dest)
        dest.chmod(0o755)
        return {
            "available": True,
            "path": str(dest),
            "fetched": True,
            "steps": [step, cfg, bld],
        }
    return {"available": False, "fetched": True, "steps": [step, cfg, bld]}


def ensure_neuron() -> dict[str, Any]:
    p = probe_neuron()
    if p.available:
        return {"available": True, "path": p.path, "fetched": False}
    candidates = [
        Path.home() / "nifdu" / "build" / "test_neuron_capabilities",
        Path("/tmp/nifdu-clean-build/test_neuron_capabilities"),
        Path.home() / "neuron_repo" / "build" / "test_neuron_capabilities",
        BIN_DIR / "test_neuron_capabilities",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            target = BIN_DIR / "test_neuron_capabilities"
            if not target.exists():
                try:
                    target.symlink_to(c)
                except OSError:
                    shutil.copy2(c, target)
                    target.chmod(0o755)
            return {"available": True, "path": str(target), "fetched": False, "linked": str(c)}
    src = CACHE / "neuron-src"
    step = ensure_source_checkout(GITHUB_NEURON, src)
    # Neuron may not ship a standalone binary target; fall back to nifdu test binary after nifdu ensure
    nifdu_try = ensure_nifdu()
    p2 = probe_neuron()
    if p2.available:
        return {"available": True, "path": p2.path, "fetched": True, "via": "nifdu", "steps": [step, nifdu_try]}
    return {"available": False, "fetched": True, "steps": [step, nifdu_try]}


def run_combined(request: str, auto_install: bool = True) -> WorkerResult:
    plan = plan_workers(request)
    steps: list[dict[str, Any]] = [{"plan": plan.__dict__}]

    nifdu_path = None
    neuron_path = None

    if plan.use_nifdu:
        info = ensure_nifdu() if auto_install else {
            "available": probe_nifdu().available,
            "path": probe_nifdu().path,
        }
        steps.append({"ensure_nifdu": info})
        if info.get("available"):
            nifdu_path = info.get("path")

    if plan.use_neuron:
        info = ensure_neuron() if auto_install else {
            "available": probe_neuron().available,
            "path": probe_neuron().path,
        }
        steps.append({"ensure_neuron": info})
        if info.get("available"):
            neuron_path = info.get("path")

    # Execute cheap native probes (no LLM tokens)
    if neuron_path and plan.use_neuron:
        steps.append({"neuron_run": _run([str(neuron_path)], timeout=60)})
    if nifdu_path and plan.use_nifdu and not plan.use_neuron:
        # nifdu CLI varies; status-style invocation
        steps.append({"nifdu_run": _run([str(nifdu_path)], timeout=30)})

    ok_native = any(
        s.get("neuron_run", {}).get("ok") or s.get("nifdu_run", {}).get("ok")
        for s in steps
    )
    backends = backend_status()
    summary_lines = [
        "Combined worker result",
        f"  plan: llm={plan.use_llm} nifdu={plan.use_nifdu} neuron={plan.use_neuron}",
        f"  reason: {plan.reason}",
        f"  token_saving: {plan.estimated_token_saving}",
        f"  nifdu: {backends['nifdu']}",
        f"  neuron: {backends['neuron']}",
    ]
    for s in steps:
        if "neuron_run" in s and s["neuron_run"].get("stdout"):
            summary_lines.append("  neuron_stdout_tail:")
            summary_lines.append(s["neuron_run"]["stdout"][-1200:])
        if "nifdu_run" in s and s["nifdu_run"].get("stdout"):
            summary_lines.append("  nifdu_stdout_tail:")
            summary_lines.append(s["nifdu_run"]["stdout"][-800:])
    return WorkerResult(
        ok=ok_native or not (plan.use_nifdu or plan.use_neuron),
        plan=plan,
        steps=steps,
        combined_summary="\n".join(summary_lines),
    )


def try_combined_reply(message: str) -> str | None:
    """Chat fast-path: explicit combine / native accelerate requests."""
    t = " ".join(str(message or "").lower().split())
    triggers = (
        "use nifdu",
        "use neuron",
        "combined workers",
        "native accelerate",
        "run neuron test",
        "run nifdu harness",
        "install nifdu",
        "install neuron",
        "fetch native",
        "auto install native",
    )
    if not any(x in t for x in triggers) and not any(h in t for h in NATIVE_HINTS):
        # only auto-combine when clearly native
        return None
    if any(x in t for x in triggers) or any(
        h in t for h in ("spiking", "snn", "benchmark harness", "neuron capabilities")
    ):
        result = run_combined(message, auto_install=True)
        return result.combined_summary
    return None


if __name__ == "__main__":
    import sys
    req = " ".join(sys.argv[1:]) or "run neuron capabilities benchmark"
    print(run_combined(req).combined_summary)
