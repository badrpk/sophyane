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
    sock_path = socket_path(state_dir)
    if sock_path.exists():
        sock_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(4)
    server.settimeout(0.5)
    (state_dir / "rsi.pid").write_text(str(os.getpid()), encoding="utf-8")
    from .rsi.supervisor import start_supervisor, stop_supervisor
    start_supervisor(state_dir=state_dir)
    try:
        while True:
            try:
                connection, _ = server.accept()
            except socket.timeout:
                status = json.loads(handle_command("status", state_dir))
                if status.get("stopped"):
                    break
                continue
            with connection:
                command = connection.recv(8192).decode("utf-8", "replace")
                reply = handle_command(command, state_dir)
                connection.sendall(reply.encode("utf-8"))
                if command.strip() == "stop":
                    break
    finally:
        stop_supervisor()
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


def start(state_dir: Path | None = None) -> int:
    state_dir = Path(state_dir or _default_state_dir())
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_path = state_dir / "rsi.pid"
    if pid_path.exists():
        try:
            os.kill(int(pid_path.read_text()), 0)
            print("Sophyane RSI is already running")
            return 0
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)
    log = (state_dir / "rsi.log").open("a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "-m", "sophyane.rsi_terminal", "--daemon", "--state-dir", str(state_dir)],
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
