"""Hardware vendor registry and capability probe for Sophyane.

Catalogues top semiconductor vendors and detects which acceleration /
integration stacks are available on the *host* running Sophyane.

Important scope:
- Sophyane runs on hosts with a CPU/OS (or companion gateway).
- Memory vendors (e.g. Micron) appear as system memory context, not as
  instruction targets.
- Foundries (TSMC, GlobalFoundries) are catalogued for awareness only.
- Device drivers for PLCs/meters remain host integrations; this module
  declares *compatibility surfaces* and probes available toolchains.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# Top semiconductor / chip ecosystems Sophyane integrates with via host stacks.
CHIP_VENDORS: dict[str, dict[str, Any]] = {
    "nvidia": {
        "name": "NVIDIA",
        "classes": ["gpu", "dpu", "soc"],
        "proprietary_stacks": ["CUDA", "cuDNN", "TensorRT", "NVIDIA Driver", "JetPack"],
        "open_stacks": ["ONNX Runtime CUDA EP", "llama.cpp CUDA", "PyTorch CUDA", "Triton"],
        "detect": ["nvidia-smi", "/dev/nvidia0", "nvcc"],
    },
    "intel": {
        "name": "Intel",
        "classes": ["cpu", "gpu", "npu", "fpga"],
        "proprietary_stacks": ["oneAPI", "OpenVINO", "Intel GPU drivers", "OpenCL"],
        "open_stacks": ["ONNX Runtime OpenVINO EP", "llama.cpp", "oneDNN", "Level Zero"],
        "detect": ["lscpu:GenuineIntel", "lspci:Intel", "openvino"],
    },
    "amd": {
        "name": "AMD",
        "classes": ["cpu", "gpu"],
        "proprietary_stacks": ["ROCm", "HIP", "AMDGPU driver"],
        "open_stacks": ["ONNX Runtime ROCm EP", "llama.cpp HIP", "PyTorch ROCm"],
        "detect": ["rocm-smi", "lscpu:AuthenticAMD", "lspci:AMD"],
    },
    "qualcomm": {
        "name": "Qualcomm",
        "classes": ["soc", "npu", "modem"],
        "proprietary_stacks": ["Snapdragon SDK", "Hexagon SDK", "QNNPACK vendor tools"],
        "open_stacks": ["ONNX Runtime QNN EP", "TFLite Hexagon", "Termux ARM builds"],
        "detect": ["lscpu:Qualcomm", "getprop:ro.hardware", "uname:qcom"],
    },
    "amd_xilinx": {
        "name": "AMD Xilinx",
        "classes": ["fpga", "adaptive_soc"],
        "proprietary_stacks": ["Vitis", "Vivado"],
        "open_stacks": ["PYNQ", "OpenCL FPGA"],
        "detect": ["xbutil", "lspci:Xilinx"],
    },
    "apple": {
        "name": "Apple Silicon",
        "classes": ["soc", "gpu", "npu"],
        "proprietary_stacks": ["Metal", "Core ML", "ANE"],
        "open_stacks": ["llama.cpp Metal", "MLX", "ONNX Runtime CoreML EP"],
        "detect": ["sysctl:hw.optional.arm64", "uname:arm64-darwin"],
    },
    "arm": {
        "name": "Arm",
        "classes": ["cpu_ip", "npu_ip"],
        "proprietary_stacks": ["Arm NN vendor packs"],
        "open_stacks": ["llama.cpp ARM", "ONNX Runtime", "CMSIS-NN", "TVM"],
        "detect": ["lscpu:aarch64", "uname:arm", "uname:aarch64"],
    },
    "broadcom": {
        "name": "Broadcom",
        "classes": ["soc", "network"],
        "proprietary_stacks": ["Broadcom SDK (vendor)"],
        "open_stacks": ["Linux kernel drivers", "OpenWrt"],
        "detect": ["lspci:Broadcom", "cpuinfo:BCM"],
    },
    "mediatek": {
        "name": "MediaTek",
        "classes": ["soc"],
        "proprietary_stacks": ["MediaTek NeuroPilot"],
        "open_stacks": ["Android NDK", "ONNX Runtime", "TFLite"],
        "detect": ["getprop:mtk", "getprop:mediatek", "cpuinfo:MediaTek", "cpuinfo:MT67", "cpuinfo:MT68"],
    },
    "samsung": {
        "name": "Samsung",
        "classes": ["soc", "memory", "storage"],
        "proprietary_stacks": ["Exynos tools", "Samsung NN"],
        "open_stacks": ["Android NDK", "ONNX Runtime", "TFLite"],
        "detect": ["getprop:exynos", "cpuinfo:Exynos", "cpuinfo:Samsung"],
    },
    "micron": {
        "name": "Micron",
        "classes": ["memory", "storage"],
        "proprietary_stacks": ["Micron storage tools"],
        "open_stacks": ["Linux NVMe/SSD stack", "spdk"],
        "detect": ["nvme:Micron", "dmidecode:Micron"],
        "note": "Memory/storage vendor — Sophyane uses host memory; does not execute on DRAM dies.",
    },
    "sk_hynix": {
        "name": "SK hynix",
        "classes": ["memory", "storage"],
        "proprietary_stacks": ["Vendor storage tools"],
        "open_stacks": ["Linux NVMe stack"],
        "detect": ["nvme:Hynix", "dmidecode:Hynix"],
        "note": "Memory/storage vendor — host-level awareness only.",
    },
    "texas_instruments": {
        "name": "Texas Instruments",
        "classes": ["mcu", "dsp", "edge"],
        "proprietary_stacks": ["Code Composer Studio", "TI-RTOS"],
        "open_stacks": ["Zephyr", "Linux on Sitara", "MQTT edge gateways"],
        "detect": ["cpuinfo:Texas Instruments", "device-tree:ti,", "cpuinfo:Sitara"],
        "note": "Typically via gateway host, not bare MCU Python.",
    },
    "nxp": {
        "name": "NXP",
        "classes": ["mcu", "mpu", "auto"],
        "proprietary_stacks": ["MCUXpresso", "NXP eIQ"],
        "open_stacks": ["Yocto", "Zephyr", "Linux i.MX"],
        "detect": ["cpuinfo:NXP", "device-tree:fsl,", "cpuinfo:i.MX"],
    },
    "infineon": {
        "name": "Infineon",
        "classes": ["mcu", "power", "security"],
        "proprietary_stacks": ["ModusToolbox", "AURIX tools"],
        "open_stacks": ["Zephyr", "FreeRTOS", "edge gateway agents"],
        "detect": ["device-tree:infineon"],
    },
    "stmicro": {
        "name": "STMicroelectronics",
        "classes": ["mcu", "mpu", "sensors"],
        "proprietary_stacks": ["STM32Cube", "TouchGFX"],
        "open_stacks": ["Zephyr", "FreeRTOS", "Linux STM32MP"],
        "detect": ["device-tree:st,"],
    },
    "analog_devices": {
        "name": "Analog Devices",
        "classes": ["dsp", "analog", "edge"],
        "proprietary_stacks": ["CrossCore Embedded Studio"],
        "open_stacks": ["Linux IIO", "MQTT sensor hubs"],
        "detect": ["device-tree:adi,"],
    },
    "marvell": {
        "name": "Marvell",
        "classes": ["network", "soc", "storage"],
        "proprietary_stacks": ["Marvell SDK"],
        "open_stacks": ["Linux networking", "DPDK"],
        "detect": ["lspci:Marvell"],
    },
    "ibm": {
        "name": "IBM",
        "classes": ["cpu", "quantum_adjacent"],
        "proprietary_stacks": ["PowerAI vendor stacks"],
        "open_stacks": ["ONNX Runtime", "PyTorch CPU", "llama.cpp"],
        "detect": ["lscpu:POWER", "uname:ppc64"],
    },
    "tsmc": {
        "name": "TSMC",
        "classes": ["foundry"],
        "proprietary_stacks": [],
        "open_stacks": [],
        "detect": [],
        "note": "Foundry — not a host runtime target; chips it fabricates appear as other vendors.",
    },
    "globalfoundries": {
        "name": "GlobalFoundries",
        "classes": ["foundry"],
        "proprietary_stacks": [],
        "open_stacks": [],
        "detect": [],
        "note": "Foundry — not a host runtime target.",
    },
    "mediatek_edge": {
        "name": "MediaTek (edge alias)",
        "classes": ["soc"],
        "proprietary_stacks": ["NeuroPilot"],
        "open_stacks": ["Android NDK", "TFLite"],
        "detect": [],
    },
    "renesas": {
        "name": "Renesas",
        "classes": ["mcu", "auto"],
        "proprietary_stacks": ["e2 studio"],
        "open_stacks": ["Zephyr", "FreeRTOS"],
        "detect": ["device-tree:renesas"],
    },
    "microchip": {
        "name": "Microchip",
        "classes": ["mcu"],
        "proprietary_stacks": ["MPLAB X"],
        "open_stacks": ["Zephyr", "FreeRTOS", "Arduino-compatible hosts"],
        "detect": [],
    },
    "raspberry_pi_broadcom": {
        "name": "Raspberry Pi (Broadcom SoC)",
        "classes": ["soc", "sbc"],
        "proprietary_stacks": [],
        "open_stacks": ["Raspberry Pi OS", "llama.cpp", "ONNX Runtime"],
        "detect": ["cpuinfo:Raspberry", "device-tree:brcm,"],
    },
}


# Open-source / freeware integration surfaces Sophyane speaks to.
OPEN_SOFTWARE: dict[str, dict[str, Any]] = {
    "llama_cpp": {
        "name": "llama.cpp",
        "langs": ["C++", "Python bindings"],
        "role": "local GGUF inference",
        "detect": ["llama-server", "llama-cli"],
    },
    "onnxruntime": {
        "name": "ONNX Runtime",
        "langs": ["C++", "Python", "JS", "C#"],
        "role": "cross-vendor inference EP (CUDA/ROCm/OpenVINO/QNN/CoreML)",
        "detect": ["python:onnxruntime"],
    },
    "pytorch": {
        "name": "PyTorch",
        "langs": ["Python", "C++"],
        "role": "training/inference",
        "detect": ["python:torch"],
    },
    "tensorflow": {
        "name": "TensorFlow / TFLite",
        "langs": ["Python", "C++", "JS"],
        "role": "inference / mobile",
        "detect": ["python:tensorflow", "python:tflite"],
    },
    "ollama": {
        "name": "Ollama",
        "langs": ["Go", "HTTP API"],
        "role": "local model server",
        "detect": ["ollama"],
    },
    "openvino": {
        "name": "OpenVINO (open core)",
        "langs": ["C++", "Python"],
        "role": "Intel CPU/GPU/NPU acceleration",
        "detect": ["python:openvino"],
    },
    "modbus": {
        "name": "pymodbus / libmodbus",
        "langs": ["Python", "C"],
        "role": "PLC / meter industrial bus",
        "detect": ["python:pymodbus"],
    },
    "mqtt": {
        "name": "Eclipse Paho / mosquitto",
        "langs": ["Python", "C", "JS"],
        "role": "IoT messaging",
        "detect": ["python:paho", "mosquitto_pub"],
    },
    "opcua": {
        "name": "open62541 / asyncua",
        "langs": ["C", "Python"],
        "role": "industrial OPC-UA",
        "detect": ["python:asyncua"],
    },
    "nodejs": {
        "name": "Node.js",
        "langs": ["JS"],
        "role": "JS client / web bridges",
        "detect": ["node", "npm"],
    },
    "cpp_toolchain": {
        "name": "C/C++ toolchain",
        "langs": ["C", "C++"],
        "role": "native clients and edge embeds",
        "detect": ["g++", "clang++", "cmake"],
    },
}


@dataclass
class VendorPresence:
    vendor_id: str
    name: str
    present: bool
    evidence: list[str] = field(default_factory=list)
    stacks_detected: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SoftwarePresence:
    software_id: str
    name: str
    present: bool
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (completed.stdout or "") + (completed.stderr or "")
    except Exception:
        return ""


def _read_text(path: str, limit: int = 200_000) -> str:
    try:
        data = Path(path).read_text(encoding="utf-8", errors="ignore")
        return data[:limit]
    except Exception:
        return ""


def _python_importable(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _match_detect(token: str, cache: dict[str, str]) -> tuple[bool, str]:
    """Evaluate a detect token against host cache."""
    if token.startswith("python:"):
        mod = token.split(":", 1)[1]
        ok = _python_importable(mod)
        return ok, f"python import {mod}" if ok else ""
    if ":" in token and not token.startswith("/"):
        kind, needle = token.split(":", 1)
        blob = cache.get(kind, "")
        if needle.lower() in blob.lower():
            return True, f"{kind} contains {needle}"
        return False, ""
    if token.startswith("/"):
        exists = Path(token).exists()
        return exists, f"path {token}" if exists else ""
    # bare command
    path = shutil.which(token)
    return bool(path), f"command {path}" if path else ""


def _build_cache() -> dict[str, str]:
    cache: dict[str, str] = {
        "uname": platform.platform() + " " + platform.machine(),
        "lscpu": _run(["lscpu"]),
        "lspci": _run(["lspci"]),
        "cpuinfo": _read_text("/proc/cpuinfo"),
        "getprop": _run(["getprop"]),
        "sysctl": _run(["sysctl", "-a"]) if platform.system() == "Darwin" else "",
        "nvme": _run(["nvme", "list"]),
        "dmidecode": _run(["dmidecode", "-t", "memory"]),
        "device-tree": "",
    }
    # device-tree model/compatible blobs (ARM SBCs)
    for path in (
        "/proc/device-tree/model",
        "/proc/device-tree/compatible",
        "/sys/firmware/devicetree/base/compatible",
    ):
        cache["device-tree"] += " " + _read_text(path)
    return cache


def probe_vendors() -> list[VendorPresence]:
    cache = _build_cache()
    results: list[VendorPresence] = []
    for vendor_id, meta in CHIP_VENDORS.items():
        evidence: list[str] = []
        stacks: list[str] = []
        for token in meta.get("detect") or []:
            ok, how = _match_detect(token, cache)
            if ok and how:
                evidence.append(how)
        # stack tools
        for stack_cmd in (
            "nvidia-smi",
            "nvcc",
            "rocm-smi",
            "clinfo",
        ):
            if shutil.which(stack_cmd):
                # attribute loosely
                if vendor_id == "nvidia" and stack_cmd in {"nvidia-smi", "nvcc"}:
                    stacks.append(stack_cmd)
                if vendor_id == "amd" and stack_cmd == "rocm-smi":
                    stacks.append(stack_cmd)
                if vendor_id == "intel" and stack_cmd == "clinfo":
                    stacks.append(stack_cmd)
        present = bool(evidence) or bool(stacks)
        # foundries never "present" as compute hosts
        if "foundry" in meta.get("classes", []):
            present = False
        results.append(
            VendorPresence(
                vendor_id=vendor_id,
                name=str(meta["name"]),
                present=present,
                evidence=evidence,
                stacks_detected=stacks,
                note=str(meta.get("note") or ""),
            )
        )
    return results


def probe_open_software() -> list[SoftwarePresence]:
    cache = _build_cache()
    results: list[SoftwarePresence] = []
    for software_id, meta in OPEN_SOFTWARE.items():
        evidence: list[str] = []
        for token in meta.get("detect") or []:
            ok, how = _match_detect(token, cache)
            if ok and how:
                evidence.append(how)
        results.append(
            SoftwarePresence(
                software_id=software_id,
                name=str(meta["name"]),
                present=bool(evidence),
                evidence=evidence,
            )
        )
    return results


def recommended_backends(vendors: list[VendorPresence] | None = None) -> list[str]:
    vendors = vendors or probe_vendors()
    present = {v.vendor_id for v in vendors if v.present}
    backends: list[str] = ["cpu"]  # always
    if "nvidia" in present:
        backends.extend(["cuda", "tensorrt", "llama_cpp_cuda"])
    if "amd" in present:
        backends.extend(["rocm", "hip", "llama_cpp_hip"])
    if "intel" in present:
        backends.extend(["openvino", "onednn", "llama_cpp_cpu"])
    if "apple" in present:
        backends.extend(["metal", "coreml", "mlx", "llama_cpp_metal"])
    if "qualcomm" in present or "arm" in present:
        backends.extend(["qnn", "tflite", "llama_cpp_arm"])
    # de-dupe preserve order
    out: list[str] = []
    for item in backends:
        if item not in out:
            out.append(item)
    return out


def hardware_compatibility_report() -> dict[str, Any]:
    vendors = probe_vendors()
    software = probe_open_software()
    return {
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "vendors_catalogued": len(CHIP_VENDORS),
        "vendors_present": [v.to_dict() for v in vendors if v.present],
        "vendors_supported_catalog": [
            {
                "id": k,
                "name": v["name"],
                "classes": v["classes"],
                "proprietary_stacks": v.get("proprietary_stacks", []),
                "open_stacks": v.get("open_stacks", []),
                "note": v.get("note", ""),
            }
            for k, v in CHIP_VENDORS.items()
        ],
        "open_software": [s.to_dict() for s in software],
        "recommended_backends": recommended_backends(vendors),
        "languages": {
            "python": {"status": "native", "package": "sophyane"},
            "cpp": {"status": "client_library", "path": "sdk/cpp"},
            "javascript": {"status": "client_library", "path": "sdk/js"},
        },
        "api": {
            "http": "sophyane-web / hardware API routes",
            "python": "sophyane.hardware_api",
            "json_rpc": "POST /v1/hardware/*",
        },
        "scope_note": (
            "Sophyane is host-level intelligence: it integrates with chip vendor "
            "toolchains and open-source runtimes on the machine (or gateway) that "
            "runs Python/C++/JS clients. It does not execute on bare DRAM dies or "
            "replace PLC firmware."
        ),
    }


def format_hardware_report(report: dict[str, Any] | None = None) -> str:
    report = report or hardware_compatibility_report()
    lines = [
        "Sophyane hardware compatibility report",
        f"  Host: {report['host']['system']} {report['host']['machine']}",
        f"  Vendors in catalog: {report['vendors_catalogued']}",
        f"  Recommended backends: {', '.join(report['recommended_backends'])}",
        "  Present vendors:",
    ]
    present = report.get("vendors_present") or []
    if not present:
        lines.append("    (none auto-detected — catalog still supported via gateway/cloud)")
    for item in present:
        lines.append(
            f"    - {item['name']}: {', '.join(item.get('evidence') or ['detected'])}"
        )
    lines.append("  Open software detected:")
    for item in report.get("open_software") or []:
        if item.get("present"):
            lines.append(f"    - {item['name']}: {', '.join(item.get('evidence') or [])}")
    lines.append(f"  Note: {report.get('scope_note')}")
    return "\n".join(lines)
