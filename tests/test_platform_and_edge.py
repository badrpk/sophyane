from sophyane.edge_agent import EQUIPMENT_TARGETS, build_edge_health, edge_chat, edge_allowed
from sophyane.platform_probe import format_platform_report, probe_platform


def test_probe_platform_core_fields():
    report = probe_platform()
    assert report.os_family in {"windows", "macos", "linux", "android", "ios", "unknown"}
    assert report.equipment_class in {
        "nano_edge", "edge", "mobile", "workstation", "server", "cloud"
    }
    assert report.recommended_profile in {"nano", "edge", "mobile", "full"}
    assert report.cpus >= 1
    text = format_platform_report(report)
    assert "equipment class" in text.lower() or "Equipment class" in text


def test_edge_health_and_chat():
    assert edge_allowed() is True
    health = build_edge_health(provider="local_gguf", model="qwen2.5-0.5b")
    assert health.equipment_class
    assert "ok" in health.to_json()
    reply = edge_chat("status?", lambda p, s: f"edge:{p[:20]}")
    assert reply.startswith("edge:")
    assert "plc_gateway" in EQUIPMENT_TARGETS
    assert "energy_meter" in EQUIPMENT_TARGETS
