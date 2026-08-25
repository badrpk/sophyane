from __future__ import annotations

import ast
from pathlib import Path


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "task_execution.py"
    ).read_text(
        encoding="utf-8"
    )


def test_task_execution_sys_import_is_semantically_used() -> None:
    source = _source()
    tree = ast.parse(source)

    imports_sys = any(
        isinstance(node, ast.Import)
        and any(
            alias.name == "sys"
            for alias in node.names
        )
        for node in ast.walk(tree)
    )

    sys_attribute_uses = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
        )
    ]

    assert imports_sys is True
    assert sys_attribute_uses


def test_compiled_task_uses_current_python_interpreter() -> None:
    source = _source()

    assert "sys.executable" in source
    assert "subprocess.run(" in source
