from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).parents[1]


@dataclass(frozen=True)
class ForbiddenImport:
    relative_path: str
    kind: str
    module: str | None
    name: str


FORBIDDEN = [
    ForbiddenImport(
        "tests/test_browser_partial_recovery.py",
        "from",
        "pathlib",
        "Path",
    ),
    ForbiddenImport(
        "tests/test_future_agent.py",
        "from",
        "sophyane.hitl",
        "list_pending",
    ),
    ForbiddenImport(
        "tests/test_mesh.py",
        "import",
        None,
        "json",
    ),
    ForbiddenImport(
        (
            "tests/"
            "test_new_tab_preview_and_gemini_tool_guard.py"
        ),
        "from",
        "types",
        "SimpleNamespace",
    ),
    ForbiddenImport(
        "tests/test_runtime_root_scan_guard.py",
        "import",
        None,
        "tempfile",
    ),
    ForbiddenImport(
        "tests/test_runtime_root_scan_guard.py",
        "from",
        "pathlib",
        "Path",
    ),
    ForbiddenImport(
        "tests/test_state_graph_unittest.py",
        "from",
        "sophyane.state_graph",
        "START",
    ),
]


def _tree(relative_path: str) -> ast.Module:
    source = (
        ROOT / relative_path
    ).read_text(encoding="utf-8")

    return ast.parse(source)


def test_batch_removes_test_only_dead_imports() -> None:
    remaining: list[tuple[str, str]] = []

    for target in FORBIDDEN:
        tree = _tree(target.relative_path)

        for node in ast.walk(tree):
            if (
                target.kind == "import"
                and isinstance(node, ast.Import)
                and any(
                    alias.name == target.name
                    for alias in node.names
                )
            ):
                remaining.append(
                    (
                        target.relative_path,
                        target.name,
                    )
                )

            elif (
                target.kind == "from"
                and isinstance(node, ast.ImportFrom)
                and node.module == target.module
                and any(
                    alias.name == target.name
                    for alias in node.names
                )
            ):
                remaining.append(
                    (
                        target.relative_path,
                        (
                            f"{target.module}."
                            f"{target.name}"
                        ),
                    )
                )

    assert remaining == []


def test_edited_test_modules_keep_tests() -> None:
    paths = {
        target.relative_path
        for target in FORBIDDEN
    }

    for relative_path in paths:
        tree = _tree(relative_path)

        top_level_tests = [
            node.name
            for node in tree.body
            if (
                isinstance(
                    node,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                    ),
                )
                and node.name.startswith("test")
            )
        ]

        test_classes = [
            node.name
            for node in tree.body
            if (
                isinstance(node, ast.ClassDef)
                and (
                    node.name.startswith("Test")
                    or any(
                        isinstance(
                            child,
                            (
                                ast.FunctionDef,
                                ast.AsyncFunctionDef,
                            ),
                        )
                        and child.name.startswith("test")
                        for child in node.body
                    )
                )
            )
        ]

        assert (
            top_level_tests or test_classes
        ), relative_path
