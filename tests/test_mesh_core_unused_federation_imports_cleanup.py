from __future__ import annotations

import ast
from pathlib import Path


def _tree() -> ast.Module:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "mesh"
        / "core.py"
    ).read_text(encoding="utf-8")

    return ast.parse(source)


def test_mesh_core_does_not_import_unused_federation_helpers() -> None:
    forbidden: list[str] = []

    for node in ast.walk(_tree()):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "sophyane.mesh.federation"
        ):
            forbidden.extend(
                alias.name
                for alias in node.names
                if alias.name in {
                    "remote_capabilities",
                    "remote_exec_safe",
                }
            )

    assert forbidden == []


def test_mesh_core_preserves_required_federation_helpers() -> None:
    imported = {
        alias.name
        for node in ast.walk(_tree())
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "sophyane.mesh.federation"
        )
        for alias in node.names
    }

    assert {
        "local_share_stats",
        "pick_best_compute_peer",
        "remote_chat",
        "remote_storage_get",
        "remote_storage_list",
        "remote_storage_put",
    } <= imported
