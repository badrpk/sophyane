"""Ultra-fast local handlers. Target: <=10ms. Never call an LLM."""
from __future__ import annotations

import platform
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class FastResult:
    text: str
    latency_ms: float
    source: str = "fast_path"


def _run(cmd: list[str], timeout: float = 1.5) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr or "").strip()
    except Exception:
        return ""


def handle_system_config(_: str) -> str:
    uname = _run(["uname", "-a"])
    return (
        f"System: {platform.system()}\n"
        f"Kernel: {platform.release()}\n"
        f"Architecture: {platform.machine()}\n"
        f"Python: {platform.python_version()}\n"
        f"uname: {uname or 'n/a'}"
    )


def handle_version(_: str) -> str:
    try:
        from sophyane.version import __version__
        return f"Sophyane {__version__}"
    except Exception:
        return "Sophyane (version unknown)"


def handle_list_models(_: str) -> str:
    out = _run(["ollama", "list"])
    if not out:
        return "No local Ollama models found (or ollama not running)."
    lines = [ln for ln in out.splitlines() if ln.strip()]
    models = lines[1:] if len(lines) > 1 else []
    if not models:
        return "No local models installed."
    names = [ln.split()[0] for ln in models if ln.split()]
    return f"{len(names)} local model(s):\n" + "\n".join(f"  - {n}" for n in names)


def handle_current_model(_: str) -> str:
    try:
        from sophyane.config import load_config
        cfg = load_config()
        return f"Active: provider={cfg.get('provider')} model={cfg.get('model')}"
    except Exception:
        return "Active model: unknown"


def handle_sli_status(_: str) -> str:
    try:
        from pathlib import Path
        import json
        p = Path.home() / ".local/share/sophyane/sli-provider-state.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return "SLI provider state:\n" + json.dumps(data, indent=2)
    except Exception:
        pass
    return "SLI state unavailable."


_ROUTES: list[tuple[re.Pattern[str], Callable[[str], str]]] = [
    (
        re.compile(
            r"^(?:show|display|print|give|tell me|what is|what are)?\s*"
            r"(?:my|the)?\s*"
            r"(?:system config(?:uration)?|system info(?:rmation)?|"
            r"os info(?:rmation)?|kernel version|uname)\??$",
            re.I,
        ),
        handle_system_config,
    ),
    (
        re.compile(
            r"^(?:sophyane\s+)?(?:--version|-v|version)\??$",
            re.I,
        ),
        handle_version,
    ),
    (
        re.compile(
            r"(how many|list).*(model|llm)|ollama\s+list|local\s+llm",
            re.I,
        ),
        handle_list_models,
    ),
    (
        re.compile(
            r"(what|which|current|using).*(model|llm)|why.*llama",
            re.I,
        ),
        handle_current_model,
    ),
    (
        re.compile(
            r"\bsli\b.*(status|state|ontology|action)",
            re.I,
        ),
        handle_sli_status,
    ),
]


def try_fast_path(query: str) -> FastResult | None:
    q = (query or "").strip()
    if not q:
        return None
    t0 = time.perf_counter()
    for pat, fn in _ROUTES:
        if pat.search(q):
            text = fn(q)
            ms = (time.perf_counter() - t0) * 1000.0
            return FastResult(text=text, latency_ms=ms)
    return None
