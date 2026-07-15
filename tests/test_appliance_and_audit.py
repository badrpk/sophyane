from __future__ import annotations

from pathlib import Path

from sophyane.appliance import (
    boot_appliance,
    detect_network_interfaces,
    network_capability_report,
    write_chip_install_script,
    write_systemd_unit,
)
from sophyane.feature_audit import run_full_audit


def test_detect_network_interfaces() -> None:
    net = detect_network_interfaces()
    assert "interfaces" in net
    assert isinstance(net["interfaces"], list)
    assert net.get("hostname")
    assert "wifi_tools" in net
    cap = network_capability_report(net)
    assert "cable_path" in cap
    assert "wifi_path" in cap


def test_boot_appliance_once() -> None:
    report = boot_appliance(
        open_browser=False,
        start_mesh=True,
        start_hardware_api=True,
        start_kernel=True,
    )
    assert report.version
    steps = {s.get("step") for s in report.steps}
    assert "platform" in steps
    assert "network" in steps
    assert "kernel" in steps
    assert report.ok is True, report.to_dict()
    # Idempotent second boot (ports may already be held)
    report2 = boot_appliance(
        open_browser=False,
        start_mesh=True,
        start_hardware_api=True,
        start_kernel=True,
    )
    assert report2.ok is True, report2.to_dict()


def test_write_units(tmp_path: Path, monkeypatch) -> None:
    unit = write_systemd_unit(tmp_path / "sophyane-appliance.service")
    assert unit.exists()
    text = unit.read_text(encoding="utf-8")
    assert "Sophyane" in text
    assert "--boot" in text
    script = write_chip_install_script(tmp_path / "sophyane-install-chip")
    assert script.exists()
    body = script.read_text(encoding="utf-8")
    assert "install.sh" in body
    assert "sophyane --boot" in body


def test_full_feature_audit() -> None:
    report = run_full_audit()
    assert report["total"] >= 15
    # Allow minor optional failures (e.g. network scrape) but require strong core
    core = [
        c
        for c in report["checks"]
        if c["area"]
        in {"import", "kernel", "platform", "hardware", "mesh", "erp", "apps", "improve", "appliance"}
    ]
    assert all(c["ok"] for c in core), [c for c in core if not c["ok"]]
