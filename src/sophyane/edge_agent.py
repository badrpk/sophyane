"""Edge / industrial / IoT profile for Sophyane.

Targets constrained chips: industrial gateways, PLC companions, meters, phones,
and small SBCs. Keeps a tiny surface area: health, memory, safe shell (optional),
and short chat — never the full repository coding planner.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from sophyane.platform_probe import PlatformReport, probe_platform


EDGE_SYSTEM_PROMPT = (
    "You are Sophyane Edge, a compact on-device assistant for industrial and "
    "field equipment. Reply in short plain language. Never invent sensor "
    "readings. Prefer safety: do not recommend unsafe electrical or mechanical actions."
)


@dataclass
class EdgeHealth:
    ok: bool
    equipment_class: str
    profile: str
    ram_mb: int
    disk_free_mb: int
    provider: str
    model: str
    ts: float
    messages: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def edge_allowed(report: PlatformReport | None = None) -> bool:
    report = report or probe_platform()
    return report.recommended_profile in {"nano", "edge", "mobile", "full"}


def build_edge_health(
    *,
    provider: str = "",
    model: str = "",
    report: PlatformReport | None = None,
) -> EdgeHealth:
    report = report or probe_platform()
    messages: list[str] = []
    ok = True
    if report.ram_mb and report.ram_mb < 256:
        ok = False
        messages.append("RAM below 256MB — chat may be cloud-only")
    if report.disk_free_mb and report.disk_free_mb < 50:
        messages.append("Low disk free space")
    if report.equipment_class == "nano_edge":
        messages.append("nano_edge: use API cloud or ultra-tiny GGUF only")
    return EdgeHealth(
        ok=ok,
        equipment_class=report.equipment_class,
        profile=report.recommended_profile,
        ram_mb=report.ram_mb,
        disk_free_mb=report.disk_free_mb,
        provider=provider,
        model=model,
        ts=time.time(),
        messages=messages,
    )


def edge_chat(
    message: str,
    generate: Callable[[str, str], str],
    *,
    max_chars: int = 1500,
) -> str:
    """Run a short edge chat with hard prompt bounds."""
    text = (message or "").strip()
    if not text:
        return "Send a short status or question."
    if len(text) > max_chars:
        text = text[:max_chars]
    return generate(text, EDGE_SYSTEM_PROMPT)


# Equipment taxonomy for documentation / routing (not device drivers).
EQUIPMENT_TARGETS: dict[str, str] = {
    "plc_gateway": "Industrial PLC companion gateway (Linux ARM/x86)",
    "energy_meter": "Smart meter / submeter with Linux or MCU host",
    "sensor_hub": "IoT sensor aggregator / MQTT edge node",
    "phone_android": "Android via Termux or PWA web UI",
    "phone_ios": "iOS via SSH to companion host or web UI",
    "laptop": "Windows / macOS / Linux workstation",
    "cloud_vm": "Cloud VM / container agent",
    "sbc": "Raspberry Pi / Orange Pi class SBC",
    "desktop": "Full desktop coding agent",
}
