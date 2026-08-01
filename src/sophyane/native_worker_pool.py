"""Persistent native worker pool (NIFDU / Neuron) over line-delimited IPC.

Protocol (worker side, optional):
  stdin  JSON line: {"id": "...", "cmd": "run"|"ping"|"shutdown", ...}
  stdout JSON line: {"id": "...", "ok": true, "stdout": "...", ...}

If the binary does not speak JSON-IPC, the pool falls back to one-shot
subprocess for that request, but still reuses discovery paths and can
parallelize independent jobs.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from sophyane.native_backends import probe_nifdu, probe_neuron


@dataclass
class _Worker:
    name: str
    path: str
    mode: str  # "ipc" | "oneshot"
    proc: subprocess.Popen[str] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_used: float = 0.0


_POOL: dict[str, _Worker] = {}
_POOL_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_IMPORT_CACHE: dict[str, Any] = {}


def cached_import(module: str):
    if module not in _IMPORT_CACHE:
        _IMPORT_CACHE[module] = __import__(module, fromlist=["*"])
    return _IMPORT_CACHE[module]


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        n = int(os.environ.get("SOPHYANE_NATIVE_POOL_WORKERS", "4"))
        _EXECUTOR = ThreadPoolExecutor(max_workers=max(2, n), thread_name_prefix="sophyane-native")
    return _EXECUTOR


def _try_start_ipc(path: str) -> subprocess.Popen[str] | None:
    """Start binary in optional IPC mode. Returns None if unsupported."""
    if os.environ.get("SOPHYANE_NATIVE_IPC", "0") not in {"1", "true", "yes"}:
        return None
    try:
        proc = subprocess.Popen(
            [path, "--sophyane-ipc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        # quick ping with short timeout
        assert proc.stdin and proc.stdout
        proc.stdin.write(json.dumps({"id": "ping", "cmd": "ping"}) + "\n")
        proc.stdin.flush()
        # non-blocking-ish read with timeout via thread
        line_holder: list[str] = []

        def _read():
            try:
                line_holder.append(proc.stdout.readline())
            except Exception:
                pass

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=0.4)
        if not line_holder or not line_holder[0].strip():
            proc.kill()
            return None
        try:
            msg = json.loads(line_holder[0])
            if not msg.get("ok", True) and msg.get("cmd") not in {None, "ping"}:
                proc.kill()
                return None
        except json.JSONDecodeError:
            proc.kill()
            return None
        return proc
    except Exception:
        return None


def _get_worker(name: str) -> _Worker | None:
    with _POOL_LOCK:
        w = _POOL.get(name)
        if w and w.path:
            # dead IPC process?
            if w.mode == "ipc" and w.proc and w.proc.poll() is not None:
                w.proc = None
                w.mode = "oneshot"
            return w

        if name == "nifdu":
            path = probe_nifdu().path
        elif name == "neuron":
            path = probe_neuron().path
        else:
            return None
        if not path:
            return None
        proc = _try_start_ipc(path)
        w = _Worker(
            name=name,
            path=path,
            mode="ipc" if proc else "oneshot",
            proc=proc,
        )
        _POOL[name] = w
        return w


def _run_oneshot(path: str, args: list[str] | None, timeout: float) -> dict[str, Any]:
    t0 = time.perf_counter()
    cmd = [path] + (args or [])
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": p.returncode == 0 or bool(p.stdout),
            "returncode": p.returncode,
            "stdout": (p.stdout or "")[-8000:],
            "stderr": (p.stderr or "")[-2000:],
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "mode": "oneshot",
            "cmd": cmd,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "mode": "oneshot", "cmd": cmd}


def _run_ipc(worker: _Worker, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    t0 = time.perf_counter()
    with worker.lock:
        proc = worker.proc
        if not proc or not proc.stdin or not proc.stdout:
            return _run_oneshot(worker.path, payload.get("args"), timeout)
        req_id = payload.get("id") or str(uuid.uuid4())
        msg = {"id": req_id, "cmd": payload.get("cmd", "run"), **{k: v for k, v in payload.items() if k not in {"id", "cmd"}}}
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
        except Exception:
            worker.proc = None
            worker.mode = "oneshot"
            return _run_oneshot(worker.path, payload.get("args"), timeout)

        line_holder: list[str] = []

        def _read():
            try:
                line_holder.append(proc.stdout.readline())
            except Exception as e:
                line_holder.append(json.dumps({"ok": False, "error": str(e)}))

        th = threading.Thread(target=_read, daemon=True)
        th.start()
        th.join(timeout=timeout)
        worker.last_used = time.monotonic()
        if not line_holder:
            return {
                "ok": False,
                "error": "ipc timeout",
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "mode": "ipc",
            }
        try:
            data = json.loads(line_holder[0])
        except json.JSONDecodeError:
            data = {"ok": True, "stdout": line_holder[0], "mode": "ipc-raw"}
        data.setdefault("ms", round((time.perf_counter() - t0) * 1000, 1))
        data.setdefault("mode", "ipc")
        return data


def run_worker(name: str, *, args: list[str] | None = None, timeout: float = 120.0, cmd: str = "run") -> dict[str, Any]:
    worker = _get_worker(name)
    if not worker:
        return {"ok": False, "error": f"{name} not available"}
    if worker.mode == "ipc" and worker.proc:
        return _run_ipc(worker, {"cmd": cmd, "args": args or []}, timeout)
    return _run_oneshot(worker.path, args, timeout)


def run_many(jobs: list[dict[str, Any]], *, timeout: float = 120.0) -> list[dict[str, Any]]:
    """Run independent workers concurrently.

    jobs: [{"name": "neuron"|"nifdu", "args": [...], "id": optional}, ...]
    """
    if not jobs:
        return []
    if len(jobs) == 1:
        j = jobs[0]
        r = run_worker(j["name"], args=j.get("args"), timeout=timeout, cmd=j.get("cmd", "run"))
        r["job_id"] = j.get("id")
        return [r]

    futs = {}
    ex = _executor()
    for j in jobs:
        fut = ex.submit(
            run_worker,
            j["name"],
            args=j.get("args"),
            timeout=timeout,
            cmd=j.get("cmd", "run"),
        )
        futs[fut] = j
    out: list[dict[str, Any]] = []
    for fut in as_completed(futs):
        j = futs[fut]
        try:
            r = fut.result()
        except Exception as e:
            r = {"ok": False, "error": str(e)}
        r["job_id"] = j.get("id")
        r["worker"] = j["name"]
        out.append(r)
    # stable order by original jobs
    by_id = {r.get("job_id"): r for r in out}
    ordered = []
    for j in jobs:
        ordered.append(by_id.get(j.get("id"), next((r for r in out if r.get("worker") == j["name"]), {"ok": False})))
    return ordered


def shutdown_pool() -> None:
    global _EXECUTOR
    with _POOL_LOCK:
        for w in _POOL.values():
            if w.proc and w.proc.poll() is None:
                try:
                    if w.proc.stdin:
                        w.proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                        w.proc.stdin.flush()
                except Exception:
                    pass
                try:
                    w.proc.terminate()
                except Exception:
                    pass
        _POOL.clear()
    if _EXECUTOR is not None:
        _EXECUTOR.shutdown(wait=False, cancel_futures=True)
        _EXECUTOR = None


def pool_stats() -> dict[str, Any]:
    with _POOL_LOCK:
        return {
            name: {
                "path": w.path,
                "mode": w.mode,
                "alive": bool(w.proc and w.proc.poll() is None),
            }
            for name, w in _POOL.items()
        }
