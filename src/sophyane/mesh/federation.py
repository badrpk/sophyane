"""Shared compute and storage across Sophyane mesh peers."""

from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sophyane.mesh.discovery import PeerInfo


@dataclass
class RemoteTaskResult:
    ok: bool
    peer_id: str
    output: str
    error: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _post(url: str, payload: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "SophyaneMesh/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {error.code}: {body[:500]}"}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": str(error)}


def _get(url: str, timeout: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "SophyaneMesh/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": str(error)}


def remote_chat(peer: PeerInfo, message: str, *, edge: bool = True) -> RemoteTaskResult:
    started = time.perf_counter()
    payload = _post(
        peer.base_url + "/v1/hardware/chat",
        {"message": message, "edge": edge},
        timeout=120.0,
    )
    ms = (time.perf_counter() - started) * 1000
    if payload.get("ok") and payload.get("reply"):
        return RemoteTaskResult(True, peer.peer_id, str(payload["reply"]), duration_ms=ms)
    # unwrap {ok,result}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if isinstance(result, dict) and result.get("reply"):
        return RemoteTaskResult(True, peer.peer_id, str(result["reply"]), duration_ms=ms)
    return RemoteTaskResult(
        False,
        peer.peer_id,
        "",
        error=str(payload.get("error") or payload)[:500],
        duration_ms=ms,
    )


def remote_capabilities(peer: PeerInfo) -> dict[str, Any]:
    data = _get(peer.base_url + "/v1/mesh/capabilities")
    if "result" in data:
        return data["result"] if isinstance(data["result"], dict) else data
    return data


def remote_storage_list(peer: PeerInfo) -> dict[str, Any]:
    return _get(peer.base_url + "/v1/mesh/storage")


def remote_storage_put(
    peer: PeerInfo,
    name: str,
    content: str,
    *,
    token: str = "",
) -> dict[str, Any]:
    return _post(
        peer.base_url + "/v1/mesh/storage/put",
        {"name": name, "content": content, "token": token},
    )


def remote_storage_get(peer: PeerInfo, name: str) -> dict[str, Any]:
    return _post(peer.base_url + "/v1/mesh/storage/get", {"name": name})


def remote_exec_safe(peer: PeerInfo, command: str, *, token: str = "") -> RemoteTaskResult:
    """Ask peer to run an allowlisted safe command (peer enforces policy)."""
    started = time.perf_counter()
    payload = _post(
        peer.base_url + "/v1/mesh/exec",
        {"command": command, "token": token},
        timeout=90.0,
    )
    ms = (time.perf_counter() - started) * 1000
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if isinstance(result, dict) and result.get("ok"):
        return RemoteTaskResult(
            True,
            peer.peer_id,
            str(result.get("output") or ""),
            duration_ms=ms,
        )
    return RemoteTaskResult(
        False,
        peer.peer_id,
        "",
        error=str((result or payload).get("error") if isinstance(result, dict) else payload)[:500],
        duration_ms=ms,
    )


def pick_best_compute_peer(peers: list[PeerInfo]) -> PeerInfo | None:
    """Prefer reachable LAN peers with most advertised RAM/CPUs."""
    ranked: list[tuple[float, PeerInfo]] = []
    for peer in peers:
        if not peer.reachable or peer.transport not in {"lan", "manual"}:
            continue
        caps = peer.capabilities or {}
        score = float(caps.get("ram_mb") or 0) + 100 * float(caps.get("cpus") or 0)
        if caps.get("has_gpu"):
            score += 5000
        ranked.append((score, peer))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def local_share_stats(share_dir: Path) -> dict[str, Any]:
    share_dir.mkdir(parents=True, exist_ok=True)
    files = [p for p in share_dir.iterdir() if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    disk = shutil.disk_usage(str(share_dir))
    return {
        "path": str(share_dir),
        "files": len(files),
        "bytes": total,
        "disk_free_mb": disk.free // (1024 * 1024),
        "disk_total_mb": disk.total // (1024 * 1024),
        "names": sorted(p.name for p in files)[:100],
    }
