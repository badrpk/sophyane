"""Fail-closed QEMU boundary for RSI candidate verification."""

from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
from pathlib import Path
from typing import Any
import subprocess
import time
import uuid

from .coding_provider import CodingCancelled
from .guest_protocol import GuestProtocolError, validate_manifest, validate_result
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
    memory_mb: int = 1024
    kernel: Path | None = None
    initrd: Path | None = None
    root_device: str = "/dev/vda1"
    init_path: str | None = None

    def __post_init__(self) -> None:
        if self.architecture != "aarch64":
            raise ValueError("QEMU RSI currently supports aarch64 guests only")
        if self.timeout_seconds <= 0:
            raise ValueError("QEMU RSI timeout must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("QEMU RSI output limit must be positive")
        if self.memory_mb <= 0:
            raise ValueError("QEMU RSI memory must be positive")
        if (self.kernel is None) != (self.initrd is None):
            raise ValueError("QEMU kernel and initrd must be configured together")
        if not self.root_device.startswith("/dev/"):
            raise ValueError("QEMU root device must be a device path")
        if self.init_path is not None and (not self.init_path.startswith("/") or " " in self.init_path):
            raise ValueError("QEMU init path must be an absolute path without spaces")


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
    task_id: str | None = None


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
        "-cpu",
        "cortex-a57",
        "-accel",
        "tcg,thread=multi",
        "-m",
        str(config.memory_mb),
        "-nographic",
        "-monitor",
        "none",
        "-serial",
        "stdio",
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
    if config.kernel is not None and config.initrd is not None:
        command[1:1] = [
            "-kernel", str(config.kernel.resolve()),
            "-initrd", str(config.initrd.resolve()),
            "-append", " ".join(filter(None, (
                f"root={config.root_device} rw console=ttyAMA0,115200 earlycon=pl011,mmio32,0x09000000 loglevel=8",
                # rdinit runs from the initramfs, before the ext4 root is
                # mounted. The configured Sophyane bootstrap lives on that
                # root, so the initramfs entrypoint must remain /init.
                "rdinit=/init",
                f"init={config.init_path}" if config.init_path else None,
            ))),
        ]
    elif config.firmware is not None:
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
        for name, path in (("kernel", self.config.kernel), ("initrd", self.config.initrd)):
            if path is not None and not path.is_file():
                raise QemuRunnerConfigurationError(f"QEMU {name} must be a regular file")
        if not str(self.config.executable).strip():
            raise QemuRunnerConfigurationError("QEMU executable is required")

    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    def prepare_exchange(self, candidate_dir: Path, manifest: dict[str, Any]) -> ExchangePaths:
        self.validate()
        try:
            validated_manifest = validate_manifest(manifest)
        except GuestProtocolError as error:
            raise QemuRunnerConfigurationError(f"guest manifest rejected: {error}") from error
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
            json.dumps(
                {
                    "schema_version": validated_manifest.schema_version,
                    "task_id": validated_manifest.task_id,
                    "command": list(validated_manifest.command),
                    "cwd": validated_manifest.cwd,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        for path in (input_dir / "candidate").rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode & ~0o222)
        (input_dir / "task.json").chmod(0o444)
        return ExchangePaths(input_dir, output_dir, output_dir / "result.json", validated_manifest.task_id)

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
            output_entries = tuple(exchange.output_dir.iterdir())
            unexpected = [path.name for path in output_entries if path.name != "result.json"]
            if unexpected:
                raise ValueError(f"unexpected guest output files: {sorted(unexpected)}")
            if exchange.result_path.stat().st_size > self.config.max_output_bytes:
                raise ValueError("result output limit exceeded")
            result = json.loads(exchange.result_path.read_text(encoding="utf-8"))
            validated_result = validate_result(result)
            if exchange.task_id is not None and validated_result.task_id != exchange.task_id:
                raise ValueError("guest result task_id does not match manifest")
            if validated_result.status != "passed" or validated_result.exit_code != 0:
                return QemuRunResult(
                    run_id,
                    validated_result.exit_code,
                    validated_result.stdout,
                    validated_result.stderr,
                    False,
                    "failed",
                    result,
                )
        except (OSError, ValueError, json.JSONDecodeError, GuestProtocolError) as error:
            return QemuRunResult(run_id, exit_code, stdout, str(error), False, "invalid")
        return QemuRunResult(
            run_id,
            exit_code,
            validated_result.stdout,
            validated_result.stderr,
            False,
            "passed",
            result,
        )

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
            deadline = time.monotonic() + self.config.timeout_seconds
            while True:
                returncode = process.poll()
                if returncode is not None:
                    stdout, stderr = process.communicate()
                    return self.parse_result(exchange, stdout, stderr, returncode, False)
                if exchange.result_path.exists():
                    process.terminate()
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate()
                    return self.parse_result(exchange, stdout, stderr, 0, False)
                if time.monotonic() >= deadline:
                    process.kill()
                    stdout, stderr = process.communicate()
                    return QemuRunResult(run_id, getattr(process, "returncode", None), stdout, stderr, True, "timeout")
                time.sleep(0.1)
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
                enabled=config.enabled, firmware=config.firmware, memory_mb=config.memory_mb,
                kernel=config.kernel, initrd=config.initrd, root_device=config.root_device,
                init_path=config.init_path,
            )
        result = QemuRsiRunner(config, popen_factory=self._popen_factory).run(
            cwd, {"schema_version": 1, "task_id": self.new_run_id(), "command": list(command), "cwd": "/mnt/sophyane-input/candidate"}
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
