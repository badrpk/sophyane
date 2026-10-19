"""Fail-closed QEMU boundary for RSI candidate verification."""

from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
from pathlib import Path
from typing import Any
import subprocess
import uuid

from .coding_provider import CodingCancelled
from .models import CommandResult


class QemuRunnerConfigurationError(PermissionError):
    """QEMU RSI cannot run with the supplied isolated configuration."""


@dataclass(frozen=True)
class QemuRunnerConfig:
    executable: str | Path
    guest_image: Path
    architecture: str
    scratch_root: Path
    timeout_seconds: float
    max_output_bytes: int
    enabled: bool = False
    firmware: Path | None = None

    def __post_init__(self) -> None:
        if self.architecture != "aarch64":
            raise ValueError("QEMU RSI currently supports aarch64 guests only")
        if self.timeout_seconds <= 0:
            raise ValueError("QEMU RSI timeout must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("QEMU RSI output limit must be positive")


@dataclass(frozen=True)
class QemuRunResult:
    run_id: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    status: str
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExchangePaths:
    input_dir: Path
    output_dir: Path
    result_path: Path


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validate_exchange_paths(config: QemuRunnerConfig, input_dir: Path, output_dir: Path) -> None:
    scratch = config.scratch_root.resolve()
    if not _inside(input_dir, scratch) or not _inside(output_dir, scratch):
        raise QemuRunnerConfigurationError("QEMU exchange paths must stay inside scratch root")
    if input_dir.resolve() == output_dir.resolve():
        raise QemuRunnerConfigurationError("QEMU input and output shares must be separate")


def build_qemu_command(
    config: QemuRunnerConfig,
    input_dir: Path,
    output_dir: Path,
    manifest: dict[str, Any],
) -> tuple[str, ...]:
    """Build the fixed guest command; manifest contents travel in task.json."""
    del manifest
    _validate_exchange_paths(config, Path(input_dir), Path(output_dir))
    executable = str(config.executable)
    image = str(config.guest_image.resolve())
    command = [
        executable,
        "-machine",
        "virt",
        "-accel",
        "tcg,thread=multi",
        "-nographic",
        "-no-reboot",
        "-drive",
        f"if=none,format={'qcow2' if config.guest_image.suffix.lower() in ('.qcow2', '.qcow') else 'raw'},readonly=on,file={image},id=drive0",
        "-device",
        "virtio-blk-device,drive=drive0",
        "-virtfs",
        f"local,path={Path(input_dir).resolve()},mount_tag=sophyane-input,security_model=none,readonly=on",
        "-virtfs",
        f"local,path={Path(output_dir).resolve()},mount_tag=sophyane-output,security_model=none",
    ]
    if config.firmware is not None:
        command[1:1] = ["-bios", str(config.firmware.resolve())]
    return tuple(command)


class QemuRsiRunner:
    def __init__(self, config: QemuRunnerConfig, *, popen_factory=None):
        self.config = config
        self._popen_factory = popen_factory or subprocess.Popen

    def validate(self) -> None:
        if not self.config.enabled:
            raise QemuRunnerConfigurationError("QEMU RSI is opt-in; enable it explicitly")
        image = self.config.guest_image
        if not image.exists():
            raise QemuRunnerConfigurationError(f"QEMU guest image does not exist: {image}")
        if not image.is_file():
            raise QemuRunnerConfigurationError("QEMU guest image must be a regular file")
        if self.config.firmware is not None and not self.config.firmware.is_file():
            raise QemuRunnerConfigurationError("QEMU firmware must be a regular file")
        if not str(self.config.executable).strip():
            raise QemuRunnerConfigurationError("QEMU executable is required")

    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    def prepare_exchange(self, candidate_dir: Path, manifest: dict[str, Any]) -> ExchangePaths:
        self.validate()
        candidate = Path(candidate_dir).resolve()
        if not candidate.is_dir():
            raise QemuRunnerConfigurationError("QEMU candidate workspace must be a directory")
        for path in candidate.rglob("*"):
            if path.is_symlink():
                raise QemuRunnerConfigurationError("QEMU candidate workspace cannot contain symlinks")

        run_root = self.config.scratch_root.resolve() / self.new_run_id()
        input_dir = run_root / "input"
        output_dir = run_root / "output"
        input_dir.mkdir(parents=True)
        output_dir.mkdir()
        shutil.copytree(candidate, input_dir / "candidate")
        (input_dir / "task.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        for path in (input_dir / "candidate").rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode & ~0o222)
        (input_dir / "task.json").chmod(0o444)
        return ExchangePaths(input_dir, output_dir, output_dir / "result.json")

    def parse_result(
        self,
        exchange: ExchangePaths,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        timed_out: bool,
    ) -> QemuRunResult:
        run_id = exchange.output_dir.parent.name
        combined_size = len(stdout.encode()) + len(stderr.encode())
        if combined_size > self.config.max_output_bytes:
            return QemuRunResult(run_id, exit_code, stdout[:1024], "output limit exceeded", False, "invalid")
        if timed_out:
            return QemuRunResult(run_id, exit_code, stdout, stderr, True, "timeout")
        if exit_code != 0:
            return QemuRunResult(run_id, exit_code, stdout, stderr, False, "failed")
        try:
            if exchange.result_path.stat().st_size > self.config.max_output_bytes:
                raise ValueError("result output limit exceeded")
            result = json.loads(exchange.result_path.read_text(encoding="utf-8"))
            if not isinstance(result, dict) or result.get("status") != "passed":
                raise ValueError("guest result must be a passed object")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return QemuRunResult(run_id, exit_code, stdout, str(error), False, "invalid")
        return QemuRunResult(run_id, exit_code, stdout, stderr, False, "passed", result)

    def run(self, candidate_dir: Path, manifest: dict[str, Any]) -> QemuRunResult:
        self.validate()
        exchange = self.prepare_exchange(candidate_dir, manifest)
        run_id = exchange.output_dir.parent.name
        process = None
        try:
            command = build_qemu_command(self.config, exchange.input_dir, exchange.output_dir, manifest)
            process = self._popen_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
            try:
                stdout, stderr = process.communicate(timeout=self.config.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                return QemuRunResult(run_id, getattr(process, "returncode", None), stdout, stderr, True, "timeout")
            return self.parse_result(exchange, stdout, stderr, process.returncode, False)
        except OSError as error:
            return QemuRunResult(run_id, None, "", str(error), False, "failed")
        finally:
            shutil.rmtree(exchange.output_dir.parent, ignore_errors=True)

    def run_command(self, command, cwd, *, timeout=300, cancelled=lambda: False) -> CommandResult:
        if cancelled():
            raise CodingCancelled("QEMU verification cancelled")
        original_timeout = self.config.timeout_seconds
        bounded_timeout = min(original_timeout, float(timeout))
        config = self.config
        if bounded_timeout != original_timeout:
            config = QemuRunnerConfig(
                executable=config.executable, guest_image=config.guest_image,
                architecture=config.architecture, scratch_root=config.scratch_root,
                timeout_seconds=bounded_timeout, max_output_bytes=config.max_output_bytes,
                enabled=config.enabled, firmware=config.firmware,
            )
        result = QemuRsiRunner(config, popen_factory=self._popen_factory).run(
            cwd, {"task_id": self.new_run_id(), "command": list(command), "cwd": "/sophyane-input/candidate"}
        )
        if result.status == "timeout":
            exit_code = 124
        elif result.status == "passed":
            exit_code = 0
        else:
            exit_code = 1
        output = result.stdout
        if result.stderr:
            output = f"{output}\n{result.stderr}" if output else result.stderr
        return CommandResult(tuple(command), exit_code, output, str(cwd))
