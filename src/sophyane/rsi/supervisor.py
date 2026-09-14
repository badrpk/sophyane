"""Default-on daemon lifecycle with thread and process ownership locks."""
import atexit
from contextlib import contextmanager
from dataclasses import dataclass, replace
from functools import wraps
import os
from pathlib import Path
import threading
import time

from .observation_bus import autonomous_bus, ImprovementObservation, ImprovementSource

_lock = threading.RLock()
_instance = None
_active = 0
_last_activity = 0.0

@dataclass
class Supervisor:
    thread: threading.Thread
    stop_event: threading.Event
    wake_event: threading.Event

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
                    while not stop.is_set():
                        started = time.monotonic()
                        try:
                            selected.tick()
                        except Exception:
                            pass  # Background diagnostics must not crash foreground runtime.
                        wake.wait(max(1, 30 - (time.monotonic() - started)))
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
