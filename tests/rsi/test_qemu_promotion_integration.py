import json
from pathlib import Path
import sys

from sophyane.rsi.models import CommandResult


def test_qemu_backend_is_explicitly_opt_in(monkeypatch, tmp_path):
    from sophyane.rsi.runtime_services import build_qemu_runner

    monkeypatch.delenv("SOPHYANE_RSI_EXECUTION_BACKEND", raising=False)
    assert build_qemu_runner(tmp_path) is None

    image = tmp_path / "guest.img"
    image.write_bytes(b"guest")
    monkeypatch.setenv("SOPHYANE_RSI_EXECUTION_BACKEND", "qemu")
    monkeypatch.setenv("SOPHYANE_RSI_QEMU_IMAGE", str(image))
    runner = build_qemu_runner(tmp_path)

    assert runner is not None
    assert runner.config.enabled is True
    assert runner.config.guest_image == image


def test_continuous_controller_wires_opted_in_qemu_runner(monkeypatch, tmp_path):
    from sophyane.rsi.runtime_services import build_controller

    image = tmp_path / "guest.img"
    image.write_bytes(b"guest")
    monkeypatch.setenv("SOPHYANE_RSI_EXECUTION_BACKEND", "qemu")
    monkeypatch.setenv("SOPHYANE_RSI_QEMU_IMAGE", str(image))

    controller = build_controller(tmp_path / "state")

    assert controller.runner.command_runner.__self__.__class__.__name__ == "QemuRsiRunner"


def test_failed_qemu_execution_rejects_without_changing_active_commit(repo, tmp_path):
    from test_end_to_end_rsi_cycle import build_controller
    from conftest import git

    controller, weakness, _ = build_controller(repo, tmp_path)
    baseline = git(repo, "rev-parse", "HEAD")

    def failed_runner(command, cwd, *, timeout, cancelled):
        return CommandResult(tuple(command), 1, "guest boot failed", str(cwd))

    controller.execution_runner = failed_runner

    result = controller.run_once(weakness)

    assert result.state == "REJECTED"
    assert git(repo, "rev-parse", "HEAD") == baseline


def test_successful_qemu_evidence_still_requires_existing_promotion_gates(repo, tmp_path):
    from test_end_to_end_rsi_cycle import build_controller
    from conftest import git

    controller, weakness, _ = build_controller(repo, tmp_path)

    def guest_runner(command, cwd, *, timeout, cancelled):
        cwd = Path(cwd)
        if command[-1] == "check.py" and (cwd / "value.py").read_text() == "VALUE = 1\n":
            return CommandResult(tuple(command), 1, "AssertionError: RSI_WEAKNESS_wrong_value", str(cwd))
        if "-c" in command:
            quality = 1 if (cwd / "value.py").read_text() == "VALUE = 1\n" else 2
            return CommandResult(tuple(command), 0, json.dumps({"quality": quality, "latency": 1}), str(cwd))
        return CommandResult(tuple(command), 0, "", str(cwd))

    controller.execution_runner = guest_runner

    result = controller.run_once(weakness)

    assert result.state == "VERIFIED_BASELINE", result.evidence
    assert git(repo, "rev-parse", "HEAD") != weakness.baseline_commit
