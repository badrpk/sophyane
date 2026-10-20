"""Termux daemon and HITL control channel for continuous RSI."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import sqlite3
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
        return json.dumps({**_curriculum_command("status", state_dir), **_multi_repo_status(state_dir)}, sort_keys=True)
    if command == "pause":
        return json.dumps(_curriculum_command("pause", state_dir), sort_keys=True)
    if command == "stop":
        result = _curriculum_command("stop", state_dir)
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


def _curriculum_command(command: str, state_dir: Path) -> dict[str, object]:
    """Apply a lifecycle command using the daemon's configured budgets."""
    return run_curriculum_command(
        command,
        state_dir,
        max_iterations=max(1, int(os.environ.get("SOPHYANE_RSI_MAX_ITERATIONS", "100"))),
        max_wall_seconds=max(1.0, float(os.environ.get("SOPHYANE_RSI_MAX_WALL_SECONDS", "86400"))),
        cooldown_seconds=max(0.0, float(os.environ.get("SOPHYANE_RSI_COOLDOWN_SECONDS", "30"))),
    )


def multi_repo_mode() -> str:
    """Require an explicit execute opt-in; invalid modes fail closed."""
    mode = os.environ.get("SOPHYANE_RSI_MULTI_REPO_MODE", "inventory").strip().lower()
    if mode not in {"inventory", "proposal", "execute"}:
        raise ValueError("SOPHYANE_RSI_MULTI_REPO_MODE must be inventory, proposal, or execute")
    return mode


def _positive_budget(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _multi_repo_status(state_dir: Path) -> dict[str, object]:
    state_dir = Path(state_dir)
    cursor: dict[str, object] = {"next_index": 0, "scanned_commits": {}}
    inventory_path = state_dir / "repository-inventory.json"
    if inventory_path.is_file():
        try:
            cursor = json.loads(inventory_path.read_text(encoding="utf-8")).get("cursor", cursor)
        except (OSError, ValueError, TypeError):
            cursor = {"error": "repository inventory unreadable"}
    last_scan: dict[str, object] = {}
    events_path = state_dir / "curriculum.events.jsonl"
    if events_path.is_file():
        try:
            with events_path.open(encoding="utf-8") as events:
                for line in events:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("event") == "repository_scan":
                        last_scan = event
        except OSError:
            pass
    current_task_id = None
    current_repository = last_scan.get("repository_id")
    try:
        from .rsi.curriculum import CurriculumStore, TaskStatus
        state = CurriculumStore(state_dir / "curriculum.json").load()
        current_task_id = state.current_task_id
        active = next((task for task in state.queue if task.task_id == current_task_id), None)
        if active is None:
            active = next((task for task in state.queue if task.status in {TaskStatus.QUEUED, TaskStatus.PAUSED}), None)
        if active is not None:
            current_task_id = active.task_id
            current_repository = active.repository_id or current_repository
    except ValueError:
        pass
    return {
        "mode": multi_repo_mode(),
        "repository_cursor": cursor,
        "current_repository": current_repository,
        "current_task_id": current_task_id,
        "last_review_outcome": last_scan.get("review_outcome"),
    }


def _failure_boundary(error: Exception) -> str:
    message = str(error).lower()
    if isinstance(error, SyntaxError) or "ast" in message or "parser" in message:
        return "ast_parser"
    if isinstance(error, sqlite3.Error) or "database is locked" in message or "sqlite" in message:
        return "sqlite_state"
    if "git" in message or "commit" in message or "hash" in message:
        return "git_inventory"
    if "symlink" in message or "path" in message or "workspace" in message:
        return "workspace_containment"
    return "daemon_cycle"


def _pause_after_failure(runtime, error: Exception) -> dict[str, object]:
    boundary = _failure_boundary(error)
    reason = f"{boundary}: {type(error).__name__}: {error}"
    try:
        runtime.scheduler.pause(reason)
    except Exception:
        # A locked/corrupt state store may prevent the normal pause write.
        # Preserve the failure boundary in the append-only audit channel when
        # that channel remains available, while still failing closed.
        try:
            runtime.scheduler.store.append_event({"event": "chaos_failure", "boundary": boundary, "reason": reason})
        except Exception:
            pass
    return {"status": "paused", "reason": reason}


def run_multi_repo_cycle(runtime, mode: str, *, max_files: int) -> dict[str, object]:
    try:
        return _run_multi_repo_cycle(runtime, mode, max_files=max_files)
    except Exception as error:
        return _pause_after_failure(runtime, error)


def _task_paths_safe(record, task) -> bool:
    root = Path(record.path).resolve()
    for relative in task.editable_paths:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        current = root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                return False
    return True


def _run_multi_repo_cycle(runtime, mode: str, *, max_files: int) -> dict[str, object]:
    """Perform at most one durable scan, proposal, or bounded execution step."""
    if mode not in {"inventory", "proposal", "execute"} or max_files < 1:
        raise ValueError("invalid multi-repository rollout controls")
    status = runtime.scheduler.status()
    if status.get("stopped"):
        return {"status": "stopped"}
    if status.get("paused"):
        return {"status": "paused"}
    inventory = runtime.repository_inventory
    if mode == "execute" and status.get("queue_length", 0):
        if runtime.task_source is None:
            reason = "proposal provider unavailable"
            runtime.scheduler.pause(reason)
            return {"status": "paused", "reason": reason}
        task = runtime.scheduler.choose_next(runtime.scheduler.store.load().queue)
        inventory.refresh()
        record = next((item for item in inventory.records if task is not None and item.repo_id == task.repository_id), None)
        if task is None or record is None or not task.base_commit or task.base_commit != record.commit:
            reason = "queued task repository unavailable or stale"
            runtime.scheduler.pause(reason)
            return {"status": "paused", "reason": reason}
        if len(task.editable_paths) > max_files:
            reason = "queued task exceeds file budget"
            runtime.scheduler.pause(reason)
            return {"status": "paused", "reason": reason}
        result = runtime.tick()
        if result.get("status") == "paused":
            runtime.scheduler.pause(str(result.get("reason", "unsafe task state")))
        return result
    record = inventory.next_repository()
    if record is None:
        return {"status": "idle"}

    def finish(outcome: str, *, task_id: str = "", review_outcome: str = "") -> None:
        runtime.scheduler.store.append_event({
            "event": "repository_scan", "repository_id": record.repo_id,
            "commit": record.commit, "task_id": task_id,
            "outcome": outcome, "review_outcome": review_outcome,
        })
        inventory.complete_scan(record)

    if mode == "inventory":
        finish("inventoried")
        return {"status": "inventoried", "repository_id": record.repo_id}
    if runtime.task_source is None:
        runtime.scheduler.pause("proposal provider unavailable")
        return {"status": "paused", "reason": "proposal provider unavailable"}
    context = runtime.context_factory()
    if context is None or context.repository_id != record.repo_id or context.base_commit != record.commit:
        runtime.scheduler.pause("repository context unavailable or stale")
        return {"status": "paused", "reason": "repository context unavailable or stale"}
    context = replace(context, allowed_paths=context.allowed_paths[:max_files])
    if not context.allowed_paths:
        finish("skipped", review_outcome="no editable files")
        return {"status": "skipped", "repository_id": record.repo_id}
    proposal = runtime.task_source.propose(context)
    if not proposal.accepted or proposal.task is None:
        reason = str(proposal.reason or "proposal rejected")
        if "provider" in reason.lower() or "unavailable" in reason.lower():
            runtime.scheduler.pause(reason)
            return {"status": "paused", "reason": reason}
        finish("rejected", review_outcome=proposal.review_outcome or reason)
        return {"status": "rejected", "repository_id": record.repo_id, "reason": reason}
    task = proposal.task
    if (task.repository_id != record.repo_id or task.base_commit != record.commit
            or len(task.editable_paths) > max_files or not _task_paths_safe(record, task)):
        reason = "proposal exceeds repository, file, or symlink containment policy"
        runtime.scheduler.pause(reason)
        return {"status": "paused", "reason": reason}
    if not runtime.scheduler.enqueue(task):
        runtime.scheduler.pause("scheduler rejected proposed task")
        return {"status": "paused", "reason": "scheduler rejected proposed task"}
    if mode == "proposal":
        finish("proposed", task_id=task.task_id, review_outcome=proposal.review_outcome or "unreviewed")
        return {"status": "proposed", "repository_id": record.repo_id, "task_id": task.task_id}
    result = runtime.tick()
    finish(str(result.get("status", "unknown")), task_id=task.task_id,
           review_outcome=proposal.review_outcome or "unreviewed")
    if result.get("status") == "paused":
        runtime.scheduler.pause(str(result.get("reason", "unsafe task state")))
    return {**result, "repository_id": record.repo_id}


def _serve(state_dir: Path) -> int:
    mode = multi_repo_mode()
    max_repositories = _positive_budget("SOPHYANE_RSI_MAX_REPOSITORIES", 8)
    max_files = _positive_budget("SOPHYANE_RSI_MAX_FILES_PER_SCAN", 8)
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
    from .rsi.heartbeat_runtime import RSIWatchdog
    from .rsi.runtime_services import build_controller, build_curriculum_runtime
    # The daemon is a background worker. Treating it as user-active forces the
    # resource governor into OBSERVE_ONLY forever and prevents queued tasks
    # from progressing.
    controller = build_controller(state_dir, active=lambda: False)
    runtime = build_curriculum_runtime(state_dir, controller)
    runtime.start()
    def run_cycle():
        return run_multi_repo_cycle(runtime, mode, max_files=max_files)

    watchdog = RSIWatchdog(
        runtime.heartbeat,
        run_cycle,
        runtime.scheduler,
        runtime.stale_seconds,
    ) if runtime.watchdog_enabled else None
    stop_event = threading.Event()
    scans = 0

    def pulse_heartbeat():
        while not stop_event.is_set():
            try:
                status = runtime.status()
                runtime.heartbeat.touch(
                    state="stopped" if status.get("stopped") else "paused" if status.get("paused") else "running",
                    last_tick_at=time.time(),
                    current_task_id=status.get("current_task_id"),
                )
            except Exception:
                pass
            stop_event.wait(min(1.0, runtime.heartbeat_interval))

    def run_worker():
        nonlocal scans
        while not stop_event.is_set():
            try:
                if watchdog is not None:
                    watchdog.check()
                result = run_cycle()
                if result.get("status") not in {"idle", "paused", "stopped"}:
                    scans += 1
                    if scans >= max_repositories:
                        runtime.scheduler.pause("repository scan budget exhausted")
                if mode == "execute" and result.get("status") == "verified" and needs_live_relaunch(state_dir, current_commit):
                    live_root = runtime_root(state_dir)
                    environment = os.environ.copy()
                    environment["PYTHONPATH"] = str(live_root / "src") + os.pathsep + environment.get("PYTHONPATH", "")
                    os.chdir(live_root)
                    os.execve(
                        sys.executable,
                        [sys.executable, "-m", "sophyane.rsi_terminal", "--daemon", "--state-dir", str(state_dir)],
                        environment,
                    )
                if mode == "execute" and result.get("status") == "idle" and runtime.status().get("queue_length", 0) == 0:
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
    _curriculum_command("start", state_dir)
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
