"""Cross-platform and equipment-class probe for Sophyane.

Detects OS family, architecture, resource class, and deployment surface so the
same harness can adapt from PLC/edge meters to phones, desktops, and cloud VMs.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PlatformReport:
    os_family: str  # windows | macos | linux | android | ios | unknown
    os_name: str
    arch: str
    python: str
    cpus: int
    ram_mb: int
    disk_free_mb: int
    surface: str  # desktop | mobile | cloud | edge | container | unknown
    equipment_class: str  # nano_edge | edge | mobile | workstation | server | cloud
    virtualization: str
    has_gpu_hint: bool
    termux: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def supports_full_cli(self) -> bool:
        return self.equipment_class in {"workstation", "server", "cloud", "mobile"}

    @property
    def recommended_profile(self) -> str:
        """Runtime profile: full | mobile | edge | nano."""
        if self.equipment_class == "nano_edge":
            return "nano"
        if self.equipment_class == "edge":
            return "edge"
        if self.equipment_class == "mobile" or self.termux:
            return "mobile"
        return "full"


def _ram_mb() -> int:
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys // (1024 * 1024))
        meminfo = open("/proc/meminfo", encoding="utf-8").read()
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def _disk_free_mb() -> int:
    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        return int(usage.free // (1024 * 1024))
    except Exception:
        return 0


def _os_family() -> tuple[str, bool]:
    system = platform.system().lower()
    termux = bool(os.environ.get("PREFIX", "").endswith("com.termux")) or (
        "com.termux" in os.environ.get("PREFIX", "")
    )
    android = termux or "android" in platform.platform().lower() or os.path.exists(
        "/system/build.prop"
    )
    if android or termux:
        return "android", termux
    if system == "darwin":
        # iOS Pythonista / a-Shell style environments sometimes report Darwin.
        if any(k in os.environ for k in ("IPHONE", "IOS_PYTHON", "PYTHONISTA")):
            return "ios", False
        return "macos", False
    if system == "windows":
        return "windows", False
    if system == "linux":
        return "linux", False
    return "unknown", False


def _surface(os_family: str, virt: str, termux: bool) -> str:
    if termux or os_family in {"android", "ios"}:
        return "mobile"
    if virt in {"kvm", "qemu", "vmware", "xen", "microsoft", "docker", "lxc", "podman"}:
        # Crosvm / cloud VMs
        if virt in {"docker", "lxc", "podman"}:
            return "container"
        return "cloud" if _ram_mb() >= 4000 else "container"
    if os_family in {"windows", "macos", "linux"}:
        return "desktop"
    return "unknown"


def _virtualization() -> str:
    try:
        import subprocess

        out = subprocess.run(
            ["systemd-detect-virt"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    platform_s = platform.platform().lower()
    for token in ("crosvm", "docker", "lxc", "kvm", "vmware", "hyperv", "xen"):
        if token in platform_s:
            return token
    return "none"


def _equipment_class(ram_mb: int, surface: str, cpus: int) -> str:
    if ram_mb and ram_mb < 512:
        return "nano_edge"  # meters, tiny MCU-class Linux, PLC gateways
    if ram_mb and ram_mb < 1500:
        return "edge"  # Pi Zero-class, industrial gateways
    if surface == "mobile" or (ram_mb and ram_mb < 3500 and cpus <= 4):
        if surface == "mobile":
            return "mobile"
        return "edge" if ram_mb < 2500 else "workstation"
    if ram_mb and ram_mb >= 16000:
        return "server" if surface != "cloud" else "cloud"
    if surface == "cloud":
        return "cloud"
    return "workstation"


def _gpu_hint() -> bool:
    for path in ("/dev/nvidia0", "/dev/dri/card0"):
        if os.path.exists(path):
            return True
    return bool(shutil.which("nvidia-smi"))


def probe_platform() -> PlatformReport:
    os_family, termux = _os_family()
    virt = _virtualization()
    ram = _ram_mb()
    cpus = os.cpu_count() or 1
    surface = _surface(os_family, virt, termux)
    equipment = _equipment_class(ram, surface, cpus)
    notes: list[str] = []
    if termux:
        notes.append("Termux Android detected — use mobile profile and Ollama/GGUF carefully")
    if equipment in {"nano_edge", "edge"}:
        notes.append(
            "Edge profile: prefer local_gguf tiny models or cloud API; skip heavy coding planner"
        )
    if os_family == "windows":
        notes.append("Windows: use install.ps1; paths under %USERPROFILE%\\.local")
    if os_family == "macos":
        notes.append("macOS: Homebrew python3 recommended; Apple Silicon uses arm64 Ollama/GGUF")
    if os_family == "ios":
        notes.append("iOS constrained runtime — edge/nano profile only; no full coding agent")

    return PlatformReport(
        os_family=os_family,
        os_name=platform.platform(),
        arch=platform.machine() or "unknown",
        python=platform.python_version(),
        cpus=cpus,
        ram_mb=ram,
        disk_free_mb=_disk_free_mb(),
        surface=surface,
        equipment_class=equipment,
        virtualization=virt,
        has_gpu_hint=_gpu_hint(),
        termux=termux,
        notes=tuple(notes),
    )


def format_platform_report(report: PlatformReport | None = None) -> str:
    report = report or probe_platform()
    lines = [
        f"Sophyane platform probe",
        f"  OS family:        {report.os_family}",
        f"  OS:               {report.os_name}",
        f"  Arch:             {report.arch}",
        f"  Python:           {report.python}",
        f"  CPUs:             {report.cpus}",
        f"  RAM:              {report.ram_mb} MB",
        f"  Disk free:        {report.disk_free_mb} MB",
        f"  Surface:          {report.surface}",
        f"  Equipment class:  {report.equipment_class}",
        f"  Virtualization:   {report.virtualization}",
        f"  GPU hint:         {report.has_gpu_hint}",
        f"  Termux:           {report.termux}",
        f"  Profile:          {report.recommended_profile}",
        f"  Full CLI:         {report.supports_full_cli}",
    ]
    for note in report.notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines)
