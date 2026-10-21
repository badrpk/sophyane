from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sophyane.rsi.heartbeat import HeartbeatRecord
from sophyane.rsi.supervisor import (
    ExternalWatchdog,
    ExternalWatchdogConfig,
    acquire_wakelock,
    parse_external_args,
    run_external_watchdog,
    status_external_watchdog,
)


def test_external_cli_parses_requested_contract(tmp_path: Path):
    args = parse_external_args(
        [
            "--daemonize",
            "--heartbeat-interval=5",
            f"--pid-file={tmp_path / 'rsi.pid'}",
            f"--socket-path={tmp_path / 'rsi.sock'}",
            "--watchdog-mode=external",
            "--wakelock",
        ]
    )

    assert args.daemonize is True
    assert args.heartbeat_interval == 5.0
    assert args.pid_file == tmp_path / "rsi.pid"
    assert args.socket_path == tmp_path / "rsi.sock"
    assert args.watchdog_mode == "external"
    assert args.wakelock is True


def test_external_cli_rejects_other_watchdog_modes():
    with pytest.raises(SystemExit):
        parse_external_args(["--watchdog-mode=internal"])


def test_external_cli_defaults_to_external_mode():
    args = parse_external_args([])
    assert args.watchdog_mode == "external"


def test_stale_pid_and_socket_are_removed_but_live_unrelated_pid_is_protected(tmp_path: Path):
    config = ExternalWatchdogConfig(
        state_dir=tmp_path,
        pid_file=tmp_path / "rsi.pid",
        socket_path=tmp_path / "rsi.sock",
    )
    watchdog = ExternalWatchdog(config, process_is_alive=lambda pid: False)
    config.pid_file.write_text("999999", encoding="utf-8")
    config.socket_path.write_text("stale", encoding="utf-8")

    watchdog.recover_stale_artifacts()

    assert not config.pid_file.exists()
    assert not config.socket_path.exists()

    config.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    protected = ExternalWatchdog(config, process_is_alive=lambda pid: True)
    with pytest.raises(RuntimeError, match="already running"):
        protected.recover_stale_artifacts()
    assert config.pid_file.read_text(encoding="utf-8") == str(os.getpid())


def test_heartbeat_health_requires_matching_live_pid_and_fresh_timestamp(tmp_path: Path):
    config = ExternalWatchdogConfig(
        state_dir=tmp_path,
        pid_file=tmp_path / "rsi.pid",
        socket_path=tmp_path / "rsi.sock",
        heartbeat_stale_after=10,
    )
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(
        json.dumps(
            {
                "worker_id": "rsi-42",
                "pid": 42,
                "state": "running",
                "started_at": 90,
                "last_tick_at": 95,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    watchdog = ExternalWatchdog(
        config,
        process_is_alive=lambda pid: pid == 42,
        clock=lambda: 100,
    )
    assert watchdog.heartbeat_healthy() is True

    heartbeat.write_text(
        heartbeat.read_text(encoding="utf-8").replace("\"pid\": 42", "\"pid\": 41"),
        encoding="utf-8",
    )
    assert watchdog.heartbeat_healthy() is False


def test_heartbeat_health_rejects_a_different_live_child_pid(tmp_path: Path):
    config = ExternalWatchdogConfig(
        state_dir=tmp_path,
        pid_file=tmp_path / "rsi.pid",
        socket_path=tmp_path / "rsi.sock",
        heartbeat_stale_after=10,
    )
    (tmp_path / "heartbeat.json").write_text(
        json.dumps(
            {
                "worker_id": "rsi-42",
                "pid": 42,
                "state": "running",
                "started_at": 90,
                "last_tick_at": 95,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    class Child:
        pid = 43

    watchdog = ExternalWatchdog(
        config,
        process_is_alive=lambda pid: True,
        clock=lambda: 100,
    )
    watchdog.child = Child()
    assert watchdog.heartbeat_healthy() is False


def test_restart_delay_is_bounded_exponential():
    config = ExternalWatchdogConfig(
        state_dir=Path("."),
        pid_file=Path("rsi.pid"),
        socket_path=Path("rsi.sock"),
        restart_backoff=2,
        max_restart_backoff=10,
    )
    watchdog = ExternalWatchdog(config)
    assert [watchdog.restart_delay(i) for i in range(5)] == [2, 4, 8, 10, 10]


def test_launch_preserves_explicit_environment_and_raises_default_continuous_budgets(tmp_path: Path, monkeypatch):
    config = ExternalWatchdogConfig(
        state_dir=tmp_path,
        pid_file=tmp_path / "rsi.pid",
        socket_path=tmp_path / "rsi.sock",
    )
    captured = {}

    class Child:
        pid = 44

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return Child()

    monkeypatch.delenv("SOPHYANE_RSI_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("SOPHYANE_RSI_MAX_REPOSITORIES", raising=False)
    watchdog = ExternalWatchdog(config, popen=fake_popen)
    watchdog.launch()

    assert captured["env"]["SOPHYANE_RSI_MAX_ITERATIONS"] == "1000000"
    assert captured["env"]["SOPHYANE_RSI_MAX_REPOSITORIES"] == "1000000"
    assert "--pid-file" in captured["command"]
    assert str(tmp_path / "rsi-child.pid") in captured["command"]


def test_missing_termux_wakelock_is_nonfatal(monkeypatch):
    monkeypatch.setattr("sophyane.rsi.supervisor.shutil.which", lambda name: None)
    assert acquire_wakelock(True) is False
    assert acquire_wakelock(False) is False


def test_one_shot_resume_path_starts_without_import_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sophyane.v13_cli.run_curriculum_command", lambda *args, **kwargs: {})
    args = parse_external_args(
        [
            "--watchdog-mode=external",
            "--once",
            f"--pid-file={tmp_path / 'watchdog.pid'}",
            f"--socket-path={tmp_path / 'rsi.sock'}",
            f"--state-dir={tmp_path / 'state'}",
        ]
    )

    assert run_external_watchdog(args) == 0


def test_status_command_is_read_only_and_does_not_require_watchdog_mode(tmp_path: Path):
    (tmp_path / "external-rsi.pid").write_text("999999", encoding="utf-8")
    (tmp_path / "external-watchdog.json").write_text(
        json.dumps({"state": "running", "pid": 999999, "child_pid": 888888}),
        encoding="utf-8",
    )
    args = parse_external_args(
        ["--status", f"--pid-file={tmp_path / 'external-rsi.pid'}", f"--socket-path={tmp_path / 'rsi.sock'}"]
    )

    result = status_external_watchdog(args)

    assert result["supervisor_alive"] is False
    assert result["child_alive"] is False
    assert (tmp_path / "external-rsi.pid").exists()
