from pathlib import Path
import json
import subprocess

import pytest

from sophyane.rsi.qemu_runner import (
    ExchangePaths,
    QemuRunnerConfig,
    QemuRunnerConfigurationError,
    QemuRsiRunner,
    build_qemu_command,
)


def _manifest(task_id="task-1"):
    return {
        "schema_version": 1,
        "task_id": task_id,
        "command": ["pytest", "-q"],
        "cwd": "/sophyane-input/candidate",
    }


def _guest_result(task_id="task-1", *, status="passed", exit_code=0):
    return {
        "schema_version": 1,
        "task_id": task_id,
        "status": status,
        "exit_code": exit_code,
        "stdout": "guest stdout",
        "stderr": "guest stderr",
    }


def _config(tmp_path: Path, *, enabled: bool = True, image: Path | None = None) -> QemuRunnerConfig:
    return QemuRunnerConfig(
        executable="qemu-system-aarch64",
        guest_image=image or (tmp_path / "guest.img"),
        architecture="aarch64",
        scratch_root=tmp_path / "scratch",
        timeout_seconds=30,
        max_output_bytes=4096,
        enabled=enabled,
    )


def test_build_qemu_command_is_deterministic_tcg_and_uses_separate_9p_shares(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    input_dir = config.scratch_root / "input"
    output_dir = config.scratch_root / "output"
    config.scratch_root.mkdir()
    input_dir.mkdir()
    output_dir.mkdir()
    manifest = {"task_id": "task-1", "command": ["pytest", "-q"]}

    command = build_qemu_command(config, input_dir, output_dir, manifest)

    assert command == (
        "qemu-system-aarch64",
        "-machine",
        "virt",
        "-accel",
        "tcg,thread=multi",
        "-nographic",
        "-no-reboot",
        "-drive",
        f"if=none,format=raw,readonly=on,file={config.guest_image.resolve()},id=drive0",
        "-device",
        "virtio-blk-device,drive=drive0",
        "-virtfs",
        f"local,path={input_dir},mount_tag=sophyane-input,security_model=none,readonly=on",
        "-virtfs",
        f"local,path={output_dir},mount_tag=sophyane-output,security_model=none",
    )


def test_qcow2_guest_uses_qcow2_format_and_explicit_firmware(tmp_path):
    firmware = tmp_path / "firmware.fd"
    firmware.write_bytes(b"firmware")
    image = tmp_path / "guest.qcow2"
    image.write_bytes(b"guest")
    config = QemuRunnerConfig(
        executable="qemu-system-aarch64", guest_image=image, architecture="aarch64",
        scratch_root=tmp_path / "scratch", timeout_seconds=30, max_output_bytes=4096,
        enabled=True, firmware=firmware,
    )
    config.scratch_root.mkdir()
    input_dir = config.scratch_root / "input"
    output_dir = config.scratch_root / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    command = build_qemu_command(config, input_dir, output_dir, {})

    assert "-bios" in command
    assert str(firmware) in command
    assert "if=none,format=qcow2,readonly=on,file=" + str(image.resolve()) + ",id=drive0" in command
    assert "-append" not in command


def test_disabled_runner_fails_closed_before_execution(tmp_path):
    config = _config(tmp_path, enabled=False)

    with pytest.raises(QemuRunnerConfigurationError, match="opt-in"):
        QemuRsiRunner(config).validate()


def test_missing_guest_image_fails_closed(tmp_path):
    with pytest.raises(QemuRunnerConfigurationError, match="guest image"):
        QemuRsiRunner(_config(tmp_path)).validate()


def test_directory_guest_image_is_rejected(tmp_path):
    image = tmp_path / "guest.img"
    image.mkdir()

    with pytest.raises(QemuRunnerConfigurationError, match="regular file"):
        QemuRsiRunner(_config(tmp_path, image=image)).validate()


def test_exchange_paths_must_stay_inside_scratch_root(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(QemuRunnerConfigurationError, match="scratch"):
        build_qemu_command(config, outside, config.scratch_root / "output", {})


def test_prepare_exchange_copies_candidate_read_only_and_separates_output(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "answer.py").write_text("answer = 42\n")
    runner = QemuRsiRunner(config)

    exchange = runner.prepare_exchange(candidate, _manifest())

    assert isinstance(exchange, ExchangePaths)
    assert (exchange.input_dir / "candidate" / "answer.py").read_text() == "answer = 42\n"
    assert (exchange.input_dir / "task.json").exists()
    assert exchange.input_dir != exchange.output_dir
    assert not (exchange.output_dir / "result.json").exists()
    assert not (exchange.input_dir / "candidate" / "answer.py").stat().st_mode & 0o222


def test_prepare_exchange_rejects_invalid_guest_manifest(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    with pytest.raises(QemuRunnerConfigurationError, match="manifest"):
        QemuRsiRunner(config).prepare_exchange(candidate, {**_manifest(), "task_id": ""})


def test_parse_result_rejects_missing_guest_result(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    runner = QemuRsiRunner(config)
    exchange = ExchangePaths(tmp_path / "input", tmp_path / "output", tmp_path / "output" / "result.json", "task-1")
    exchange.output_dir.mkdir()

    result = runner.parse_result(exchange, "stdout", "", 0, False)

    assert result.status == "invalid"
    assert "result.json" in result.stderr


def test_parse_result_rejects_duplicate_or_unexpected_guest_output(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    runner = QemuRsiRunner(config)
    exchange = ExchangePaths(tmp_path / "input", tmp_path / "output", tmp_path / "output" / "result.json", "task-1")
    exchange.output_dir.mkdir()
    exchange.result_path.write_text(json.dumps(_guest_result()))
    (exchange.output_dir / "result.json.tmp").write_text("partial")

    result = runner.parse_result(exchange, "stdout", "", 0, False)

    assert result.status == "invalid"
    assert "unexpected" in result.stderr or "duplicate" in result.stderr


def test_parse_result_converts_protocol_result_and_checks_task_id(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    runner = QemuRsiRunner(config)
    exchange = ExchangePaths(tmp_path / "input", tmp_path / "output", tmp_path / "output" / "result.json", "task-1")
    exchange.output_dir.mkdir()
    exchange.result_path.write_text(json.dumps(_guest_result()))

    result = runner.parse_result(exchange, "host stdout", "", 0, False)

    assert result.status == "passed"
    assert result.result == _guest_result()
    assert result.stdout == "guest stdout"

    exchange.result_path.write_text(json.dumps(_guest_result("other-task")))
    mismatch = runner.parse_result(exchange, "", "", 0, False)
    assert mismatch.status == "invalid"
    assert "task_id" in mismatch.stderr


def test_prepare_exchange_rejects_candidate_symlink_escape(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (candidate / "escape.txt").symlink_to(outside)

    with pytest.raises(QemuRunnerConfigurationError, match="symlink"):
        QemuRsiRunner(config).prepare_exchange(candidate, _manifest())


def test_parse_result_accepts_valid_guest_result(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    runner = QemuRsiRunner(config)
    exchange = ExchangePaths(tmp_path / "input", tmp_path / "output", tmp_path / "output" / "result.json")
    exchange.output_dir.mkdir()
    exchange.result_path.write_text(json.dumps(_guest_result()))

    result = runner.parse_result(exchange, "guest stdout", "", 0, False)

    assert result.status == "passed"
    assert result.result == _guest_result()
    assert result.exit_code == 0


@pytest.mark.parametrize(
    ("payload", "exit_code", "timed_out", "expected"),
    [
        ("not-json", 0, False, "invalid"),
        ('{"status":"passed"}', 1, False, "failed"),
        ('{"status":"passed"}', None, True, "timeout"),
    ],
)
def test_parse_result_rejects_invalid_guest_completion(tmp_path, payload, exit_code, timed_out, expected):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    runner = QemuRsiRunner(config)
    exchange = ExchangePaths(tmp_path / "input", tmp_path / "output", tmp_path / "output" / "result.json")
    exchange.output_dir.mkdir()
    exchange.result_path.write_text(payload)

    result = runner.parse_result(exchange, "stdout", "stderr", exit_code, timed_out)

    assert result.status == expected


def test_parse_result_rejects_oversized_diagnostics(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    runner = QemuRsiRunner(config)
    exchange = ExchangePaths(tmp_path / "input", tmp_path / "output", tmp_path / "output" / "result.json")
    exchange.output_dir.mkdir()
    exchange.result_path.write_text('{"status":"passed"}')

    result = runner.parse_result(exchange, "x" * 4097, "", 0, False)

    assert result.status == "invalid"
    assert "output limit" in result.stderr


class _FakeProcess:
    def __init__(self, command, *, outcome="success"):
        self.command = command
        self.outcome = outcome
        self.killed = False

    def communicate(self, timeout=None):
        if self.outcome == "timeout" and not self.killed:
            raise subprocess.TimeoutExpired(self.command, timeout)
        if self.outcome == "timeout":
            return "", "timed out"
        output = next(token.split("path=", 1)[1].split(",", 1)[0]
                      for token in self.command if token.startswith("local,path=") and "sophyane-output" in token)
        Path(output, "result.json").write_text(json.dumps(_guest_result()))
        return "guest stdout", "guest stderr"

    def kill(self):
        self.killed = True

    returncode = 0

    def wait(self, timeout=None):
        return None


def test_run_executes_without_shell_and_cleans_exchange(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "answer.py").write_text("answer = 42\n")
    calls = []
    process = _FakeProcess(())

    def popen(command, **kwargs):
        process.command = command
        calls.append((command, kwargs))
        return process

    result = QemuRsiRunner(config, popen_factory=popen).run(candidate, _manifest())

    assert result.status == "passed"
    assert calls[0][1]["shell"] is False
    assert not list(config.scratch_root.glob("*"))


def test_run_terminates_timed_out_qemu_and_cleans_exchange(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    process = _FakeProcess((), outcome="timeout")

    result = QemuRsiRunner(config, popen_factory=lambda command, **kwargs: process).run(
        candidate, _manifest()
    )

    assert result.status == "timeout"
    assert process.killed is True
    assert not list(config.scratch_root.glob("*"))


def test_run_reports_qemu_startup_failure_and_cleans_exchange(tmp_path):
    config = _config(tmp_path)
    config.guest_image.write_bytes(b"guest")
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    def popen(command, **kwargs):
        raise OSError("qemu missing")

    result = QemuRsiRunner(config, popen_factory=popen).run(candidate, _manifest())

    assert result.status == "failed"
    assert "qemu missing" in result.stderr
    assert not list(config.scratch_root.glob("*"))
