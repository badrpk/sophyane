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
        "src/sophyane/mesh/discovery.py",
        "import",
        None,
        "struct",
    ),
    ForbiddenImport(
        "src/sophyane/mesh/install_peer.py",
        "import",
        None,
        "shlex",
    ),
    ForbiddenImport(
        "src/sophyane/providers/fallback.py",
        "from",
        "pathlib",
        "Path",
    ),
    ForbiddenImport(
        "src/sophyane/providers/openai_compatible.py",
        "from",
        "sophyane.providers.base",
        "ProviderMetadata",
    ),
    ForbiddenImport(
        "src/sophyane/self_improve/ledger.py",
        "import",
        None,
        "os",
    ),
]


def _tree(relative_path: str) -> ast.Module:
    source = (
        ROOT / relative_path
    ).read_text(encoding="utf-8")

    return ast.parse(source)


def test_batch_removes_targeted_unused_imports() -> None:
    remaining: list[tuple[str, str]] = []

    for target in FORBIDDEN:
        tree = _tree(target.relative_path)

        for node in ast.walk(tree):
            if (
                target.kind == "import"
                and isinstance(node, ast.Import)
            ):
                if any(
                    alias.name == target.name
                    for alias in node.names
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
            ):
                if any(
                    alias.name == target.name
                    for alias in node.names
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


def test_edited_modules_keep_real_definitions() -> None:
    for target in FORBIDDEN:
        tree = _tree(target.relative_path)

        definitions = [
            node.name
            for node in tree.body
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            )
        ]

        assert definitions, target.relative_path
