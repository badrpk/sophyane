"""Mesh node: serve peers, discover, install clones, share compute/storage."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sophyane.hardware_registry import recommended_backends
from sophyane.mesh.discovery import (
    MESH_PORT,
    PeerInfo,
    discover_peers,
    _local_ips,
)
from sophyane.mesh.federation import (
    local_share_stats,
    pick_best_compute_peer,
    remote_capabilities,
    remote_chat,
    remote_exec_safe,
    remote_storage_get,
    remote_storage_list,
    remote_storage_put,
)
from sophyane.mesh.install_peer import install_on_peer
from sophyane.platform_probe import probe_platform
from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
MESH_STATE = STATE_DIR / "mesh.json"
SHARE_DIR = STATE_DIR / "mesh_share"
MESH_TOKEN = os.environ.get("SOPHYANE_MESH_TOKEN", "").strip()

# Extremely small allowlist for remote exec (peer-enforced).
SAFE_EXEC = {
    "uname -a",
    "uptime",
    "nproc",
    "df -h",
    "free -h",
    "hostname",
    "sophyane --version",
    "sophyane --platform",
    "sophyane --edge-health",
    "sophyane --kernel-status",
}


def _peer_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()).hex[:8]}"


class MeshNode:
    def __init__(self, port: int = MESH_PORT) -> None:
        self.port = port
        self.peer_id = _peer_id()
        self.hostname = socket.gethostname()
        self.peers: dict[str, PeerInfo] = {}
        self.started_at = time.time()
        SHARE_DIR.mkdir(parents=True, exist_ok=True)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def local_capabilities(self) -> dict[str, Any]:
        platform = probe_platform()
        share = local_share_stats(SHARE_DIR)
        return {
            "peer_id": self.peer_id,
            "hostname": self.hostname,
            "version": __version__,
            "port": self.port,
            "addresses": _local_ips(),
            "cpus": platform.cpus,
            "ram_mb": platform.ram_mb,
            "disk_free_mb": platform.disk_free_mb,
            "equipment_class": platform.equipment_class,
            "profile": platform.recommended_profile,
            "backends": recommended_backends(),
            "has_gpu": platform.has_gpu_hint,
            "share": share,
            "role": "mesh-peer",
            "magic": "SOPHYANE_MESH_v1",
            "control": True,
            "storage": True,
            "compute": True,
        }

    def hello(self) -> dict[str, Any]:
        caps = self.local_capabilities()
        return {
            "magic": "SOPHYANE_MESH_v1",
            "role": "mesh-peer",
            "peer_id": self.peer_id,
            "hostname": self.hostname,
            "version": __version__,
            "port": self.port,
            "addresses": caps["addresses"],
            "transport": "lan",
            "capabilities": {
                "cpus": caps["cpus"],
                "ram_mb": caps["ram_mb"],
                "disk_free_mb": caps["disk_free_mb"],
                "has_gpu": caps["has_gpu"],
                "backends": caps["backends"],
            },
            "note": "Sophyane mesh peer ready",
        }

    def discover(self, *, include_usb: bool = True) -> list[dict[str, Any]]:
        found = discover_peers(include_usb=include_usb, include_lan=True)
        for peer in found:
            # don't register pure lsusb inventory rows as control peers
            if peer.transport == "usb" and not peer.reachable and "lsusb" in (peer.capabilities or {}):
                if not str(peer.capabilities.get("lsusb", "")).lower().startswith("bus "):
                    pass
            self.peers[peer.peer_id] = peer
        self._save()
        return [p.to_dict() for p in self.peers.values()]

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "peer_id": self.peer_id,
            "hostname": self.hostname,
            "version": __version__,
            "port": self.port,
            "uptime_s": time.time() - self.started_at,
            "serving": self._server is not None,
            "local": self.local_capabilities(),
            "peers": [p.to_dict() for p in self.peers.values()],
            "share": local_share_stats(SHARE_DIR),
            "mesh_token_required": bool(MESH_TOKEN),
        }

    def install_peer(self, peer_id: str, *, yes: bool = False, ssh_user: str = "") -> dict[str, Any]:
        peer = self.peers.get(peer_id)
        if peer is None:
            # try address as id
            for candidate in self.peers.values():
                if peer_id in candidate.addresses or peer_id == candidate.hostname:
                    peer = candidate
                    break
        if peer is None:
            return {"ok": False, "error": f"unknown peer: {peer_id}"}
        result = install_on_peer(peer, ssh_user=ssh_user, approve=yes)
        return result.to_dict()

    def use_peer_compute(self, message: str, peer_id: str | None = None) -> dict[str, Any]:
        peer: PeerInfo | None = None
        if peer_id:
            peer = self.peers.get(peer_id)
        if peer is None:
            peer = pick_best_compute_peer(list(self.peers.values()))
        if peer is None:
            return {"ok": False, "error": "no reachable compute peer; run mesh discover"}
        result = remote_chat(peer, message, edge=True)
        return result.to_dict()

    def use_peer_storage(
        self,
        action: str,
        name: str = "",
        content: str = "",
        peer_id: str | None = None,
    ) -> dict[str, Any]:
        peer = self.peers.get(peer_id) if peer_id else None
        if peer is None:
            for candidate in self.peers.values():
                if candidate.reachable and candidate.transport in {"lan", "manual"}:
                    peer = candidate
                    break
        if peer is None:
            return {"ok": False, "error": "no storage peer"}
        if action == "list":
            return remote_storage_list(peer)
        if action == "put":
            return remote_storage_put(peer, name, content, token=MESH_TOKEN)
        if action == "get":
            return remote_storage_get(peer, name)
        return {"ok": False, "error": f"unknown storage action: {action}"}

    def handle(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if method in {"hello", "mesh.hello"}:
            return {"ok": True, "result": self.hello()}
        if method in {"capabilities", "mesh.capabilities"}:
            return {"ok": True, "result": self.local_capabilities()}
        if method in {"status", "mesh.status"}:
            return {"ok": True, "result": self.status()}
        if method in {"discover", "mesh.discover"}:
            return {
                "ok": True,
                "result": self.discover(include_usb=bool(params.get("usb", True))),
            }
        if method == "install":
            return self.install_peer(
                str(params.get("peer_id") or ""),
                yes=bool(params.get("yes")),
                ssh_user=str(params.get("ssh_user") or ""),
            )
        if method == "compute":
            return self.use_peer_compute(
                str(params.get("message") or params.get("prompt") or ""),
                peer_id=params.get("peer_id"),
            )
        if method == "storage":
            return self.use_peer_storage(
                str(params.get("action") or "list"),
                name=str(params.get("name") or ""),
                content=str(params.get("content") or ""),
                peer_id=params.get("peer_id"),
            )
        if method == "exec":
            return self._local_exec(
                str(params.get("command") or ""),
                token=str(params.get("token") or ""),
            )
        if method == "storage.put":
            return self._storage_put(params)
        if method == "storage.get":
            return self._storage_get(params)
        if method == "storage.list":
            return {"ok": True, "result": local_share_stats(SHARE_DIR)}
        if method.startswith("train.") or method in {
            "train",
            "train.status",
            "train.opt_in",
            "train.record",
            "train.step",
            "train.contribute",
            "train.aggregate",
            "train.round",
        }:
            from sophyane.continual.engine import handle_train_rpc

            return handle_train_rpc(method if method.startswith("train.") else f"train.{method}", params)
        return {"ok": False, "error": f"unknown mesh method: {method}"}

    def _check_token(self, token: str) -> bool:
        if not MESH_TOKEN:
            return True
        return token == MESH_TOKEN

    def _local_exec(self, command: str, *, token: str = "") -> dict[str, Any]:
        if not self._check_token(token):
            return {"ok": False, "error": "invalid mesh token"}
        command = command.strip()
        if command not in SAFE_EXEC:
            return {
                "ok": False,
                "error": "command not allowlisted",
                "allowed": sorted(SAFE_EXEC),
            }
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            return {
                "ok": completed.returncode == 0,
                "output": output[-8000:],
                "exit_code": completed.returncode,
            }
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "error": str(error)}

    def _storage_put(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._check_token(str(params.get("token") or "")):
            return {"ok": False, "error": "invalid mesh token"}
        name = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(params.get("name") or "blob"))
        content = str(params.get("content") or "")
        if len(content.encode("utf-8")) > 5_000_000:
            return {"ok": False, "error": "content too large (5MB max in v1)"}
        path = SHARE_DIR / name
        path.write_text(content, encoding="utf-8")
        return {"ok": True, "name": name, "bytes": path.stat().st_size}

    def _storage_get(self, params: dict[str, Any]) -> dict[str, Any]:
        name = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(params.get("name") or ""))
        path = SHARE_DIR / name
        if not path.exists():
            return {"ok": False, "error": "not found"}
        return {"ok": True, "name": name, "content": path.read_text(encoding="utf-8", errors="replace")}

    def _save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "peer_id": self.peer_id,
            "peers": [p.to_dict() for p in self.peers.values()],
            "saved_at": time.time(),
        }
        MESH_STATE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def serve(self, host: str = "0.0.0.0") -> ThreadingHTTPServer:
        node = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

            def _send(self, code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path.rstrip("/")
                mapping = {
                    "/v1/mesh/hello": "hello",
                    "/v1/mesh/capabilities": "capabilities",
                    "/v1/mesh/status": "status",
                    "/v1/mesh/storage": "storage.list",
                    "/v1/mesh/train": "train.status",
                    "/v1/mesh/train/status": "train.status",
                }
                method = mapping.get(path)
                if not method:
                    self._send(404, {"ok": False, "error": "not found"})
                    return
                self._send(200, node.handle(method))

            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path.rstrip("/")
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    params = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send(400, {"ok": False, "error": "invalid json"})
                    return
                if not isinstance(params, dict):
                    params = {}
                # Also expose hardware chat for federation compute
                if path in {"/v1/hardware/chat", "/v1/chat"}:
                    from sophyane.hardware_api import create_default_api

                    api = create_default_api()
                    self._send(200, api.dispatch("chat", params))
                    return
                mapping = {
                    "/v1/mesh/discover": "discover",
                    "/v1/mesh/install": "install",
                    "/v1/mesh/compute": "compute",
                    "/v1/mesh/storage": "storage",
                    "/v1/mesh/storage/put": "storage.put",
                    "/v1/mesh/storage/get": "storage.get",
                    "/v1/mesh/exec": "exec",
                    "/v1/mesh/rpc": "rpc",
                    "/v1/mesh/train/contribute": "train.contribute",
                    "/v1/mesh/train/step": "train.step",
                    "/v1/mesh/train/aggregate": "train.aggregate",
                    "/v1/mesh/train/round": "train.round",
                    "/v1/mesh/train/opt_in": "train.opt_in",
                    "/v1/mesh/train/record": "train.record",
                }
                method = mapping.get(path)
                if path == "/v1/mesh/rpc":
                    method = str(params.get("method") or "")
                    params = params.get("params") if isinstance(params.get("params"), dict) else {}
                if not method:
                    self._send(404, {"ok": False, "error": "not found"})
                    return
                self._send(200, node.handle(method, params))

        server = ThreadingHTTPServer((host, self.port), Handler)
        self._server = server
        return server

    def _probe_local_hello(self) -> bool:
        """True if something already answers mesh hello on this port."""
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1.0):
                pass
        except OSError:
            return False
        try:
            import urllib.request

            url = f"http://127.0.0.1:{self.port}/v1/mesh/hello"
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            # Responses may be flat or wrapped as {"ok": true, "result": {...}}
            magic = data.get("magic")
            if magic is None and isinstance(data.get("result"), dict):
                magic = data["result"].get("magic")
            return magic == "SOPHYANE_MESH_v1"
        except Exception:  # noqa: BLE001
            return False

    def serve_background(self, host: str = "0.0.0.0") -> dict[str, Any]:
        """Start mesh HTTP in a daemon thread. Idempotent if already listening."""
        if self._thread and self._thread.is_alive():
            return {"ok": True, "reused": True, "port": self.port}
        try:
            server = self.serve(host=host)
        except OSError as error:
            # Address already in use — another Sophyane (or prior boot) holds the port.
            if getattr(error, "errno", None) in {98, 48} or "Address already in use" in str(error):
                if self._probe_local_hello():
                    return {
                        "ok": True,
                        "reused": True,
                        "port": self.port,
                        "note": "mesh already listening",
                    }
            raise

        def run() -> None:
            server.serve_forever()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return {"ok": True, "reused": False, "port": self.port}


_NODE: MeshNode | None = None


def get_mesh_node(port: int | None = None) -> MeshNode:
    global _NODE
    if _NODE is None:
        _NODE = MeshNode(port=port or MESH_PORT)
    return _NODE


def mesh_status() -> dict[str, Any]:
    return get_mesh_node().status()
