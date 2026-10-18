"""Termux daemon and HITL control channel for continuous RSI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

from .rsi.observation_bus import ImprovementObservation, ImprovementSource, autonomous_bus
from .v13_cli import run_curriculum_command


def socket_path(state_dir: Path) -> Path:
    return Path(state_dir) / "rsi.sock"


def handle_command(command: str, state_dir: Path) -> str:
    command = str(command).strip()
    if command == "status":
        return json.dumps(run_curriculum_command("status", state_dir), sort_keys=True)
    if command == "pause":
        return json.dumps(run_curriculum_command("pause", state_dir), sort_keys=True)
    if command == "stop":
        result = run_curriculum_command("stop", state_dir)
        return json.dumps(result, sort_keys=True)
    if command.startswith("instruction "):
        text = command[len("instruction "):].strip()
        if not text:
            return "instruction rejected: empty"
        accepted = autonomous_bus.submit(
            ImprovementObservation(
                ImprovementSource.USER_FRICTION,
                text[:2000],
                "termux-hitl",
                ("human instruction",),
            )
        )
        return "instruction accepted for bounded RSI analysis" if accepted else "instruction deferred: observation queue full"
    if command in {"help", "?"}:
        return "status | pause | stop | instruction <bounded improvement request>"
    return "unknown command; use help"


def _serve(state_dir: Path) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    runtime_source_root = Path(__file__).resolve().parents[2]
    current_commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=runtime_source_root,
        capture_output=True,
        text=True,
        check=False,
    )
    current_commit = current_commit_result.stdout.strip()
    sock_path = socket_path(state_dir)
    if sock_path.exists():
        sock_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(4)
    server.settimeout(0.5)
    (state_dir / "rsi.pid").write_text(str(os.getpid()), encoding="utf-8")
    from .rsi.heartbeat import HeartbeatRecord, HeartbeatStore
    heartbeat = HeartbeatStore(state_dir / "heartbeat.json")
    now = time.time()
    heartbeat.save(HeartbeatRecord(f"rsi-{os.getpid()}", os.getpid(), "starting", now, now))
    from .rsi.heartbeat_runtime import ContinuousRSIWorker, RSIWatchdog
    from .rsi.runtime_services import build_controller, build_curriculum_runtime
    # The daemon is a background worker. Treating it as user-active forces the
    # resource governor into OBSERVE_ONLY forever and prevents queued tasks
    # from progressing.
    controller = build_controller(state_dir, active=lambda: False)
    runtime = build_curriculum_runtime(state_dir, controller)
    runtime.start()
    worker = ContinuousRSIWorker(
        runtime,
        runtime.heartbeat,
        runtime.task_source,
        context_factory=runtime.context_factory,
    )
    watchdog = RSIWatchdog(
        runtime.heartbeat,
        worker.run_once,
        runtime.scheduler,
        runtime.stale_seconds,
    ) if runtime.watchdog_enabled else None
    stop_event = threading.Event()

    def pulse_heartbeat():
        while not stop_event.is_set():
            try:
                runtime.heartbeat.touch(
                    state="running",
                    last_tick_at=time.time(),
                )
            except Exception:
                pass
            stop_event.wait(min(1.0, runtime.heartbeat_interval))

    def run_worker():
        while not stop_event.is_set():
            try:
                if watchdog is not None:
                    watchdog.check()
                result = worker.run_once()
                if result.get("status") == "verified" and needs_live_relaunch(state_dir, current_commit):
                    live_root = runtime_root(state_dir)
                    environment = os.environ.copy()
                    environment["PYTHONPATH"] = str(live_root / "src") + os.pathsep + environment.get("PYTHONPATH", "")
                    os.chdir(live_root)
                    os.execve(
                        sys.executable,
                        [sys.executable, "-m", "sophyane.rsi_terminal", "--daemon", "--state-dir", str(state_dir)],
                        environment,
                    )
                if result.get("status") == "idle" and runtime.status().get("queue_length", 0) == 0:
                    controller.tick()
            except Exception as error:
                try:
                    runtime.heartbeat.touch(state="error", last_error=str(error)[:1000])
                except Exception:
                    pass
            stop_event.wait(runtime.heartbeat_interval)

    worker_thread = threading.Thread(target=run_worker, name="sophyane-rsi-worker", daemon=True)
    heartbeat_thread = threading.Thread(target=pulse_heartbeat, name="sophyane-rsi-heartbeat", daemon=True)
    heartbeat_thread.start()
    worker_thread.start()
    try:
        while True:
            try:
                connection, _ = server.accept()
            except socket.timeout:
                status = json.loads(handle_command("status", state_dir))
                if status.get("stopped"):
                    break
                connection = None
            if connection is not None:
                with connection:
                    command = connection.recv(8192).decode("utf-8", "replace")
                    reply = handle_command(command, state_dir)
                    try:
                        connection.sendall(reply.encode("utf-8"))
                    except BrokenPipeError:
                        pass
                    if command.strip() == "stop":
                        break
    finally:
        stop_event.set()
        worker_thread.join(timeout=2.0)
        heartbeat_thread.join(timeout=2.0)
        if getattr(controller, "candidate", None):
            controller.candidate.close()
        server.close()
        if sock_path.exists():
            sock_path.unlink()
        (state_dir / "rsi.pid").unlink(missing_ok=True)
    return 0


def _request(state_dir: Path, command: str) -> str:
    path = socket_path(state_dir)
    if not path.exists():
        return handle_command(command, state_dir)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(5)
        client.connect(str(path))
        client.sendall(command.encode("utf-8"))
        return client.recv(16384).decode("utf-8", "replace")
    finally:
        client.close()


def _default_state_dir() -> Path:
    return Path(os.environ.get("SOPHYANE_RSI_STATE", Path.home() / ".local/state/sophyane/continuous-rsi"))


def runtime_root(state_dir: Path) -> Path:
    live = Path(state_dir) / "live-worktree"
    promotion = Path(state_dir) / "promotion.json"
    if live.is_dir() and promotion.is_file():
        try:
            if bool(json.loads(promotion.read_text(encoding="utf-8")).get("promoted")):
                return live
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    return Path(__file__).resolve().parents[2]


def needs_live_relaunch(state_dir: Path, current_commit: str) -> bool:
    try:
        payload = json.loads((Path(state_dir) / "promotion.json").read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    active = str(payload.get("active_commit") or "")
    return bool(payload.get("promoted")) and bool(active) and active != str(current_commit)


def start(state_dir: Path | None = None) -> int:
    state_dir = Path(state_dir or _default_state_dir())
    state_dir.mkdir(parents=True, exist_ok=True)
    run_curriculum_command("start", state_dir)
    pid_path = state_dir / "rsi.pid"
    if pid_path.exists():
        try:
            os.kill(int(pid_path.read_text()), 0)
            print("Sophyane RSI is already running")
            return 0
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)
    log = (state_dir / "rsi.log").open("a", encoding="utf-8")
    root = runtime_root(state_dir)
    environment = os.environ.copy()
    source_root = str(root / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    subprocess.Popen(
        [sys.executable, "-m", "sophyane.rsi_terminal", "--daemon", "--state-dir", str(state_dir)],
        cwd=str(root),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    print(f"Sophyane RSI started; state: {state_dir}")
    return 0


def cli_start() -> int:
    return start()


def cli_stop() -> int:
    print(_request(_default_state_dir(), "stop"))
    return 0


def cli_status() -> int:
    print(_request(_default_state_dir(), "status"))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sophyane-rsi")
    parser.add_argument("command", nargs="?", default="shell", choices=("start", "stop", "status", "shell"))
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--state-dir", default=str(Path.home() / ".local/state/sophyane/continuous-rsi"))
    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir)
    if args.daemon:
        return _serve(state_dir)
    if args.command == "start":
        return start(state_dir)
    if args.command == "stop":
        print(_request(state_dir, "stop"))
        return 0
    if args.command == "status":
        print(_request(state_dir, "status"))
        return 0
    while True:
        try:
            line = input("sophyane-rsi> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.strip() in {"exit", "quit"}:
            return 0
        print(_request(state_dir, line if line.startswith(("instruction ", "status", "pause", "stop", "help")) else "instruction " + line))


if __name__ == "__main__":
    raise SystemExit(main())
