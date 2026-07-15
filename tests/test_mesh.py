from __future__ import annotations

import json
from pathlib import Path

from sophyane.mesh.core import MeshNode
from sophyane.mesh.discovery import PeerInfo, discover_usb_peers
from sophyane.mesh.federation import local_share_stats, pick_best_compute_peer
from sophyane.mesh.install_peer import install_on_peer


def test_mesh_hello_and_status() -> None:
    node = MeshNode(port=18777)
    hello = node.hello()
    assert hello["magic"] == "SOPHYANE_MESH_v1"
    assert hello["peer_id"]
    status = node.status()
    assert status["ok"] is True
    assert "share" in status
    caps = node.handle("capabilities")
    assert caps["ok"] is True


def test_mesh_storage_put_get(tmp_path: Path, monkeypatch) -> None:
    import sophyane.mesh.core as core

    monkeypatch.setattr(core, "SHARE_DIR", tmp_path / "share")
    node = MeshNode(port=18778)
    put = node.handle("storage.put", {"name": "note.txt", "content": "hello-mesh"})
    assert put.get("ok") is True
    got = node.handle("storage.get", {"name": "note.txt"})
    assert got.get("ok") is True
    assert got.get("content") == "hello-mesh"
    listed = local_share_stats(tmp_path / "share")
    assert listed["files"] >= 1


def test_mesh_exec_allowlist() -> None:
    node = MeshNode(port=18779)
    bad = node.handle("exec", {"command": "rm -rf /"})
    assert bad.get("ok") is False
    good = node.handle("exec", {"command": "hostname"})
    assert good.get("ok") is True
    assert good.get("output")


def test_install_requires_approval() -> None:
    peer = PeerInfo("p1", "host", ["127.0.0.1"], transport="lan")
    result = install_on_peer(peer, approve=False)
    assert result.ok is False
    assert "approve" in result.message.lower() or "Refused" in result.message


def test_pick_best_compute_peer() -> None:
    peers = [
        PeerInfo("a", "a", ["10.0.0.1"], transport="lan", reachable=True, capabilities={"ram_mb": 2000, "cpus": 2}),
        PeerInfo("b", "b", ["10.0.0.2"], transport="lan", reachable=True, capabilities={"ram_mb": 8000, "cpus": 4, "has_gpu": True}),
        PeerInfo("c", "c", ["usb"], transport="usb", reachable=False),
    ]
    best = pick_best_compute_peer(peers)
    assert best is not None
    assert best.peer_id == "b"


def test_discover_usb_does_not_crash() -> None:
    peers = discover_usb_peers()
    assert isinstance(peers, list)
