"""Discover Sophyane peers on LAN/WiFi and USB-attached hosts."""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MESH_PORT = int(os.environ.get("SOPHYANE_MESH_PORT", "8777"))
MESH_MAGIC = b"SOPHYANE_MESH_v1"
BROADCAST_PORT = int(os.environ.get("SOPHYANE_MESH_BCAST", "8778"))


@dataclass
class PeerInfo:
    peer_id: str
    hostname: str
    addresses: list[str] = field(default_factory=list)
    port: int = MESH_PORT
    transport: str = "lan"  # lan | usb | adb | manual
    capabilities: dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)
    reachable: bool = False
    version: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def base_url(self) -> str:
        host = self.addresses[0] if self.addresses else "127.0.0.1"
        return f"http://{host}:{self.port}"


def _local_ips() -> list[str]:
    ips: list[str] = []
    try:
        out = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "up"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        for line in (out.stdout or "").splitlines():
            parts = line.split()
            if "inet" in parts:
                idx = parts.index("inet")
                cidr = parts[idx + 1]
                ip = cidr.split("/")[0]
                if not ip.startswith("127."):
                    ips.append(ip)
    except Exception:
        pass
    if not ips:
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if not ip.startswith("127.") and ip not in ips:
                    ips.append(ip)
        except Exception:
            pass
    return ips


def _probe_mesh_url(url: str, timeout: float = 1.2) -> PeerInfo | None:
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/v1/mesh/hello",
            headers={"User-Agent": "SophyaneMesh/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            return None
        result = data.get("result") if "result" in data else data
        if not isinstance(result, dict):
            return None
        if result.get("magic") not in {"SOPHYANE_MESH_v1", "sophyane-mesh"}:
            # Accept health-shaped peers that declare mesh role
            if result.get("role") != "mesh-peer" and not result.get("peer_id"):
                return None
        addresses = list(result.get("addresses") or [])
        host = url.split("://", 1)[-1].split(":")[0]
        if host not in addresses:
            addresses.insert(0, host)
        return PeerInfo(
            peer_id=str(result.get("peer_id") or host),
            hostname=str(result.get("hostname") or host),
            addresses=addresses,
            port=int(result.get("port") or MESH_PORT),
            transport=str(result.get("transport") or "lan"),
            capabilities=dict(result.get("capabilities") or {}),
            last_seen=time.time(),
            reachable=True,
            version=str(result.get("version") or ""),
            note=str(result.get("note") or "mesh hello ok"),
        )
    except Exception:
        return None


def discover_lan_peers(
    *,
    port: int = MESH_PORT,
    timeout: float = 1.0,
    extra_hosts: list[str] | None = None,
) -> list[PeerInfo]:
    """Scan common LAN patterns + optional hosts for Sophyane mesh peers."""
    candidates: list[str] = []
    for ip in _local_ips():
        # same /24 for typical WiFi (skip link-local weirdness)
        parts = ip.split(".")
        if len(parts) == 4 and not ip.startswith("100."):  # skip some CGNAT chromeos
            base = ".".join(parts[:3])
            # limited scan of gateway-ish and nearby
            for last in list(range(1, 16)) + list(range(100, 110)) + [int(parts[3])]:
                host = f"{base}.{last}"
                if host != ip and host not in candidates:
                    candidates.append(host)
        # ChromeOS container often uses 100.115.x — probe neighbors lightly
        if ip.startswith("100.115."):
            parts = ip.split(".")
            base = ".".join(parts[:3])
            for last in range(max(1, int(parts[3]) - 3), min(254, int(parts[3]) + 4)):
                host = f"{base}.{last}"
                if host != ip and host not in candidates:
                    candidates.append(host)

    for host in extra_hosts or []:
        if host and host not in candidates:
            candidates.append(host)

    # Always try localhost mesh
    candidates = ["127.0.0.1"] + candidates

    peers: list[PeerInfo] = []
    seen: set[str] = set()

    def check(host: str) -> PeerInfo | None:
        return _probe_mesh_url(f"http://{host}:{port}", timeout=timeout)

    # Bound concurrency for low-RAM hosts
    workers = min(32, max(4, (os.cpu_count() or 2) * 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check, host): host for host in candidates[:80]}
        for fut in as_completed(futures):
            peer = fut.result()
            if peer and peer.peer_id not in seen:
                seen.add(peer.peer_id)
                peers.append(peer)
    return peers


def discover_usb_peers() -> list[PeerInfo]:
    """Detect USB serial and ADB-attached devices as potential mesh install targets."""
    peers: list[PeerInfo] = []

    # USB serial endpoints (gateways, MCUs with USB-CDC)
    serial_paths: list[Path] = []
    serial_paths.extend(Path("/dev").glob("ttyUSB*"))
    serial_paths.extend(Path("/dev").glob("ttyACM*"))
    by_id = Path("/dev/serial/by-id")
    if by_id.is_dir():
        serial_paths.extend(by_id.iterdir())
    seen_serial: set[str] = set()
    for path in serial_paths:
        if not path.exists():
            continue
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen_serial:
            continue
        seen_serial.add(key)
        peers.append(
            PeerInfo(
                peer_id=f"usb:{path.name}",
                hostname=path.name,
                addresses=[str(path)],
                port=0,
                transport="usb",
                capabilities={"serial": True, "path": str(path)},
                reachable=True,
                note="USB serial device — use gateway OS with SSH/ADB for full control",
            )
        )

    # ADB devices (Android phones/tablets)
    try:
        out = subprocess.run(
            ["adb", "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in (out.stdout or "").splitlines()[1:]:
            line = line.strip()
            if not line or "offline" in line:
                continue
            if "\tdevice" in line or line.endswith(" device") or " device " in line:
                serial = line.split()[0]
                peers.append(
                    PeerInfo(
                        peer_id=f"adb:{serial}",
                        hostname=serial,
                        addresses=[serial],
                        port=MESH_PORT,
                        transport="adb",
                        capabilities={"android": True, "adb": True},
                        reachable=True,
                        note="Android via ADB — can push Termux/Sophyane bootstrap",
                    )
                )
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # lsusb summary (inventory, not always installable)
    try:
        out = subprocess.run(
            ["lsusb"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for i, line in enumerate((out.stdout or "").splitlines()[:30]):
            line = line.strip()
            if not line:
                continue
            peers.append(
                PeerInfo(
                    peer_id=f"lsusb:{i}:{line[:40]}",
                    hostname="usb-device",
                    addresses=[],
                    port=0,
                    transport="usb",
                    capabilities={"lsusb": line},
                    reachable=False,
                    note=line,
                )
            )
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return peers


def broadcast_presence(payload: dict[str, Any], *, rounds: int = 2) -> int:
    """UDP broadcast so LAN peers can notice us (best-effort)."""
    message = MESH_MAGIC + b"|" + json.dumps(payload).encode("utf-8")
    sent = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.5)
    try:
        for _ in range(rounds):
            for bcast in ("255.255.255.255",):
                try:
                    sock.sendto(message, (bcast, BROADCAST_PORT))
                    sent += 1
                except OSError:
                    pass
            # subnet broadcasts
            for ip in _local_ips():
                parts = ip.split(".")
                if len(parts) == 4:
                    target = ".".join(parts[:3] + ["255"])
                    try:
                        sock.sendto(message, (target, BROADCAST_PORT))
                        sent += 1
                    except OSError:
                        pass
            time.sleep(0.05)
    finally:
        sock.close()
    return sent


def listen_broadcast(timeout: float = 2.0) -> list[dict[str, Any]]:
    """Listen briefly for mesh UDP advertisements."""
    found: list[dict[str, Any]] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", BROADCAST_PORT))
    except OSError:
        return found
    sock.settimeout(timeout)
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            if not data.startswith(MESH_MAGIC):
                continue
            try:
                payload = json.loads(data.split(b"|", 1)[1].decode("utf-8"))
            except Exception:
                continue
            payload["_from"] = addr[0]
            found.append(payload)
    finally:
        sock.close()
    return found


def discover_peers(
    *,
    include_usb: bool = True,
    include_lan: bool = True,
    extra_hosts: list[str] | None = None,
) -> list[PeerInfo]:
    peers: list[PeerInfo] = []
    if include_lan:
        # announce ourselves then scan
        try:
            from sophyane.version import __version__

            broadcast_presence(
                {
                    "peer_id": socket.gethostname(),
                    "hostname": socket.gethostname(),
                    "port": MESH_PORT,
                    "version": __version__,
                    "addresses": _local_ips(),
                }
            )
        except Exception:
            pass
        peers.extend(discover_lan_peers(extra_hosts=extra_hosts))
        for adv in listen_broadcast(timeout=1.0):
            host = str(adv.get("_from") or "")
            if not host:
                continue
            peer = _probe_mesh_url(f"http://{host}:{adv.get('port') or MESH_PORT}")
            if peer and all(p.peer_id != peer.peer_id for p in peers):
                peers.append(peer)
    if include_usb:
        peers.extend(discover_usb_peers())
    return peers
