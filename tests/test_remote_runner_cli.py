from __future__ import annotations

import pytest

from sophyane.remote_runner_cli import qemu_health_timeout_seconds


def test_qemu_health_timeout_is_configurable_and_bounded(monkeypatch):
    monkeypatch.delenv("SOPHYANE_QEMU_HEALTH_TIMEOUT_SECONDS", raising=False)
    assert qemu_health_timeout_seconds() == 240

    monkeypatch.setenv("SOPHYANE_QEMU_HEALTH_TIMEOUT_SECONDS", "900")
    assert qemu_health_timeout_seconds() == 900

    for value in ("invalid", "59", "1801"):
        monkeypatch.setenv("SOPHYANE_QEMU_HEALTH_TIMEOUT_SECONDS", value)
        with pytest.raises(RuntimeError, match="between 60 and 1800"):
            qemu_health_timeout_seconds()
