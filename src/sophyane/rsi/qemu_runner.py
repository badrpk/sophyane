"""Fail-closed QEMU boundary for RSI candidate verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import uuid


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
    return (
        executable,
        "-machine",
        "virt",
        "-accel",
        "tcg,thread=multi",
        "-nographic",
        "-no-reboot",
        "-drive",
        f"if=none,format=raw,readonly=on,file={image},id=drive0",
        "-device",
        "virtio-blk-device,drive=drive0",
        "-virtfs",
        f"local,path={Path(input_dir).resolve()},mount_tag=sophyane-input,security_model=none,readonly=on",
        "-virtfs",
        f"local,path={Path(output_dir).resolve()},mount_tag=sophyane-output,security_model=none",
        "-append",
        "sophyane.input=/sophyane-input/task.json sophyane.output=/sophyane-output/result.json",
    )


class QemuRsiRunner:
    def __init__(self, config: QemuRunnerConfig):
        self.config = config

    def validate(self) -> None:
        if not self.config.enabled:
            raise QemuRunnerConfigurationError("QEMU RSI is opt-in; enable it explicitly")
        image = self.config.guest_image
        if not image.exists():
            raise QemuRunnerConfigurationError(f"QEMU guest image does not exist: {image}")
        if not image.is_file():
            raise QemuRunnerConfigurationError("QEMU guest image must be a regular file")
        if not str(self.config.executable).strip():
            raise QemuRunnerConfigurationError("QEMU executable is required")

    def new_run_id(self) -> str:
        return uuid.uuid4().hex
