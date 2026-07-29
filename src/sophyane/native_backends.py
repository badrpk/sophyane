"""Optional NIFDU / Neuron backend probes with TTL cache."""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Process-wide caches (survive across requests in same interpreter)
_DISCOVERY_CACHE: dict[str, tuple[float, "BackendProbe"]] = {}
_DISCOVERY_TTL = float(os.environ.get("SOPHYANE_NATIVE_DISCOVERY_TTL", "300"))  # seconds
_STATUS_CACHE: tuple[float, dict[str, Any]] | None = None
_STATUS_TTL = float(os.environ.get("SOPHYANE_NATIVE_STATUS_TTL", "60"))


@dataclass(frozen=True)
class BackendProbe:
    name: str
    available: bool
    path: str | None
    detail: str = ""


def _which(*candidates: str) -> str | None:
    for c in candidates:
        if not c:
            continue
        # env override
        if c.startswith("SOPHYANE_") or c.isupper():
            val = os.environ.get(c)
            if val and Path(val).is_file() and os.access(val, os.X_OK):
                return val
            continue
        p = Path(c).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p.resolve())
        found = shutil.which(c)
        if found:
            return found
    return None


def _probe_nifdu_uncached() -> BackendProbe:
    path = _which(
        "SOPHYANE_NIFDU_BIN",
        "nifdu",
        str(Path.home() / ".local/bin/nifdu"),
        str(Path.home() / "nifdu/build/nifdu"),
        str(Path.home() / "nifdu/build/Release/nifdu.exe"),
        "/tmp/nifdu-clean-build/nifdu",
    )
    return BackendProbe("nifdu", bool(path), path, path or "not found")


def _probe_neuron_uncached() -> BackendProbe:
    path = _which(
        "SOPHYANE_NEURON_BIN",
        "test_neuron_capabilities",
        str(Path.home() / ".local/bin/test_neuron_capabilities"),
        str(Path.home() / "nifdu/build/test_neuron_capabilities"),
        str(Path.home() / "neuron_repo/build/test_neuron_capabilities"),
        "/tmp/nifdu-clean-build/test_neuron_capabilities",
    )
    return BackendProbe("neuron", bool(path), path, path or "not found")


def _cached(key: str, factory) -> BackendProbe:
    now = time.monotonic()
    hit = _DISCOVERY_CACHE.get(key)
    if hit and (now - hit[0]) < _DISCOVERY_TTL:
        return hit[1]
    probe = factory()
    _DISCOVERY_CACHE[key] = (now, probe)
    return probe


def probe_nifdu(*, force: bool = False) -> BackendProbe:
    if force:
        _DISCOVERY_CACHE.pop("nifdu", None)
    return _cached("nifdu", _probe_nifdu_uncached)


def probe_neuron(*, force: bool = False) -> BackendProbe:
    if force:
        _DISCOVERY_CACHE.pop("neuron", None)
    return _cached("neuron", _probe_neuron_uncached)


def invalidate_discovery() -> None:
    global _STATUS_CACHE
    _DISCOVERY_CACHE.clear()
    _STATUS_CACHE = None


def status(*, force: bool = False) -> dict[str, Any]:
    global _STATUS_CACHE
    now = time.monotonic()
    if not force and _STATUS_CACHE and (now - _STATUS_CACHE[0]) < _STATUS_TTL:
        return _STATUS_CACHE[1]
    data = {
        "nifdu": {
            "available": probe_nifdu(force=force).available,
            "path": probe_nifdu().path,
        },
        "neuron": {
            "available": probe_neuron(force=force).available,
            "path": probe_neuron().path,
        },
        "version_hint": {
            "nifdu_tag": os.environ.get("SOPHYANE_NATIVE_TAG", "v2.1.0"),
            "neuron_tag": os.environ.get("SOPHYANE_NATIVE_TAG", "v2.1.0"),
        },
        "discovery_ttl_s": _DISCOVERY_TTL,
        "status_ttl_s": _STATUS_TTL,
    }
    _STATUS_CACHE = (now, data)
    return data


def status_text(*, force: bool = False) -> str:
    s = status(force=force)
    lines = [
        "Native backends",
        f"  nifdu:  {'OK' if s['nifdu']['available'] else 'missing'}  {s['nifdu'].get('path') or ''}",
        f"  neuron: {'OK' if s['neuron']['available'] else 'missing'}  {s['neuron'].get('path') or ''}",
        f"  discovery TTL: {s['discovery_ttl_s']}s",
    ]
    return "\n".join(lines)
