from __future__ import annotations

from sophyane.hardware_api import HardwareAPI
from sophyane.hardware_registry import (
    CHIP_VENDORS,
    OPEN_SOFTWARE,
    format_hardware_report,
    hardware_compatibility_report,
    recommended_backends,
)


def test_chip_catalog_covers_major_vendors() -> None:
    for key in (
        "nvidia",
        "intel",
        "amd",
        "qualcomm",
        "micron",
        "apple",
        "arm",
        "texas_instruments",
        "nxp",
        "stmicro",
    ):
        assert key in CHIP_VENDORS
    assert len(CHIP_VENDORS) >= 20


def test_open_software_catalog() -> None:
    for key in ("llama_cpp", "onnxruntime", "mqtt", "modbus", "nodejs", "cpp_toolchain"):
        assert key in OPEN_SOFTWARE


def test_hardware_report_shape() -> None:
    report = hardware_compatibility_report()
    assert "vendors_supported_catalog" in report
    assert "recommended_backends" in report
    assert "cpu" in report["recommended_backends"]
    assert report["languages"]["python"]["status"] == "native"
    assert report["languages"]["cpp"]["path"] == "sdk/cpp"
    assert report["languages"]["javascript"]["path"] == "sdk/js"
    text = format_hardware_report(report)
    assert "compatibility" in text.lower() or "Hardware" in text
    assert recommended_backends()


def test_hardware_api_dispatch() -> None:
    api = HardwareAPI(generate=lambda prompt, system: f"echo:{prompt[:32]}")
    health = api.dispatch("health")
    assert health.get("ok") is True
    hw = api.dispatch("hardware")
    assert hw.get("ok") is True
    chat = api.dispatch("chat", {"message": "hi", "edge": True})
    assert chat.get("ok") is True
    assert "echo:" in chat.get("reply", "")
    unknown = api.dispatch("nope")
    assert unknown.get("ok") is False
