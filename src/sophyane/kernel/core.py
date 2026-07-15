"""Sophyane AI Kernel core — boot, modules, status."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sophyane.hardware_registry import (
    format_hardware_report,
    hardware_compatibility_report,
    recommended_backends,
)
from sophyane.kernel.app_factory import SUPPORTED_TARGETS, create_app
from sophyane.kernel.bus import KernelBus
from sophyane.kernel.erp import list_erp_systems, probe_all_erp, probe_erp
from sophyane.platform_probe import probe_platform
from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
KERNEL_STATE = STATE_DIR / "ai_kernel.json"


@dataclass
class KernelModule:
    name: str
    kind: str
    status: str = "ready"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KernelStatus:
    ok: bool
    version: str
    uptime_s: float
    profile: str
    modules: list[dict[str, Any]] = field(default_factory=list)
    backends: list[str] = field(default_factory=list)
    app_targets: list[str] = field(default_factory=list)
    erp_systems: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class AIKernel:
    """Userspace AI kernel supervisor."""

    def __init__(self) -> None:
        self.bus = KernelBus()
        self.booted_at = 0.0
        self.modules: dict[str, KernelModule] = {}
        self._booted = False

    @property
    def booted(self) -> bool:
        return self._booted

    def boot(self) -> KernelStatus:
        self.booted_at = time.time()
        self.bus.publish("kernel.boot", {"version": __version__}, source="core")

        platform = probe_platform()
        self.modules["platform"] = KernelModule(
            "platform",
            "probe",
            "ready",
            f"{platform.os_family}/{platform.equipment_class}/{platform.recommended_profile}",
        )

        try:
            hw = hardware_compatibility_report()
            present = ", ".join(v["name"] for v in hw.get("vendors_present") or []) or "cpu-generic"
            self.modules["hardware"] = KernelModule(
                "hardware",
                "bus",
                "ready",
                f"backends={','.join(hw.get('recommended_backends') or [])}; present={present}",
            )
        except Exception as error:  # noqa: BLE001
            self.modules["hardware"] = KernelModule("hardware", "bus", "degraded", str(error))

        self.modules["software"] = KernelModule(
            "software",
            "bus",
            "ready",
            "CUDA/ROCm/OpenVINO/Metal/open-source stacks via hardware_registry",
        )
        self.modules["app_factory"] = KernelModule(
            "app_factory",
            "service",
            "ready",
            f"targets={','.join(SUPPORTED_TARGETS)}",
        )
        self.modules["erp"] = KernelModule(
            "erp",
            "service",
            "ready",
            f"systems={','.join(sorted(s['id'] for s in list_erp_systems()))}",
        )
        self.modules["agents"] = KernelModule(
            "agents",
            "runtime",
            "ready",
            "chat, coding, multiagent, edge, daemon",
        )
        self.modules["memory"] = KernelModule("memory", "runtime", "ready", "sqlite persistent memory")
        self.modules["security"] = KernelModule(
            "security",
            "policy",
            "ready",
            "guardrails + approval gates + edge safety prompts",
        )

        self._booted = True
        self.bus.publish(
            "kernel.ready",
            {"modules": list(self.modules)},
            source="core",
        )
        self._persist()
        return self.status()

    def status(self) -> KernelStatus:
        platform = probe_platform()
        uptime = (time.time() - self.booted_at) if self._booted else 0.0
        return KernelStatus(
            ok=self._booted and all(m.status != "failed" for m in self.modules.values()),
            version=__version__,
            uptime_s=uptime,
            profile=platform.recommended_profile,
            modules=[m.to_dict() for m in self.modules.values()],
            backends=recommended_backends(),
            app_targets=list(SUPPORTED_TARGETS),
            erp_systems=[s["id"] for s in list_erp_systems()],
            events=self.bus.history(20),
            message=(
                "Sophyane AI Kernel is a userspace intelligence control plane "
                "(not a ring-0 OS). It coordinates hardware adapters, app factories, "
                "ERP connectors, and agents on top of Linux/Windows/macOS/edge hosts."
            ),
        )

    def create_application(
        self,
        target: str,
        name: str,
        *,
        output_dir: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        if not self._booted:
            self.boot()
        result = create_app(target, name, output_dir=output_dir, description=description)
        self.bus.publish(
            "app.created" if result.ok else "app.failed",
            result.to_dict(),
            source="app_factory",
        )
        self._persist()
        return result.to_dict()

    def erp_status(self, system: str | None = None) -> dict[str, Any]:
        if not self._booted:
            self.boot()
        if system:
            return probe_erp(system).to_dict()
        return {"systems": probe_all_erp()}

    def hardware_text(self) -> str:
        return format_hardware_report()

    def _persist(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "booted": self._booted,
            "booted_at": self.booted_at,
            "status": self.status().to_dict(),
            "saved_at": time.time(),
        }
        KERNEL_STATE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


_KERNEL: AIKernel | None = None


def boot_kernel() -> AIKernel:
    global _KERNEL
    if _KERNEL is None:
        _KERNEL = AIKernel()
    if not _KERNEL.booted:
        _KERNEL.boot()
    return _KERNEL


def kernel_status() -> KernelStatus:
    kernel = boot_kernel()
    return kernel.status()
