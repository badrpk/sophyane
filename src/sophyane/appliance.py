"""Sophyane Appliance — OS-like boot on Linux-capable chips/SoCs.

This is not a from-scratch silicon bootloader. On any processor that can run
Linux (or a Linux container), Sophyane can be installed as an **appliance**
that:

1. Brings up networking (Ethernet cable and/or Wi‑Fi)
2. Boots the AI Kernel + mesh + hardware API
3. Optionally opens Sophyane Browser
4. Exposes a single ``sophyane --boot`` entry used by systemd or embedded init

Bare MCUs without an MMU still require a gateway SoC; the appliance targets
ARM/x86 boards, phones (Termux), industrial gateways, cloud VMs, and PCs.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
BOOT_LOG = STATE_DIR / "boot.log"
BOOT_STATE = STATE_DIR / "boot_state.json"


@dataclass
class BootReport:
    ok: bool
    version: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    network: dict[str, Any] = field(default_factory=dict)
    services: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n"
    with BOOT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()
    except Exception as error:  # noqa: BLE001
        return 1, str(error)


def _classify_iface(name: str) -> str:
    lower = name.lower().rstrip(":")
    if lower in {"lo", "localhost"}:
        return "loopback"
    if lower.startswith(("eth", "en", "em", "eno", "ens", "enp", "enx")):
        return "ethernet"
    if lower.startswith(("wl", "wlan", "wifi", "ath", "ra")):
        return "wifi"
    # sysfs: /sys/class/net/<name>/wireless or type.
    #
    # Android/Termux may expose entries that exist but cannot be stat'ed.
    # Network classification is best-effort, so restricted sysfs paths must
    # not abort appliance detection or the full feature audit.
    sys_net = Path(f"/sys/class/net/{lower}")
    try:
        if (sys_net / "wireless").exists() or (sys_net / "phy80211").exists():
            return "wifi"
    except OSError:
        pass

    type_file = sys_net / "type"
    try:
        if type_file.exists():
            # ARPHRD_ETHER=1; still ethernet vs wifi needs wireless naming
            # or a separately visible wireless directory.
            if type_file.read_text(encoding="utf-8").strip() == "1" and lower.startswith(
                ("eth", "en")
            ):
                return "ethernet"
    except OSError:
        pass

    return "other"


def detect_network_interfaces() -> dict[str, Any]:
    """List up interfaces; classify ethernet vs wifi when possible."""
    ifaces: list[dict[str, Any]] = []
    code, out = _run(["ip", "-brief", "addr"])
    if code != 0:
        code, out = _run(["ifconfig", "-a"])
    continuation_tokens = {
        "inet",
        "inet6",
        "ether",
        "txqueuelen",
        "rx",
        "tx",
        "collisions",
        "device",
    }

    for line in (out or "").splitlines():
        parts = line.split()
        if not parts:
            continue

        name = parts[0].rstrip(":")

        # Ignore warning/banner lines that are not interfaces
        if name.lower() in {
            "warning",
            "note",
            "error",
            "failed",
            "cannot",
        }:
            continue
        if name.lower() in continuation_tokens:
            continue

        # `ifconfig -a` continuation lines are normally indented. They contain
        # addresses and counters, not interface names.
        if line[:1].isspace() and not name.endswith(":"):
            continue

        kind = _classify_iface(name)
        state = "UP" if "UP" in line.upper() else "UNKNOWN"
        addrs = [p for p in parts[1:] if p.count(".") == 3 or ":" in p]
        ifaces.append(
            {
                "name": name,
                "kind": kind,
                "state": state,
                "addrs": addrs,
                "raw": line[:200],
            }
        )

    # Minimal Android environments may restrict both `ip` and `ifconfig`.
    # Python's socket interface list is non-mutating and usually remains
    # available, so use it as a final discovery fallback.
    if not ifaces:
        try:
            for _, name in socket.if_nameindex():
                ifaces.append(
                    {
                        "name": name,
                        "kind": _classify_iface(name),
                        "state": "UNKNOWN",
                        "addrs": [],
                        "raw": "socket.if_nameindex",
                    }
                )
        except (OSError, AttributeError):
            pass

    # Supplement with nmcli device list (catches wifi even if down / no addr)
    if shutil.which("nmcli"):
        _, nm_out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "dev"])
        known = {i["name"] for i in ifaces}
        for line in (nm_out or "").splitlines():
            parts = line.split(":")
            if len(parts) < 2:
                continue
            dev, typ = parts[0], parts[1]
            kind = "wifi" if typ == "wifi" else ("ethernet" if typ == "ethernet" else "other")
            if dev in known:
                for i in ifaces:
                    if i["name"] == dev and kind in {"wifi", "ethernet"}:
                        i["kind"] = kind
            elif kind in {"wifi", "ethernet"}:
                ifaces.append(
                    {
                        "name": dev,
                        "kind": kind,
                        "state": parts[2] if len(parts) > 2 else "UNKNOWN",
                        "addrs": [],
                        "raw": line[:200],
                    }
                )

    return {
        "hostname": socket.gethostname(),
        "interfaces": ifaces,
        "has_ethernet": any(i["kind"] == "ethernet" for i in ifaces),
        "has_wifi": any(i["kind"] == "wifi" for i in ifaces),
        "online_guess": any(
            i["kind"] in {"ethernet", "wifi"} and i.get("addrs") for i in ifaces
        ),
        "wifi_tools": {
            "nmcli": bool(shutil.which("nmcli")),
            "wpa_supplicant": bool(shutil.which("wpa_supplicant")),
            "dhclient": bool(shutil.which("dhclient")),
            "udhcpc": bool(shutil.which("udhcpc")),
        },
    }


def bring_up_network(
    *,
    wifi_ssid: str | None = None,
    wifi_psk: str | None = None,
) -> dict[str, Any]:
    """Best-effort network bring-up for cable Ethernet and Wi‑Fi.

    Uses NetworkManager (nmcli) when present; falls back to dhclient/ip.
    """
    actions: list[str] = []
    wifi_ssid = wifi_ssid or os.environ.get("SOPHYANE_WIFI_SSID", "").strip() or None
    wifi_psk = wifi_psk or os.environ.get("SOPHYANE_WIFI_PSK", "").strip() or None

    # Prefer NetworkManager
    if shutil.which("nmcli"):
        _run(["nmcli", "radio", "wifi", "on"])
        actions.append("nmcli wifi on")
        # Try DHCP on all ethernet devices
        code, out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "dev"])
        for line in (out or "").splitlines():
            parts = line.split(":")
            if len(parts) < 3:
                continue
            dev, typ, state = parts[0], parts[1], parts[2]
            if typ == "ethernet" and state in {"disconnected", "unavailable", "connected"}:
                c, o = _run(["nmcli", "dev", "connect", dev], timeout=30)
                actions.append(f"nmcli connect {dev}: {c} {o[:80]}")
        if wifi_ssid:
            if wifi_psk:
                c, o = _run(
                    [
                        "nmcli",
                        "dev",
                        "wifi",
                        "connect",
                        wifi_ssid,
                        "password",
                        wifi_psk,
                    ],
                    timeout=45,
                )
            else:
                c, o = _run(["nmcli", "dev", "wifi", "connect", wifi_ssid], timeout=45)
            actions.append(f"nmcli wifi {wifi_ssid}: {c} {o[:100]}")
    else:
        # Manual: try dhclient on eth* / en*
        net = detect_network_interfaces()
        for iface in net["interfaces"]:
            if iface["kind"] == "ethernet":
                _run(["ip", "link", "set", iface["name"], "up"])
                if shutil.which("dhclient"):
                    c, o = _run(["dhclient", iface["name"]], timeout=30)
                    actions.append(f"dhclient {iface['name']}: {c}")
                elif shutil.which("udhcpc"):
                    c, o = _run(["udhcpc", "-i", iface["name"]], timeout=30)
                    actions.append(f"udhcpc {iface['name']}: {c}")
        if wifi_ssid and shutil.which("wpa_supplicant") and shutil.which("wpa_passphrase"):
            conf = STATE_DIR / "wpa_supplicant.conf"
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            if wifi_psk:
                c, o = _run(["wpa_passphrase", wifi_ssid, wifi_psk])
                conf.write_text(
                    "ctrl_interface=/var/run/wpa_supplicant\nupdate_config=1\n" + o + "\n",
                    encoding="utf-8",
                )
            actions.append(f"wpa config written for {wifi_ssid} (start wpa_supplicant manually if needed)")

    net = detect_network_interfaces()
    # Connectivity probe
    online = False
    for host in ("1.1.1.1", "8.8.8.8"):
        c, _ = _run(["ping", "-c", "1", "-W", "2", host], timeout=5)
        if c == 0:
            online = True
            break
    net["online"] = online or net.get("online_guess")
    net["actions"] = actions
    return net


def _start_service(name: str, starter) -> dict[str, Any]:
    try:
        result = starter()
        if isinstance(result, dict):
            out = {"name": name, "ok": bool(result.get("ok", True)), **{k: v for k, v in result.items() if k != "ok"}}
            if not out["ok"]:
                _log(f"service {name} reported not ok: {result}")
            return out
        return {"name": name, "ok": True}
    except Exception as error:  # noqa: BLE001
        _log(f"service {name} failed: {error}")
        return {"name": name, "ok": False, "error": str(error)}


def network_capability_report(net: dict[str, Any] | None = None) -> dict[str, Any]:
    """Summarize cable Ethernet + Wi‑Fi readiness for appliance/chip installs."""
    net = net or detect_network_interfaces()
    return {
        "ethernet_present": bool(net.get("has_ethernet")),
        "wifi_present": bool(net.get("has_wifi")),
        "cable_path": "supported (nmcli/dhclient/udhcpc on eth*/en*)",
        "wifi_path": "supported (nmcli wifi connect or wpa_supplicant)",
        "online": bool(net.get("online") or net.get("online_guess")),
        "note": (
            "Containers (e.g. Crostini) often expose only eth0; Wi‑Fi is managed by the host. "
            "On bare metal / SBC images, both cable and Wi‑Fi interfaces appear when hardware exists."
        ),
    }


def boot_appliance(
    *,
    wifi_ssid: str | None = None,
    wifi_psk: str | None = None,
    open_browser: bool = False,
    start_mesh: bool = True,
    start_hardware_api: bool = True,
    start_kernel: bool = True,
) -> BootReport:
    """Full appliance boot sequence for chip/SoC/gateway hosts."""
    steps: list[dict[str, Any]] = []
    _log(f"boot start v{__version__}")

    # 1) Platform
    try:
        from sophyane.platform_probe import probe_platform

        platform = probe_platform().to_dict()
        steps.append({"step": "platform", "ok": True, "detail": platform})
    except Exception as error:  # noqa: BLE001
        platform = {}
        steps.append({"step": "platform", "ok": False, "error": str(error)})

    # 2) Network cable + wifi
    network = bring_up_network(wifi_ssid=wifi_ssid, wifi_psk=wifi_psk)
    network["capability"] = network_capability_report(network)
    steps.append(
        {
            "step": "network",
            "ok": bool(network.get("online") or network.get("interfaces")),
            "detail": network,
            "ethernet": network.get("has_ethernet"),
            "wifi": network.get("has_wifi"),
            "online": network.get("online"),
        }
    )

    services: dict[str, Any] = {}

    # 3) AI Kernel
    if start_kernel:
        def _kernel() -> dict[str, Any]:
            from sophyane.kernel import boot_kernel

            k = boot_kernel()
            st = k.status()
            return {"ok": bool(st.ok), "modules": len(st.modules)}

        services["kernel"] = _start_service("kernel", _kernel)
        steps.append({"step": "kernel", **services["kernel"]})

    # 4) Hardware API (idempotent — reuse if already listening)
    if start_hardware_api:
        def _hw() -> dict[str, Any]:
            from sophyane.hardware_api import create_default_api, ensure_hardware_api

            return ensure_hardware_api("0.0.0.0", 8770, create_default_api())

        services["hardware_api"] = _start_service("hardware_api", _hw)
        steps.append({"step": "hardware_api", **services["hardware_api"]})

    # 5) Mesh peer (idempotent)
    if start_mesh:
        def _mesh() -> dict[str, Any]:
            from sophyane.mesh.core import get_mesh_node

            return get_mesh_node(8777).serve_background(host="0.0.0.0")

        services["mesh"] = _start_service("mesh", _mesh)
        steps.append({"step": "mesh", **services["mesh"]})

    # 6) Optional browser
    if open_browser:
        def _browser() -> None:
            from sophyane.browser import launch_sophyane_browser

            launch_sophyane_browser(open_home=True, start_apis=False)

        services["browser"] = _start_service("browser", _browser)
        steps.append({"step": "browser", **services["browser"]})

    # 7) Self-improve heartbeat proposal on boot
    try:
        from sophyane.self_improve.ledger import propose_improvement

        propose_improvement(
            "benchmark",
            "appliance-boot",
            f"Booted Sophyane appliance v{__version__} on {platform.get('os_family')}/{platform.get('arch')}",
            evidence={
                "network_online": network.get("online"),
                "profile": platform.get("recommended_profile"),
                "ethernet": network.get("has_ethernet"),
                "wifi": network.get("has_wifi"),
            },
            score=0.1,
        )
        steps.append({"step": "improve_heartbeat", "ok": True})
    except Exception as error:  # noqa: BLE001
        steps.append({"step": "improve_heartbeat", "ok": False, "error": str(error)})

    # 8) Continual federated train tick (opt-in only; C++ PEFT on existing weights)
    if os.environ.get("SOPHYANE_TRAIN_ON_BOOT", "").lower() in {"1", "true", "yes"}:
        try:
            from sophyane.continual.engine import contribute_round, is_opted_in

            if is_opted_in():
                tr = contribute_round(publish_mesh=True)
                steps.append({"step": "continual_train", "ok": bool(tr.get("ok")), "detail": {
                    "local_ok": (tr.get("local") or {}).get("ok"),
                    "aggregate_ok": (tr.get("aggregate") or {}).get("ok"),
                }})
            else:
                steps.append({"step": "continual_train", "ok": True, "skipped": True, "reason": "not opted in"})
        except Exception as error:  # noqa: BLE001
            steps.append({"step": "continual_train", "ok": False, "error": str(error)})

    core_steps = {"platform", "kernel", "hardware_api", "mesh", "network"}
    ok = all(s.get("ok", True) for s in steps if s.get("step") in core_steps)
    report = BootReport(
        ok=ok,
        version=__version__,
        steps=steps,
        network=network,
        services=services,
        message=(
            "Sophyane appliance booted. "
            "This is an OS-like agent runtime on Linux-capable processors; "
            "not a bare-metal bootloader for MMU-less MCUs. "
            "Internet: Ethernet cable (DHCP) and Wi‑Fi (nmcli/wpa) are both supported."
        ),
    )
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    BOOT_STATE.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    _log(f"boot done ok={ok}")
    return report


def write_systemd_unit(path: Path | None = None) -> Path:
    """Write a user systemd unit to auto-boot Sophyane appliance."""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    path = path or (unit_dir / "sophyane-appliance.service")
    sophyane = shutil.which("sophyane") or str(Path.home() / ".local" / "bin" / "sophyane")
    content = f"""[Unit]
Description=Sophyane AI Appliance Boot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={sophyane} --boot --boot-foreground
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    path.write_text(content, encoding="utf-8")
    return path


def write_chip_install_script(path: Path | None = None) -> Path:
    """Emit a script that installs Sophyane appliance on Linux SoCs/chips with OS."""
    path = path or (Path.home() / ".local" / "bin" / "sophyane-install-chip")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = r'''#!/usr/bin/env bash
# Install Sophyane as an appliance on Linux-capable processors / SoCs / SBCs.
# Works on: Raspberry Pi, industrial ARM gateways, x86 boards, cloud VMs, Termux.
# Requires: Linux userland (not bare Cortex-M flash).
set -Eeuo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

echo "=== Sophyane Chip/SoC Appliance Installer ==="
if ! command -v python3 >/dev/null; then
  echo "python3 required" >&2; exit 1
fi
if ! command -v curl >/dev/null && ! command -v wget >/dev/null; then
  echo "curl or wget required" >&2; exit 1
fi

if command -v curl >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
else
  wget -qO- https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
fi

# Optional Wi‑Fi: export SOPHYANE_WIFI_SSID / SOPHYANE_WIFI_PSK before boot
sophyane --install-appliance-unit || true
if command -v systemctl >/dev/null; then
  systemctl --user daemon-reload || true
  systemctl --user enable --now sophyane-appliance.service || true
fi

sophyane --boot || true
echo "=== Boot complete. Mesh :8777 · Hardware API :8770 ==="
sophyane --platform || true
'''
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path
