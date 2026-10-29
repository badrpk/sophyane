"""Durable ownership and bounded resource leases for continuous RSI."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import tempfile
import time


class LifecycleError(RuntimeError):
    """A lifecycle lease cannot be acquired or safely recovered."""


@dataclass(frozen=True)
class LifecycleConfig:
    state_dir: Path
    max_guests: int = 1
    memory_budget_mb: int = 1024

    def __post_init__(self) -> None:
        if self.max_guests <= 0:
            raise ValueError("maximum guest count must be positive")
        if self.memory_budget_mb <= 0:
            raise ValueError("guest memory budget must be positive")

    @property
    def singleton_path(self) -> Path:
        return self.state_dir / "continuous-rsi.lock"

    @property
    def registry_path(self) -> Path:
        return self.state_dir / "active-qemu-runs.json"

    @property
    def registry_lock_path(self) -> Path:
        return self.state_dir / "active-qemu-runs.lock"


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _process_identity(pid: int) -> str | None:
    """Return Linux's process start-time token, which changes on PID reuse."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        after_name = stat.rsplit(")", 1)[1].split()
        return after_name[19]
    except (OSError, IndexError, ValueError):
        return None


def _write_registry(config: LifecycleConfig, records: dict[str, dict]) -> None:
    config.state_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="active-qemu-runs-", dir=config.state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, config.registry_path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def load_active_runs(config: LifecycleConfig) -> dict[str, dict]:
    try:
        payload = json.loads(config.registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise LifecycleError(f"active QEMU registry is unreadable: {error}") from error
    if not isinstance(payload, dict) or any(not isinstance(value, dict) for value in payload.values()):
        raise LifecycleError("active QEMU registry has invalid shape")
    return payload


@contextmanager
def _registry_lock(config: LifecycleConfig):
    try:
        import fcntl
    except ImportError as error:
        raise LifecycleError("lifecycle locking is unavailable") from error
    config.state_dir.mkdir(parents=True, exist_ok=True)
    handle = config.registry_lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class SingletonLease:
    """Process-held lock preventing overlapping continuous-RSI supervisors."""

    def __init__(self, config: LifecycleConfig):
        self.config = config
        self._handle = None

    def acquire(self) -> "SingletonLease":
        if self._handle is not None:
            return self
        try:
            import fcntl
            self.config.state_dir.mkdir(parents=True, exist_ok=True)
            handle = self.config.singleton_path.open("a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                handle.close()
                raise LifecycleError("continuous RSI is already active") from error
        except ImportError as error:
            raise LifecycleError("lifecycle locking is unavailable") from error
        self._handle = handle
        return self

    def release(self) -> None:
        if self._handle is None:
            return
        import fcntl
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> "SingletonLease":
        return self.acquire()

    def __exit__(self, *_exc) -> None:
        self.release()


class ExperimentLease:
    """Durable capacity reservation and ownership record for one QEMU run."""

    def __init__(self, config: LifecycleConfig, record: dict):
        self.config = config
        self.record = record
        self._released = False

    @classmethod
    def acquire(cls, config: LifecycleConfig, run_id: str, run_root: Path, memory_mb: int) -> "ExperimentLease":
        if not run_id or memory_mb <= 0:
            raise LifecycleError("QEMU run identity and memory must be positive")
        with _registry_lock(config):
            records = load_active_runs(config)
            used_memory = sum(int(item.get("memory_mb", 0)) for item in records.values())
            if len(records) >= config.max_guests:
                raise LifecycleError("QEMU guest capacity is exhausted")
            if used_memory + memory_mb > config.memory_budget_mb:
                raise LifecycleError("QEMU guest memory budget is exhausted")
            record = {
                "run_id": run_id,
                "run_root": str(Path(run_root).resolve()),
                "pid": None,
                "owner_pid": os.getpid(),
                "owner_identity": _process_identity(os.getpid()),
                "memory_mb": int(memory_mb),
                "started_at": time.time(),
            }
            records[run_id] = record
            _write_registry(config, records)
        return cls(config, record)

    def attach_pid(self, pid: int) -> None:
        if self._released or pid <= 0:
            raise LifecycleError("cannot attach a PID to a released lease")
        with _registry_lock(self.config):
            records = load_active_runs(self.config)
            current = records.get(self.record["run_id"])
            if current is None:
                raise LifecycleError("QEMU lease is no longer registered")
            current["pid"] = int(pid)
            current["pid_identity"] = _process_identity(pid)
            _write_registry(self.config, records)
            self.record = current

    def release(self) -> None:
        if self._released:
            return
        with _registry_lock(self.config):
            records = load_active_runs(self.config)
            records.pop(self.record["run_id"], None)
            _write_registry(self.config, records)
        self._released = True

    def __enter__(self) -> "ExperimentLease":
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def recover_abandoned_runs(
    config: LifecycleConfig,
    *,
    process_is_alive=_alive,
    owner_is_alive=_alive,
    process_identity=_process_identity,
) -> tuple[str, ...]:
    """Remove records whose supervisor died and stop their owned QEMU PIDs."""
    recovered = []
    with _registry_lock(config):
        records = load_active_runs(config)
        for run_id, record in tuple(records.items()):
            owner_pid = int(record.get("owner_pid") or 0)
            guest_pid = int(record.get("pid") or 0)
            owner_alive = owner_is_alive(owner_pid)
            owner_identity = record.get("owner_identity")
            if owner_alive and owner_identity:
                owner_alive = process_identity(owner_pid) == owner_identity
            if owner_alive:
                continue
            guest_identity = record.get("pid_identity")
            guest_alive = guest_pid and process_is_alive(guest_pid)
            guest_owned = guest_alive and guest_identity and process_identity(guest_pid) == guest_identity
            if guest_owned:
                try:
                    os.kill(guest_pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
            records.pop(run_id, None)
            recovered.append(run_id)
        if recovered:
            _write_registry(config, records)
    return tuple(recovered)
