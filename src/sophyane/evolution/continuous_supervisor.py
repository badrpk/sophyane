"""Opt-in, bounded supervisor for explicit evolution analysis cycles."""
from __future__ import annotations
import hashlib, json, math, os, time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
DEFAULT_STATE_DIR = Path.home() / ".local/state/sophyane/continuous_rsi"
MAX_STATE_BYTES = 64 * 1024

def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)

def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

@contextmanager
def _exclusive_lock(path: Path):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc: raise RuntimeError("continuous RSI supervisor already running") from exc
        try: yield
        finally: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size > MAX_STATE_BYTES: return {}
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError): return {}
    return value if isinstance(value, dict) else {}

@contextmanager
def _deadline(seconds: float):
    import signal
    if seconds <= 0 or not hasattr(signal, "setitimer"):
        yield; return
    def alarm(_signum, _frame): raise TimeoutError("evolution cycle deadline exceeded")
    previous = signal.getsignal(signal.SIGALRM); signal.signal(signal.SIGALRM, alarm); signal.setitimer(signal.ITIMER_REAL, seconds)
    try: yield
    finally: signal.setitimer(signal.ITIMER_REAL, 0); signal.signal(signal.SIGALRM, previous)

def run_bounded_continuous_rsi(repo: str | Path, *, max_cycles: int = 1, per_cycle_deadline_seconds: float = 300.0, backoff_seconds: float = 5.0, maximum_backoff_seconds: float = 300.0, max_failures: int = 3, resume: bool = False, stop: Callable[[], bool] | None = None, state_dir: str | Path | None = None, engine_factory: Callable[[Any], Any] | None = None, sleep_fn: Callable[[float], None] = time.sleep, now_fn: Callable[[], float] = time.time) -> dict[str, Any]:
    if not isinstance(max_cycles, int) or isinstance(max_cycles, bool) or max_cycles <= 0: raise ValueError("max_cycles must be a positive finite integer")
    if (not math.isfinite(float(per_cycle_deadline_seconds)) or not math.isfinite(float(backoff_seconds)) or not math.isfinite(float(maximum_backoff_seconds)) or per_cycle_deadline_seconds <= 0 or backoff_seconds < 0 or maximum_backoff_seconds < 0 or max_failures < 0): raise ValueError("invalid supervisor bounds")
    root = Path(repo).expanduser().resolve(); directory = Path(state_dir or DEFAULT_STATE_DIR).expanduser(); state_path = directory / "run.json"
    config = {"repo": str(root), "max_cycles": max_cycles, "deadline": float(per_cycle_deadline_seconds), "backoff": float(backoff_seconds), "max_backoff": float(maximum_backoff_seconds), "max_failures": max_failures}; fingerprint = _fingerprint(config)
    with _exclusive_lock(directory / "run.lock"):
        state = _load_state(state_path) if resume else {}
        if state.get("configuration_fingerprint") not in (None, fingerprint): state = {}
        run_id = str(state.get("run_id") or f"rsi-{int(now_fn())}-{os.getpid()}"); completed = int(state.get("completed_cycles") or 0); failures = int(state.get("consecutive_failures") or 0); cycle = int(state.get("cycle_index") or completed + 1)
        state.update({"run_id": run_id, "created_at": state.get("created_at") or now_fn(), "updated_at": now_fn(), "cycle_index": cycle, "max_cycles": max_cycles, "completed_cycles": completed, "consecutive_failures": failures, "configuration_fingerprint": fingerprint}); _atomic_write(state_path, state)
        if engine_factory is None:
            from .engine import EvolutionEngine
            engine_factory = EvolutionEngine
        while completed < max_cycles:
            if stop and stop(): state.update({"last_cycle_status": "stopped", "updated_at": now_fn()}); _atomic_write(state_path, state); break
            started = now_fn(); state.update({"cycle_index": cycle, "last_cycle_status": "in_progress", "last_cycle_started_at": started, "updated_at": started}); _atomic_write(state_path, state)
            try:
                from .models import EvolutionConfig
                cfg = EvolutionConfig(repo=root, cycles=1, timeout_seconds=int(per_cycle_deadline_seconds), allow_cloud_analysis=False, allow_candidate_patches=False, allow_promotion=False)
                with _deadline(float(per_cycle_deadline_seconds)): result = engine_factory(cfg).run()
                finished = now_fn()
                if finished - started > per_cycle_deadline_seconds: raise TimeoutError("evolution cycle deadline exceeded")
                completed += 1; failures = 0; cycle += 1; state.update({"completed_cycles": completed, "cycle_index": cycle, "consecutive_failures": 0, "last_cycle_status": "completed", "last_cycle_finished_at": finished, "next_eligible_run_at": None, "updated_at": finished}); _atomic_write(state_path, state)
            except Exception as exc:
                failures += 1; finished = now_fn(); delay = min(float(maximum_backoff_seconds), float(backoff_seconds) * (2 ** (failures - 1))); state.update({"consecutive_failures": failures, "last_cycle_status": "failed", "last_error": type(exc).__name__, "last_cycle_finished_at": finished, "next_eligible_run_at": finished + delay, "updated_at": finished}); _atomic_write(state_path, state)
                if failures > max_failures: break
                if delay: sleep_fn(delay)
        return state

__all__ = ["run_bounded_continuous_rsi"]
