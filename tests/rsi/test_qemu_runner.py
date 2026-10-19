from pathlib import Path

import pytest

from sophyane.rsi.qemu_runner import (
    QemuRunnerConfig,
    QemuRunnerConfigurationError,
    QemuRsiRunner,
    build_qemu_command,
)


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
        "-append",
        "sophyane.input=/sophyane-input/task.json sophyane.output=/sophyane-output/result.json",
    )


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
