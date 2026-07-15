"""Continual federated training orchestration.

Heavy math runs in ``sophyane-train-core`` (C++17 only). Python:
- discovers base GGUF hash
- stores opt-in + experience digests (not raw private text by default)
- invokes C++ local-step / FedAvg
- publishes deltas over mesh to other user devices
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane" / "continual"
EXPERIENCE_FILE = STATE_DIR / "experience.jsonl"
OPT_IN_FILE = STATE_DIR / "opt_in.json"
GLOBAL_DIR = STATE_DIR / "global_adapter"
LOCAL_DIR = STATE_DIR / "local_adapter"
PEERS_DIR = STATE_DIR / "peer_deltas"
CORE_BIN_CANDIDATES = [
    Path.home() / ".local" / "bin" / "sophyane-train-core",
    Path(__file__).resolve().parents[3] / "sdk" / "cpp" / "continual" / "build" / "sophyane-train-core",
]


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PEERS_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)


def _cpp_sources() -> Path:
    # package layout: src/sophyane/continual → parents[3] = repo root when editable
    for p in (
        Path(__file__).resolve().parents[3] / "sdk" / "cpp" / "continual",
        Path.home() / ".local" / "share" / "sophyane" / "current" / "sdk" / "cpp" / "continual",
    ):
        if (p / "src" / "train_core.cpp").exists():
            return p
    return Path(__file__).resolve().parents[3] / "sdk" / "cpp" / "continual"


def ensure_train_core(*, force_rebuild: bool = False) -> Path:
    """Locate or build the pure-C++ train core binary."""
    _ensure_dirs()
    for cand in CORE_BIN_CANDIDATES:
        if cand.exists() and os.access(cand, os.X_OK) and not force_rebuild:
            return cand
    which = shutil.which("sophyane-train-core")
    if which and not force_rebuild:
        return Path(which)

    src = _cpp_sources()
    build = src / "build"
    build.mkdir(parents=True, exist_ok=True)
    # Prefer simple g++ when cmake missing
    out_bin = Path.home() / ".local" / "bin" / "sophyane-train-core"
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    cpp = src / "src" / "train_core.cpp"
    inc = src / "include"
    if not cpp.exists():
        raise FileNotFoundError(f"C++ train core sources missing at {src}")

    if shutil.which("cmake"):
        subprocess.run(
            ["cmake", "-S", str(src), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["cmake", "--build", str(build), "-j", str(max(1, (os.cpu_count() or 2) // 2))],
            check=True,
            capture_output=True,
            text=True,
        )
        built = build / "sophyane-train-core"
        if built.exists():
            shutil.copy2(built, out_bin)
            out_bin.chmod(0o755)
            return out_bin

    # Fallback: direct g++
    gxx = shutil.which("g++") or shutil.which("c++")
    if not gxx:
        raise RuntimeError("g++ required to build sophyane-train-core (C++ continual engine)")
    subprocess.run(
        [gxx, "-O2", "-std=c++17", f"-I{inc}", str(cpp), "-o", str(out_bin)],
        check=True,
        capture_output=True,
        text=True,
    )
    out_bin.chmod(0o755)
    return out_bin


def _run_core(args: list[str], timeout: float = 120.0) -> tuple[int, str]:
    core = ensure_train_core()
    completed = subprocess.run(
        [str(core), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return completed.returncode, out


def base_model_fingerprint() -> dict[str, Any]:
    """Hash existing local GGUF / runtime so adapters attach to the right base."""
    gguf_dir = Path.home() / ".local" / "share" / "sophyane" / "models" / "gguf"
    files: list[Path] = []
    if gguf_dir.exists():
        files = sorted(gguf_dir.glob("*.gguf"))
    h = hashlib.sha256()
    name = "none"
    size = 0
    if files:
        path = files[0]
        name = path.name
        size = path.stat().st_size
        # Hash first + last 1MB for speed on large weights
        with path.open("rb") as handle:
            head = handle.read(1_048_576)
            h.update(head)
            if size > 2_097_152:
                handle.seek(size - 1_048_576)
                h.update(handle.read(1_048_576))
            h.update(str(size).encode())
    else:
        h.update(b"no-gguf")
    return {
        "base_model": name,
        "base_hash": h.hexdigest()[:32],
        "bytes": size,
        "provider_hint": "local_gguf",
    }


def train_opt_in(enabled: bool = True, *, share_raw_text: bool = False) -> dict[str, Any]:
    """Users must opt in before their device contributes compute/deltas."""
    _ensure_dirs()
    payload = {
        "opt_in": bool(enabled),
        "share_raw_text": bool(share_raw_text),
        "updated_at": time.time(),
        "peer_id": f"{socket.gethostname()}-{os.getuid() if hasattr(os, 'getuid') else 'u'}",
        "note": (
            "Opt-in continuous federated training: local C++ PEFT steps on your device; "
            "adapter deltas (not full weights) shared via mesh when enabled."
        ),
    }
    OPT_IN_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def is_opted_in() -> bool:
    if os.environ.get("SOPHYANE_TRAIN_OPT_IN", "").lower() in {"1", "true", "yes"}:
        return True
    if not OPT_IN_FILE.exists():
        return False
    try:
        data = json.loads(OPT_IN_FILE.read_text(encoding="utf-8"))
        return bool(data.get("opt_in"))
    except json.JSONDecodeError:
        return False


def _opt_meta() -> dict[str, Any]:
    if OPT_IN_FILE.exists():
        try:
            return json.loads(OPT_IN_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"opt_in": False, "share_raw_text": False, "peer_id": socket.gethostname()}


def record_experience(prompt: str, response: str = "", *, source: str = "chat") -> dict[str, Any]:
    """Append a privacy-preserving experience line for continual training.

    By default only digests are stored (hash + length + source), not full text,
    unless the user opted into share_raw_text.
    """
    _ensure_dirs()
    meta = _opt_meta()
    blob = f"{prompt}\n{response}".strip()
    digest = hashlib.sha256(blob.encode("utf-8", errors="replace")).hexdigest()
    if meta.get("share_raw_text") and is_opted_in():
        line = {
            "ts": time.time(),
            "source": source,
            "text": blob[:4000],
            "digest": digest,
        }
    else:
        # Store enough structure for C++ feature digests without private content
        line = {
            "ts": time.time(),
            "source": source,
            "digest": digest,
            "n_chars": len(blob),
            "prompt_len": len(prompt),
            "response_len": len(response),
            # Synthetic stable text for C++ local-step (no private payload)
            "text": f"exp:{source}:{digest}:{len(blob)}",
        }
    with EXPERIENCE_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return {"ok": True, "digest": digest, "opt_in": is_opted_in()}


def _experience_for_core(max_lines: int = 256) -> Path:
    """Write a plain-text experience file the C++ core can read."""
    _ensure_dirs()
    out = STATE_DIR / "experience_for_core.txt"
    lines: list[str] = []
    if EXPERIENCE_FILE.exists():
        raw = EXPERIENCE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        for row in raw[-max_lines:]:
            try:
                obj = json.loads(row)
                lines.append(str(obj.get("text") or obj.get("digest") or row))
            except json.JSONDecodeError:
                lines.append(row)
    if not lines:
        # Seed with platform self-knowledge so a first step still runs
        lines = [
            f"sophyane continual seed {__version__} {socket.gethostname()}",
            "prefer accurate helpful tool-using agent behavior",
            "hardware efficient cpp peft adapter training",
        ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def run_local_train_step(*, round_id: int | None = None) -> dict[str, Any]:
    """Run one C++ local continual step against existing base weights fingerprint."""
    if not is_opted_in():
        return {
            "ok": False,
            "error": "training not opted in; run: sophyane --train-opt-in",
            "opt_in": False,
        }
    _ensure_dirs()
    base = base_model_fingerprint()
    exp = _experience_for_core()
    peer = str(_opt_meta().get("peer_id") or socket.gethostname())
    rnd = int(round_id if round_id is not None else time.time() // 3600)
    code, out = _run_core(
        [
            "local-step",
            "--experience",
            str(exp),
            "--out",
            str(LOCAL_DIR),
            "--base-hash",
            base["base_hash"],
            "--peer",
            peer,
            "--round",
            str(rnd),
            "--rank",
            os.environ.get("SOPHYANE_TRAIN_RANK", "8"),
        ]
    )
    meta: dict[str, Any] = {}
    try:
        # stdout is adapter json
        meta = json.loads(out[out.find("{") : out.rfind("}") + 1])
    except Exception:  # noqa: BLE001
        meta = {"raw": out[:500]}
    ok = code == 0 and (LOCAL_DIR / "adapter.bin").exists()
    result = {
        "ok": ok,
        "exit_code": code,
        "base": base,
        "adapter_dir": str(LOCAL_DIR),
        "meta": meta,
        "core": "C++",
        "language": "C++17",
    }
    if ok:
        try:
            from sophyane.self_improve.ledger import propose_improvement

            propose_improvement(
                "train",
                "continual-local-step",
                f"C++ PEFT local step round={rnd} loss={meta.get('loss')} samples={meta.get('samples')}",
                evidence={"base_hash": base["base_hash"], "weights": meta.get("weights_sha256")},
                score=0.15,
            )
        except Exception:  # noqa: BLE001
            pass
    return result


def ingest_peer_delta(peer_id: str, adapter_json: dict[str, Any], adapter_b64: str | None = None) -> dict[str, Any]:
    """Accept a peer's adapter package into the local peer_deltas pool."""
    import base64

    _ensure_dirs()
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in peer_id)[:64] or "peer"
    dest = PEERS_DIR / safe
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "adapter.json").write_text(json.dumps(adapter_json, indent=2) + "\n", encoding="utf-8")
    if adapter_b64:
        (dest / "adapter.bin").write_bytes(base64.b64decode(adapter_b64))
    return {"ok": True, "peer_id": safe, "path": str(dest)}


def federated_aggregate() -> dict[str, Any]:
    """FedAvg all peer deltas + local adapter via C++ core."""
    if not is_opted_in():
        return {"ok": False, "error": "not opted in"}
    _ensure_dirs()
    # Copy local into peers pool for this round
    if (LOCAL_DIR / "adapter.bin").exists():
        peer = str(_opt_meta().get("peer_id") or "local")
        dest = PEERS_DIR / "self"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LOCAL_DIR / "adapter.bin", dest / "adapter.bin")
        if (LOCAL_DIR / "adapter.json").exists():
            shutil.copy2(LOCAL_DIR / "adapter.json", dest / "adapter.json")
    code, out = _run_core(["aggregate", "--deltas", str(PEERS_DIR), "--out", str(GLOBAL_DIR)])
    meta: dict[str, Any] = {}
    try:
        meta = json.loads(out[out.find("{") : out.rfind("}") + 1])
    except Exception:  # noqa: BLE001
        meta = {"raw": out[:500]}
    return {
        "ok": code == 0 and (GLOBAL_DIR / "adapter.bin").exists(),
        "exit_code": code,
        "global_dir": str(GLOBAL_DIR),
        "meta": meta,
        "core": "C++",
        "peers_pooled": sum(1 for p in PEERS_DIR.iterdir() if p.is_dir()) if PEERS_DIR.exists() else 0,
    }


def export_local_delta_package() -> dict[str, Any]:
    """Package local adapter for mesh transport (JSON + base64 weights)."""
    import base64

    if not (LOCAL_DIR / "adapter.bin").exists():
        return {"ok": False, "error": "no local adapter; run local train step first"}
    meta = {}
    if (LOCAL_DIR / "adapter.json").exists():
        meta = json.loads((LOCAL_DIR / "adapter.json").read_text(encoding="utf-8"))
    raw = (LOCAL_DIR / "adapter.bin").read_bytes()
    return {
        "ok": True,
        "meta": meta,
        "adapter_b64": base64.b64encode(raw).decode("ascii"),
        "bytes": len(raw),
        "peer_id": _opt_meta().get("peer_id"),
    }


def mesh_publish_delta(host: str = "127.0.0.1", port: int = 8777) -> dict[str, Any]:
    """POST local delta to local mesh node (which can fan-out)."""
    pkg = export_local_delta_package()
    if not pkg.get("ok"):
        return pkg
    body = json.dumps(
        {
            "peer_id": pkg.get("peer_id"),
            "meta": pkg.get("meta"),
            "adapter_b64": pkg.get("adapter_b64"),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/mesh/train/contribute",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as error:
        return {"ok": False, "error": str(error), "package_ready": True, "bytes": pkg.get("bytes")}


def contribute_round(*, publish_mesh: bool = True) -> dict[str, Any]:
    """Full continuous contribution: local C++ step → optional mesh publish → aggregate."""
    local = run_local_train_step()
    if not local.get("ok"):
        return {"ok": False, "phase": "local", "local": local}
    mesh_result: dict[str, Any] = {"skipped": True}
    if publish_mesh:
        mesh_result = mesh_publish_delta()
    agg = federated_aggregate()
    return {
        "ok": bool(local.get("ok") and agg.get("ok")),
        "local": local,
        "mesh": mesh_result,
        "aggregate": agg,
        "message": (
            "Continual federated round complete. C++ PEFT adapters improve on existing "
            "base LLM weights using opted-in user device compute."
        ),
    }


def train_status() -> dict[str, Any]:
    _ensure_dirs()
    core_ok = False
    core_path = ""
    core_info: dict[str, Any] = {}
    try:
        path = ensure_train_core()
        core_path = str(path)
        code, out = _run_core(["status"])
        core_ok = code == 0
        try:
            core_info = json.loads(out[out.find("{") : out.rfind("}") + 1])
        except Exception:  # noqa: BLE001
            core_info = {"raw": out[:200]}
    except Exception as error:  # noqa: BLE001
        core_info = {"error": str(error)}

    exp_n = 0
    if EXPERIENCE_FILE.exists():
        exp_n = sum(1 for _ in EXPERIENCE_FILE.open(encoding="utf-8", errors="replace"))

    return {
        "ok": core_ok,
        "version": __version__,
        "opt_in": is_opted_in(),
        "opt_meta": _opt_meta(),
        "base": base_model_fingerprint(),
        "experience_lines": exp_n,
        "local_adapter": (LOCAL_DIR / "adapter.bin").exists(),
        "global_adapter": (GLOBAL_DIR / "adapter.bin").exists(),
        "peer_deltas": sum(1 for p in PEERS_DIR.iterdir() if p.is_dir()) if PEERS_DIR.exists() else 0,
        "core_path": core_path,
        "core": core_info,
        "language": "C++17 (train math) + Python (orchestration/mesh)",
        "goal": "Continuously improve Sophyane LLM adapters across millions of installs via federated PEFT",
    }


def handle_train_rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mesh / API RPC surface for continual training."""
    params = params or {}
    if method in {"train.status", "status"}:
        return {"ok": True, "result": train_status()}
    if method in {"train.opt_in", "opt_in"}:
        return {"ok": True, "result": train_opt_in(bool(params.get("enabled", True)))}
    if method in {"train.record", "record"}:
        return {
            "ok": True,
            "result": record_experience(
                str(params.get("prompt") or ""),
                str(params.get("response") or ""),
                source=str(params.get("source") or "mesh"),
            ),
        }
    if method in {"train.step", "local_step"}:
        return run_local_train_step(round_id=params.get("round"))
    if method in {"train.contribute", "contribute"}:
        peer = str(params.get("peer_id") or "peer")
        meta = params.get("meta") if isinstance(params.get("meta"), dict) else {}
        return ingest_peer_delta(peer, meta, params.get("adapter_b64"))
    if method in {"train.aggregate", "aggregate"}:
        return federated_aggregate()
    if method in {"train.round", "round"}:
        return contribute_round(publish_mesh=bool(params.get("publish_mesh", False)))
    return {"ok": False, "error": f"unknown train method: {method}"}
