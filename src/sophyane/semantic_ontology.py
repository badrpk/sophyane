"""Evidence-based startup ontology report for Sophyane."""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


CATEGORIES = (
    "domains",
    "intents",
    "profiles",
    "actions",
    "capabilities",
    "policies",
    "learned_concepts",
)

SOURCE_HINTS = (
    "ontology",
    "semantic",
    "sli",
    "intent",
    "capability",
    "execution",
    "adaptive",
    "planner",
    "router",
    "tool",
    "provider",
)

RUNTIME_HINTS = (
    "ontology",
    "semantic",
    "sli",
    "intent",
    "capability",
    "concept",
    "memory",
    "learn",
)

SKIP_DIRS = {
    ".git",
    ".cache",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "build",
    "dist",
}

NAME_MAP = {
    "domain": "domains",
    "domains": "domains",
    "intent": "intents",
    "intents": "intents",
    "profile": "profiles",
    "profiles": "profiles",
    "task_type": "profiles",
    "task_types": "profiles",
    "action": "actions",
    "actions": "actions",
    "tool": "actions",
    "tools": "actions",
    "operation": "actions",
    "operations": "actions",
    "capability": "capabilities",
    "capabilities": "capabilities",
    "policy": "policies",
    "policies": "policies",
    "mode": "policies",
    "modes": "policies",
    "constraint": "policies",
    "constraints": "policies",
    "concept": "learned_concepts",
    "concepts": "learned_concepts",
    "entity": "learned_concepts",
    "entities": "learned_concepts",
    "relation": "learned_concepts",
    "relations": "learned_concepts",
    "predicate": "learned_concepts",
    "predicates": "learned_concepts",
    "label": "learned_concepts",
    "labels": "learned_concepts",
}


def _normalise(value: Any) -> str | None:
    if value is None or isinstance(value, (bool, int, float)):
        return None

    text = " ".join(str(value).strip().split())

    if not text:
        return None

    if len(text) > 100:
        return None

    if text.count(" ") > 8:
        return None

    if text.startswith(("http://", "https://")):
        return None

    if "/" in text and " " not in text:
        return None

    if not re.search(r"[A-Za-z]", text):
        return None

    return text


def _category_for_name(name: str) -> str | None:
    lowered = name.lower().strip("_")

    if lowered in NAME_MAP:
        return NAME_MAP[lowered]

    parts = lowered.split("_")

    for part in parts:
        if part in NAME_MAP:
            return NAME_MAP[part]

    for key, category in NAME_MAP.items():
        if lowered.endswith(key):
            return category

    return None


def _collect_literal(
    value: Any,
    category: str,
    collected: dict[str, set[str]],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_category = _category_for_name(str(key)) or category

            key_label = _normalise(key)
            if key_label and category:
                collected[category].add(key_label)

            _collect_literal(child, key_category, collected)

    elif isinstance(value, (list, tuple, set, frozenset)):
        for child in value:
            _collect_literal(child, category, collected)

    else:
        label = _normalise(value)

        if label and category:
            collected[category].add(label)


def _inspect_python(
    path: Path,
    collected: dict[str, set[str]],
) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return False

    found = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names: list[str] = []

            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
                elif isinstance(target, ast.Attribute):
                    names.append(target.attr)

            for name in names:
                category = _category_for_name(name)

                if not category:
                    continue

                try:
                    literal = ast.literal_eval(node.value)
                except (ValueError, TypeError, SyntaxError):
                    continue

                _collect_literal(literal, category, collected)
                found = True

        elif isinstance(node, ast.AnnAssign):
            if node.value is None:
                continue

            if isinstance(node.target, ast.Name):
                name = node.target.id
            elif isinstance(node.target, ast.Attribute):
                name = node.target.attr
            else:
                continue

            category = _category_for_name(name)

            if not category:
                continue

            try:
                literal = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                continue

            _collect_literal(literal, category, collected)
            found = True

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            else:
                function_name = ""

            category = _category_for_name(function_name)

            if not category and any(
                token in function_name.lower()
                for token in ("register", "handler", "dispatch", "route")
            ):
                category = "actions"

            if not category:
                continue

            for argument in node.args[:2]:
                if isinstance(argument, ast.Constant):
                    label = _normalise(argument.value)

                    if label:
                        collected[category].add(label)
                        found = True

    tokens = re.findall(
        r'''(?<![A-Za-z0-9])["']([A-Z][A-Z0-9_]{2,48})["']''',
        source,
    )

    for token in tokens:
        if token.endswith(("_TASK", "_PROFILE")):
            collected["profiles"].add(token)
            found = True
        elif token.endswith(("_MODE", "_POLICY", "_BOUNDED")):
            collected["policies"].add(token)
            found = True

    return found


def _inspect_json(
    path: Path,
    collected: dict[str, set[str]],
) -> bool:
    try:
        if path.stat().st_size > 2_000_000:
            return False

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False

    found = False

    def visit(value: Any, category: str | None = None) -> None:
        nonlocal found

        if isinstance(value, dict):
            for key, child in value.items():
                next_category = _category_for_name(str(key)) or category
                visit(child, next_category)

        elif isinstance(value, list):
            for child in value:
                visit(child, category)

        elif category:
            label = _normalise(value)

            if label:
                collected[category].add(label)
                found = True

    visit(payload)
    return found


def collect_semantic_ontology() -> dict[str, Any]:
    package_root = Path(__file__).resolve().parent
    project_root = package_root.parent.parent

    roots = [
        package_root,
        project_root / "runtime",
        Path.home() / ".local" / "share" / "sophyane" / "runtime",
        Path.home() / ".config" / "sophyane",
        Path.home() / ".sophyane",
    ]

    collected: dict[str, set[str]] = defaultdict(set)
    evidence: list[str] = []

    python_examined = 0
    json_examined = 0

    for path in sorted(package_root.glob("*.py")):
        if not any(hint in path.name.lower() for hint in SOURCE_HINTS):
            continue

        python_examined += 1

        if _inspect_python(path, collected):
            evidence.append(str(path))

    seen_json: set[Path] = set()

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue

        for path in root.rglob("*.json"):
            if path in seen_json:
                continue

            seen_json.add(path)

            if any(part in SKIP_DIRS for part in path.parts):
                continue

            if not any(hint in path.name.lower() for hint in RUNTIME_HINTS):
                continue

            json_examined += 1

            if json_examined > 250:
                break

            if _inspect_json(path, collected):
                evidence.append(str(path))

    result: dict[str, Any] = {}

    for category in CATEGORIES:
        result[category] = sorted(
            collected.get(category, set()),
            key=str.casefold,
        )

    result["evidence_sources"] = sorted(set(evidence))
    result["python_files_examined"] = python_examined
    result["json_files_examined"] = json_examined

    return result


def _format_values(values: list[str], limit: int = 16) -> str:
    if not values:
        return "none explicitly discovered"

    shown = values[:limit]
    result = ", ".join(shown)

    remaining = len(values) - len(shown)

    if remaining:
        result += f", +{remaining} more"

    return result


def render_semantic_ontology_report() -> str:
    ontology = collect_semantic_ontology()

    domains = ontology["domains"]
    intents = ontology["intents"]
    profiles = ontology["profiles"]
    actions = ontology["actions"]
    capabilities = ontology["capabilities"]
    policies = ontology["policies"]
    concepts = ontology["learned_concepts"]
    sources = ontology["evidence_sources"]

    executable = bool(actions or capabilities)
    accumulated = bool(concepts)

    lines = [
        "",
        "Semantic ontology",
        "────────────────────────────────────────────────────────",
        f"Domains      : {_format_values(domains)}",
        f"Intents      : {_format_values(intents)}",
        f"SLI profiles : {_format_values(profiles)}",
        f"Actions/tools: {_format_values(actions)}",
        f"Capabilities : {_format_values(capabilities)}",
        f"Policies     : {_format_values(policies)}",
        f"Learned terms: {_format_values(concepts)}",
        "",
        "Assessment",
        "────────────────────────────────────────────────────────",
        (
            "Executable action evidence : registered"
            if executable
            else "Executable action evidence : no explicit registry discovered"
        ),
        (
            "Accumulated semantic memory: discovered"
            if accumulated
            else "Accumulated semantic memory: no explicit concepts discovered"
        ),
        f"Python sources examined    : {ontology['python_files_examined']}",
        f"Runtime records examined   : {ontology['json_files_examined']}",
        f"Evidence-bearing sources   : {len(sources)}",
        (
            "Scope note                  : model knowledge is not counted "
            "as an executable capability."
        ),
    ]

    if sources:
        lines.extend(
            [
                "",
                "Ontology evidence",
                "────────────────────────────────────────────────────────",
            ]
        )

        for source in sources[:8]:
            lines.append(f"• {source}")

        remaining = len(sources) - 8

        if remaining > 0:
            lines.append(f"• +{remaining} more sources")

    lines.append("")

    return "\n".join(lines)
