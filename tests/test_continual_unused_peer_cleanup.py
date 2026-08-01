from __future__ import annotations

import ast
from pathlib import Path

from sophyane.continual import engine


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "continual"
        / "engine.py"
    ).read_text(encoding="utf-8")


def test_federated_aggregate_has_no_dead_peer_local() -> None:
    tree = ast.parse(_source())

    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "federated_aggregate"
    ]

    assert len(functions) == 1

    peer_names = [
        node.lineno
        for node in ast.walk(functions[0])
        if isinstance(node, ast.Name)
        and node.id == "peer"
    ]

    assert peer_names == []


def test_federated_aggregate_still_copies_local_adapter(
    tmp_path,
    monkeypatch,
) -> None:
    local_dir = tmp_path / "local"
    peers_dir = tmp_path / "peers"
    global_dir = tmp_path / "global"

    local_dir.mkdir()
    peers_dir.mkdir()
    global_dir.mkdir()

    (local_dir / "adapter.bin").write_bytes(b"weights")
    (local_dir / "adapter.json").write_text(
        '{"round": 1}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(engine, "LOCAL_DIR", local_dir)
    monkeypatch.setattr(engine, "PEERS_DIR", peers_dir)
    monkeypatch.setattr(engine, "GLOBAL_DIR", global_dir)
    monkeypatch.setattr(engine, "is_opted_in", lambda: True)
    monkeypatch.setattr(engine, "_ensure_dirs", lambda: None)

    def fake_run_core(arguments):
        assert arguments == [
            "aggregate",
            "--deltas",
            str(peers_dir),
            "--out",
            str(global_dir),
        ]

        (global_dir / "adapter.bin").write_bytes(
            b"global-weights"
        )

        return 0, '{"aggregated": true}'

    monkeypatch.setattr(
        engine,
        "_run_core",
        fake_run_core,
    )

    result = engine.federated_aggregate()

    assert (
        peers_dir / "self" / "adapter.bin"
    ).read_bytes() == b"weights"

    assert (
        peers_dir / "self" / "adapter.json"
    ).read_text(
        encoding="utf-8"
    ) == '{"round": 1}\n'

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["peers_pooled"] == 1
    assert result["meta"]["aggregated"] is True
