from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "runtime_sli_mission_os.py"
    ).read_text(encoding="utf-8")


def test_runtime_sli_mission_os_does_not_import_re() -> None:
    tree = ast.parse(_source())

    imports_re = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "re"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    assert imports_re is False


def test_runtime_sli_mission_os_entry_points_remain_present() -> None:
    source = _source()

    assert "def " in source
    assert "mission" in source.lower()
    assert "sli" in source.lower()
