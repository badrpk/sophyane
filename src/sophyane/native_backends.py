"""Optional NIFDU / Neuron backends. Missing binaries = soft skip."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BackendProbe:
    name: str
    available: bool
    path: str | None
    detail: str


def _which(env_key: str, *names: str) -> str | None:
    env = os.environ.get(env_key, "").strip()
    if env and Path(env).exists():
        return env
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def probe_nifdu() -> BackendProbe:
    path = _which(
        "SOPHYANE_NIFDU_BIN",
        "nifdu",
        str(Path.home() / "nifdu" / "build" / "nifdu"),
        str(Path.home() / "nifdu" / "build" / "Release" / "nifdu.exe"),
    )
    return BackendProbe("nifdu", bool(path), path, path or "not found")


def probe_neuron() -> BackendProbe:
    path = _which(
        "SOPHYANE_NEURON_BIN",
        "neuron",
        "test_neuron_capabilities",
        str(Path.home() / "neuron_repo" / "build" / "test_neuron_capabilities"),
        str(Path.home() / "nifdu" / "build" / "test_neuron_capabilities"),
    )
    return BackendProbe("neuron", bool(path), path, path or "not found")


def run_json(path: str, args: list[str], timeout: float = 30.0) -> dict[str, Any]:
    proc = subprocess.run(
        [path, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = (proc.stdout or "").strip()
    try:
        payload = json.loads(out) if out.startswith("{") else {"stdout": out}
    except json.JSONDecodeError:
        payload = {"stdout": out}
    payload["ok"] = proc.returncode == 0
    payload["returncode"] = proc.returncode
    if proc.stderr:
        payload["stderr"] = proc.stderr[-2000:]
    return payload


def status() -> dict[str, Any]:
    n = probe_nifdu()
    e = probe_neuron()
    return {
        "nifdu": {"available": n.available, "path": n.path},
        "neuron": {"available": e.available, "path": e.path},
        "version_hint": {
            "nifdu_tag": "v2.1.0",
            "neuron_tag": "v2.1.0",
            "nifdu_sha": "e947217",
            "neuron_sha": "af27f80",
        },
    }


def status_text() -> str:
    """Human one-shot for registry / chat; no engine logic inlined."""
    s = status()
    lines = [
        "Native workers",
        f"  nifdu : {'OK' if s['nifdu']['available'] else 'missing'}  {s['nifdu'].get('path') or ''}",
        f"  neuron: {'OK' if s['neuron']['available'] else 'missing'}  {s['neuron'].get('path') or ''}",
        "Roles: Sophyane=policy | Neuron=SNN | NIFDU=product C++",
        "No duplicated engine code in Sophyane.",
    ]
    return "\n".join(lines)
