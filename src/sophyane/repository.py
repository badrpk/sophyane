"""Local Python repository inspection and dependency mapping."""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path
from typing import Any


IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
}


def find_repository_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()

    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate

    return current


def project_tree(root: Path, max_files: int = 300) -> str:
    lines = [f"Repository root: {root}"]
    count = 0

    for path in sorted(root.rglob("*")):
        if any(part in IGNORED_DIRECTORIES for part in path.parts):
            continue

        relative = path.relative_to(root)

        if path.is_dir():
            continue

        lines.append(str(relative))
        count += 1

        if count >= max_files:
            lines.append("... output truncated ...")
            break

    return "\n".join(lines)


def parse_python_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "imports": [],
        "functions": [],
        "classes": [],
        "calls": [],
        "error": None,
    }

    try:
        source = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as error:
        result["error"] = str(error)
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result["imports"].extend(
                alias.name for alias in node.names
            )

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            result["imports"].extend(
                f"{module}.{alias.name}".strip(".")
                for alias in node.names
            )

        elif isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            result["functions"].append(node.name)

        elif isinstance(node, ast.ClassDef):
            result["classes"].append(node.name)

        elif isinstance(node, ast.Call):
            function = node.func

            if isinstance(function, ast.Name):
                result["calls"].append(function.id)

            elif isinstance(function, ast.Attribute):
                result["calls"].append(function.attr)

    for key in ("imports", "functions", "classes", "calls"):
        result[key] = sorted(set(result[key]))

    return result


def dependency_map(root: Path | None = None) -> dict[str, Any]:
    repository_root = find_repository_root(root)
    src_root = repository_root / "src"

    search_root = src_root if src_root.exists() else repository_root

    files: dict[str, Any] = {}

    for path in search_root.rglob("*.py"):
        if any(part in IGNORED_DIRECTORIES for part in path.parts):
            continue

        files[str(path.relative_to(repository_root))] = (
            parse_python_file(path)
        )

    return {
        "root": str(repository_root),
        "files": files,
    }


def git_snapshot(root: Path | None = None) -> str:
    repository_root = find_repository_root(root)

    commands = [
        ["git", "status", "--short", "--branch"],
        ["git", "remote", "-v"],
        ["git", "log", "-5", "--oneline", "--decorate"],
    ]

    sections: list[str] = []

    for command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=repository_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            sections.append(
                f"$ {' '.join(command)}\nERROR: {error}"
            )
            continue

        output = result.stdout.strip()

        if result.stderr.strip():
            output += "\nSTDERR:\n" + result.stderr.strip()

        sections.append(
            f"$ {' '.join(command)}\n"
            f"{output or '[no output]'}"
        )

    return "\n\n".join(sections)


def repository_report(root: Path | None = None) -> str:
    repository_root = find_repository_root(root)

    return "\n\n".join(
        [
            "=== PROJECT TREE ===",
            project_tree(repository_root),
            "=== PYTHON DEPENDENCY MAP ===",
            json.dumps(
                dependency_map(repository_root),
                indent=2,
            ),
            "=== GIT SNAPSHOT ===",
            git_snapshot(repository_root),
        ]
    )
