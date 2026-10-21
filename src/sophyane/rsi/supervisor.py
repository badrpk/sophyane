"""Default-on lifecycle helpers and an external RSI process watchdog."""
import argparse
import atexit
from contextlib import contextmanager
from dataclasses import dataclass, replace
from functools import wraps
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

from .observation_bus import autonomous_bus, ImprovementObservation, ImprovementSource

_lock = threading.RLock()
_instance = None
_curriculum_instance = None
_active = 0
_last_activity = 0.0

@dataclass
class Supervisor:
    thread: threading.Thread
    stop_event: threading.Event
    wake_event: threading.Event


@dataclass(frozen=True)
class ExternalWatchdogConfig:
    state_dir: Path
    pid_file: Path
    socket_path: Path
    heartbeat_interval: float = 5.0
    heartbeat_stale_after: float = 30.0
    restart_backoff: float = 1.0
    max_restart_backoff: float = 60.0
    daemonize: bool = False
    wakelock: bool = False
    watchdog_mode: str = "external"

    def __post_init__(self):
        if self.watchdog_mode != "external":
            raise ValueError("watchdog mode must be external")
        if self.heartbeat_interval <= 0 or self.heartbeat_stale_after <= 0:
            raise ValueError("heartbeat intervals must be positive")
        if self.restart_backoff <= 0 or self.max_restart_backoff < self.restart_backoff:
            raise ValueError("invalid restart backoff")


def parse_external_args(argv=None):
    default_state = Path.home() / ".local/state/sophyane/continuous-rsi"
    parser = argparse.ArgumentParser(prog="python -m sophyane.rsi.supervisor")
    parser.add_argument("--daemonize", action="store_true")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--pid-file", type=Path, default=default_state / "external-rsi.pid")
    parser.add_argument("--socket-path", type=Path, default=default_state / "rsi.sock")
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--watchdog-mode", choices=("external",), default=None)
    parser.add_argument("--wakelock", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if not args.status and args.watchdog_mode is None:
        parser.error("--watchdog-mode=external is required unless --status is used")
    if args.state_dir is None:
        args.state_dir = args.socket_path.parent
    args.heartbeat_stale_after = max(3.0 * args.heartbeat_interval, 15.0)
    return args


def status_external_watchdog(args) -> dict[str, object]:
    state_dir = Path(args.state_dir)
    pid_file = Path(args.pid_file)
    supervisor_pid = None
    try:
        supervisor_pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    child_pid = None
    payload: dict[str, object] = {}
    try:
        payload = json.loads((state_dir / "external-watchdog.json").read_text(encoding="utf-8"))
        child_pid = int(payload["child_pid"]) if payload.get("child_pid") else None
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        pass
    alive = ExternalWatchdog._default_process_is_alive
    result = {
        **payload,
        "supervisor_pid": supervisor_pid,
        "supervisor_alive": bool(supervisor_pid and alive(supervisor_pid)),
        "child_pid": child_pid,
        "child_alive": bool(child_pid and alive(child_pid)),
        "heartbeat": None,
    }
    try:
        heartbeat = json.loads((state_dir / "heartbeat.json").read_text(encoding="utf-8"))
        result["heartbeat"] = {
            "pid": heartbeat.get("pid"),
            "state": heartbeat.get("state"),
            "last_tick_at": heartbeat.get("last_tick_at"),
            "last_error": heartbeat.get("last_error", ""),
        }
    except (OSError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
        pass
    return result


def acquire_wakelock(enabled: bool, *, runner=subprocess.run) -> bool:
    """Best-effort Termux wakelock acquisition; unavailable is nonfatal."""
    if not enabled:
        return False
    command = shutil.which("termux-wake-lock")
    if not command:
        return False
    try:
        return runner([command], check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def release_wakelock(enabled: bool, *, runner=subprocess.run) -> bool:
    if not enabled:
        return False
    command = shutil.which("termux-wake-unlock")
    if not command:
        return False
    try:
        return runner([command], check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class ExternalWatchdog:
    """Own and supervise one RSI daemon process."""

    def __init__(self, config: ExternalWatchdogConfig, *, process_is_alive=None, clock=time.time, popen=None):
        self.config = config
        self.clock = clock
        self.process_is_alive = process_is_alive or self._default_process_is_alive
        self.popen = popen or subprocess.Popen
        self.child = None
        self.restart_count = 0
        self.last_error = ""

    @staticmethod
    def _default_process_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def recover_stale_artifacts(self) -> None:
        pid_path = self.config.pid_file
        if pid_path.exists():
            try:
                pid = int(pid_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pid = 0
            if pid and self.process_is_alive(pid):
                raise RuntimeError(f"external RSI watchdog already running: {pid}")
            pid_path.unlink(missing_ok=True)
        if self.config.socket_path.exists():
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.2)
                probe.connect(str(self.config.socket_path))
            except OSError:
                self.config.socket_path.unlink(missing_ok=True)
            else:
                raise RuntimeError(f"RSI daemon socket already active: {self.config.socket_path}")
            finally:
                probe.close()
        (self.config.state_dir / "rsi-child.pid").unlink(missing_ok=True)

    def heartbeat_healthy(self) -> bool:
        try:
            raw = json.loads((self.config.state_dir / "heartbeat.json").read_text(encoding="utf-8"))
            pid = int(raw["pid"])
            last_tick = float(raw["last_tick_at"])
            state = str(raw["state"])
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return False
        child_pid = getattr(self.child, "pid", None)
        return (
            state not in {"error", "stopped"}
            and (child_pid is None or int(child_pid) == pid)
            and self.process_is_alive(pid)
            and self.clock() - last_tick < self.config.heartbeat_stale_after
        )

    def restart_delay(self, failures: int) -> float:
        return min(self.config.max_restart_backoff, self.config.restart_backoff * (2 ** max(0, int(failures))))

    def launch(self):
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        source_root = Path(__file__).resolve().parents[2]
        environment["PYTHONPATH"] = str(source_root) + os.pathsep + environment.get("PYTHONPATH", "")
        environment.setdefault("SOPHYANE_RSI_MAX_ITERATIONS", "1000000")
        environment.setdefault("SOPHYANE_RSI_MAX_WALL_SECONDS", "31536000")
        environment.setdefault("SOPHYANE_RSI_MAX_REPOSITORIES", "1000000")
        log_path = self.config.state_dir / "rsi.log"
        log = log_path.open("a", encoding="utf-8")
        try:
            self.child = self.popen(
                [
                    sys.executable,
                    "-m",
                    "sophyane.rsi_terminal",
                    "--daemon",
                    "--state-dir",
                    str(self.config.state_dir),
                    "--pid-file",
                    str(self.config.state_dir / "rsi-child.pid"),
                    "--socket-path",
                    str(self.config.socket_path),
                ],
                cwd=str(source_root),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        finally:
            log.close()
        return self.child

    def write_pid(self) -> None:
        self.config.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def write_status(self, state: str) -> None:
        status = {
            "state": state,
            "pid": os.getpid(),
            "child_pid": getattr(self.child, "pid", None),
            "restart_count": self.restart_count,
            "last_error": self.last_error,
            "updated_at": self.clock(),
        }
        path = self.config.state_dir / "external-watchdog.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, sort_keys=True) + "\n", encoding="utf-8")

@contextmanager
def foreground_work():
    global _active, _last_activity
    with _lock:
        _active += 1
        _last_activity = time.monotonic()
    try:
        yield
    finally:
        with _lock:
            _active -= 1
            _last_activity = time.monotonic()

def foreground(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with foreground_work():
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                autonomous_bus.submit(ImprovementObservation(ImprovementSource.RUNTIME,
                    type(error).__name__ + ': ' + str(error)[:1000], function.__module__,
                    (function.__qualname__,)))
                raise
            if isinstance(result, tuple) and result and result[0] is False:
                autonomous_bus.submit(ImprovementObservation(ImprovementSource.RUNTIME,
                    str(result[1])[:1000], function.__module__, (function.__qualname__,)))
            # SOPHYANE_RSI_STRUCTURED_UNRESOLVED_V1
            if getattr(result, "execution_failed", False) is True:
                diagnostic_evidence = tuple(
                    getattr(result, "execution_failure_evidence", ())
                )
                autonomous_bus.submit(ImprovementObservation(
                    ImprovementSource.RUNTIME,
                    "Bounded execution ended without a verified outcome",
                    function.__module__,
                    (function.__qualname__,) + diagnostic_evidence,
                ))
            return result
    return wrapped

def default_controller(state_dir):
    from .runtime_services import build_controller
    def active():
        with _lock:
            return bool(_active) or time.monotonic() - _last_activity < 30
    return build_controller(state_dir, active=active)

def start_supervisor(*, controller=None, state_dir=None):
    global _instance
    if os.environ.get('SOPHYANE_AUTONOMOUS_RSI', '1').strip() == '0':
        return None
    with _lock:
        if _instance and _instance.thread.is_alive():
            return _instance
        root = Path(state_dir or os.environ.get('SOPHYANE_AUTONOMOUS_RSI_STATE',
                    Path.home() / '.local/state/sophyane/autonomous-rsi'))
        try:
            import fcntl
            root.mkdir(parents=True, exist_ok=True)
            handle = (root / 'supervisor.lock').open('a+')
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                return None
        except (ImportError, OSError):
            return None  # Cannot prove singleton ownership on this platform.
        stop, wake = threading.Event(), threading.Event()
        def run():
            try:
                selected = controller if controller is not None else default_controller(root)
                if controller is not None:
                    selected.run(stop_event=stop)
                else:
                    curriculum = None
                    if os.environ.get('SOPHYANE_CONTINUOUS_RSI', '1').strip() == '1':
                        from .runtime_services import build_curriculum_runtime
                        from .heartbeat_runtime import ContinuousRSIWorker, RSIWatchdog
                        curriculum = build_curriculum_runtime(root, selected)
                        curriculum.start()
                        worker = ContinuousRSIWorker(
                            curriculum,
                            curriculum.heartbeat,
                            curriculum.task_source,
                            context_factory=curriculum.context_factory,
                        )
                        watchdog = RSIWatchdog(
                            curriculum.heartbeat,
                            worker.run_once,
                            curriculum.scheduler,
                            curriculum.stale_seconds,
                        ) if curriculum.watchdog_enabled else None
                    while not stop.is_set():
                        started = time.monotonic()
                        try:
                            if curriculum is None:
                                selected.tick()
                            elif watchdog is not None and watchdog.check().get('status') == 'error':
                                worker.run_once()
                            elif worker.run_once().get('status') == 'idle':
                                selected.tick()
                        except Exception:
                            pass  # Background diagnostics must not crash foreground runtime.
                        interval = getattr(curriculum, 'heartbeat_interval', 30) if curriculum else 30
                        wake.wait(max(0.5, interval - (time.monotonic() - started)))
                        wake.clear()
                        # Wake storms may not turn into an unbounded busy loop.
                        stop.wait(max(0, 1 - (time.monotonic() - started)))
            finally:
                if 'selected' in locals() and getattr(selected, 'candidate', None):
                    selected.candidate.close()
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
        thread = threading.Thread(target=run, name='sophyane-autonomous-rsi', daemon=True)
        _instance = Supervisor(thread, stop, wake)
        autonomous_bus.wake = wake.set
        thread.start()
        return _instance

def stop_supervisor(timeout=2):
    global _instance
    with _lock:
        current = _instance
        if current:
            current.stop_event.set()
            current.wake_event.set()
    if current and current.thread is not threading.current_thread():
        current.thread.join(max(0, min(timeout, 5)))
    with _lock:
        if current and not current.thread.is_alive() and _instance is current:
            _instance = None
            autonomous_bus.wake = lambda: None


def start_continuous_curriculum(runtime, *, interval=30.0):
    """Start an opt-in durable curriculum loop around a runtime adapter."""
    global _curriculum_instance
    if not runtime.enabled or not runtime.start():
        return None
    from .heartbeat_runtime import ContinuousRSIWorker, RSIWatchdog
    worker = getattr(runtime, "worker", None)
    if worker is None and hasattr(runtime, "heartbeat"):
        worker = ContinuousRSIWorker(
            runtime,
            runtime.heartbeat,
            getattr(runtime, "task_source", None),
            context_factory=getattr(runtime, "context_factory", None),
        )
        runtime.worker = worker
    watchdog = None
    if worker is not None and getattr(runtime, "watchdog_enabled", False):
        watchdog = RSIWatchdog(
            runtime.heartbeat,
            worker.run_once,
            runtime.scheduler,
            getattr(runtime, "stale_seconds", max(2.0, float(interval) * 2)),
        )
    with _lock:
        if _curriculum_instance and _curriculum_instance.thread.is_alive():
            return _curriculum_instance
        stop = threading.Event()

        def run():
            while not stop.is_set():
                try:
                    if watchdog is not None:
                        watchdog.check()
                    if worker is not None:
                        worker.run_once()
                    else:
                        runtime.tick()
                except Exception:
                    pass
                stop.wait(max(0.1, float(interval)))

        thread = threading.Thread(target=run, name="sophyane-continuous-rsi", daemon=True)
        _curriculum_instance = Supervisor(thread, stop, stop)
        thread.start()
        return _curriculum_instance


def stop_continuous_curriculum(timeout=2):
    global _curriculum_instance
    with _lock:
        current = _curriculum_instance
        if current:
            current.stop_event.set()
            current.wake_event.set()
    if current and current.thread is not threading.current_thread():
        current.thread.join(max(0, min(timeout, 5)))
    with _lock:
        if current and not current.thread.is_alive() and _curriculum_instance is current:
            _curriculum_instance = None

atexit.register(stop_supervisor)

_runtime_depth = 0

def runtime_session(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        global _runtime_depth
        with _lock:
            outer = _runtime_depth == 0
            _runtime_depth += 1
        try:
            if outer:
                start_supervisor()
            return function(*args, **kwargs)
        finally:
            with _lock:
                _runtime_depth -= 1
            if outer:
                stop_supervisor()
    return wrapped


def _external_lock(path: Path):
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError(f"external RSI watchdog already owns {path}")
    return handle


def _daemonize() -> None:
    pid = os.fork()
    if pid:
        raise SystemExit(0)
    os.setsid()
    pid = os.fork()
    if pid:
        raise SystemExit(0)
    os.chdir("/")
    with open(os.devnull, "r") as stdin, open(os.devnull, "a") as stdout, open(os.devnull, "a") as stderr:
        os.dup2(stdin.fileno(), 0)
        os.dup2(stdout.fileno(), 1)
        os.dup2(stderr.fileno(), 2)


def run_external_watchdog(args) -> int:
    config = ExternalWatchdogConfig(
        state_dir=Path(args.state_dir),
        pid_file=Path(args.pid_file),
        socket_path=Path(args.socket_path),
        heartbeat_interval=float(args.heartbeat_interval),
        heartbeat_stale_after=float(args.heartbeat_stale_after),
        daemonize=bool(args.daemonize),
        wakelock=bool(args.wakelock),
        watchdog_mode=args.watchdog_mode,
    )
    if config.daemonize:
        _daemonize()
    lock = _external_lock(config.pid_file.with_suffix(config.pid_file.suffix + ".lock"))
    watchdog = ExternalWatchdog(config)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    wakelock_held = acquire_wakelock(config.wakelock)
    try:
        watchdog.recover_stale_artifacts()
        from ..v13_cli import run_curriculum_command
        run_curriculum_command(
            "start",
            config.state_dir,
            max_iterations=1_000_000,
            max_wall_seconds=31_536_000,
            cooldown_seconds=30,
        )
        watchdog.write_pid()
        watchdog.write_status("starting")
        if args.once:
            watchdog.write_status("checked")
            return 0
        watchdog.launch()
        startup_deadline = time.monotonic() + max(15.0, config.heartbeat_stale_after)
        watchdog.write_status("running")
        while not stop.wait(config.heartbeat_interval):
            child = watchdog.child
            if child is None:
                watchdog.launch()
                continue
            exit_code = child.poll()
            heartbeat_exists = (config.state_dir / "heartbeat.json").exists()
            healthy = watchdog.heartbeat_healthy()
            if exit_code is None and (healthy or (not heartbeat_exists and time.monotonic() < startup_deadline)):
                watchdog.write_status("running")
                continue
            if exit_code is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
                watchdog.last_error = "stale RSI heartbeat"
            else:
                watchdog.last_error = f"RSI daemon exited with code {exit_code}"
            watchdog.restart_count += 1
            watchdog.write_status("backoff")
            if stop.wait(watchdog.restart_delay(watchdog.restart_count - 1)):
                break
            watchdog.launch()
            startup_deadline = time.monotonic() + max(15.0, config.heartbeat_stale_after)
    finally:
        child = watchdog.child
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
        if config.pid_file.exists():
            try:
                if int(config.pid_file.read_text(encoding="utf-8").strip()) == os.getpid():
                    config.pid_file.unlink()
            except (OSError, ValueError):
                pass
        release_wakelock(wakelock_held)
        try:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        finally:
            lock.close()
    return 0


def main(argv=None) -> int:
    args = parse_external_args(argv)
    if args.status:
        print(json.dumps(status_external_watchdog(args), sort_keys=True))
        return 0
    return run_external_watchdog(args)


if __name__ == "__main__":
    raise SystemExit(main())
