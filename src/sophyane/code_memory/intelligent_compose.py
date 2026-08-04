"""Stable SLI capability/component/symbol composer."""
from __future__ import annotations

import html
import re

from pathlib import Path
from typing import Any, Callable

from sophyane.code_memory.capability_graph import (
    CAPABILITIES,
    retrieve_capability_graph,
)


Progress = Callable[[str], None]


def _request_family(request: str) -> str:
    text = " ".join(str(request or "").lower().split())

    if any(
        term in text
        for term in (
            "snake",
            "pong",
            "platformer",
            "space invader",
            "arcade",
            "racing game",
        )
    ):
        return "action_game"

    if any(
        term in text
        for term in (
            "missing word",
            "missing letter",
            "fill in the blank",
            "sentence game",
            "word game",
            "spelling",
            "word quiz",
            "letter quiz",
        )
    ):
        return "language_exercise"

    return "generic_browser_application"


def _extract_html(
    source: str,
) -> tuple[str, str, str]:
    styles = re.findall(
        r"<style[^>]*>(.*?)</style>",
        source,
        flags=re.I | re.S,
    )

    scripts = re.findall(
        r"<script[^>]*>(.*?)</script>",
        source,
        flags=re.I | re.S,
    )

    body_match = re.search(
        r"<body[^>]*>(.*?)</body>",
        source,
        flags=re.I | re.S,
    )

    body = body_match.group(1) if body_match else ""

    body = re.sub(
        r"<script[^>]*>.*?</script>",
        "",
        body,
        flags=re.I | re.S,
    )

    body = re.sub(
        r"<style[^>]*>.*?</style>",
        "",
        body,
        flags=re.I | re.S,
    )

    return (
        body.strip(),
        "\n".join(styles).strip(),
        "\n".join(scripts).strip(),
    )


def _clean_script(source: str) -> str:
    source = source.strip()

    if not source:
        return ""

    if re.search(
        r"(?m)^\s*(?:import|export)\s",
        source,
    ):
        return ""

    if any(
        marker in source
        for marker in (
            "require(",
            "module.exports",
            "process.env",
            "__dirname",
        )
    ):
        return ""

    return source


def _selected_contract(
    selected_ids,
    signatures,
) -> tuple[set[str], set[str], set[str]]:
    provides: set[str] = set()
    requires: set[str] = set()
    exports: set[str] = set()

    for chunk_id in selected_ids:
        signature = signatures[chunk_id]

        provides.update(signature.provides)
        requires.update(signature.requires)
        exports.update(signature.exports)

    return provides, requires, exports


def _provider_for(
    requirement: str,
    signatures,
    selected: set[str],
) -> str | None:
    candidates = []

    for chunk_id, signature in signatures.items():
        if signature.excluded_reason:
            continue

        if (
            requirement not in signature.provides
            and requirement not in signature.exports
        ):
            continue

        candidates.append(signature)

    if not candidates:
        return None

    candidates.sort(
        key=lambda signature: (
            signature.chunk_id in selected,
            not signature.explicit_contract,
            len(signature.requires),
            signature.size,
            signature.chunk_id,
        )
    )

    return candidates[0].chunk_id


def _resolve_dependencies(
    selected_ids,
    signatures,
) -> tuple[list[str], list[str]]:
    selected_ids = list(selected_ids)
    selected = set(selected_ids)

    while True:
        provides, requires, exports = _selected_contract(
            selected_ids,
            signatures,
        )

        capability_names = set(CAPABILITIES)

        missing_capabilities = {
            name
            for name in requires
            if (
                name in capability_names
                and name not in provides
            )
        }

        missing_symbols = {
            name
            for name in requires
            if (
                name not in capability_names
                and name not in exports
            )
        }

        unresolved = sorted(
            missing_capabilities
            | missing_symbols
        )

        if not unresolved:
            return selected_ids, []

        added = False
        impossible = []

        for requirement in unresolved:
            provider = _provider_for(
                requirement,
                signatures,
                selected,
            )

            if provider is None:
                impossible.append(requirement)
                continue

            if provider not in selected:
                selected.add(provider)
                selected_ids.append(provider)
                added = True

        if impossible:
            return selected_ids, impossible

        if not added:
            return selected_ids, unresolved


def _dependency_order(
    selected_ids,
    signatures,
) -> list[str]:
    remaining = set(selected_ids)
    ordered = []

    available_capabilities: set[str] = set()
    available_symbols: set[str] = set()

    while remaining:
        ready = []

        for chunk_id in remaining:
            signature = signatures[chunk_id]

            capability_requirements = {
                name
                for name in signature.requires
                if name in CAPABILITIES
            }

            symbol_requirements = (
                signature.requires
                - capability_requirements
            )

            if (
                capability_requirements
                <= available_capabilities
                and symbol_requirements
                <= available_symbols
            ):
                ready.append(chunk_id)

        if not ready:
            ready = sorted(
                remaining,
                key=lambda chunk_id: (
                    len(signatures[chunk_id].requires),
                    signatures[chunk_id].size,
                    chunk_id,
                ),
            )[:1]

        ready.sort(
            key=lambda chunk_id: (
                signatures[chunk_id].placement
                != "html_document",
                len(signatures[chunk_id].requires),
                signatures[chunk_id].size,
                chunk_id,
            )
        )

        for chunk_id in ready:
            signature = signatures[chunk_id]

            ordered.append(chunk_id)
            available_capabilities.update(
                signature.provides
            )
            available_symbols.update(
                signature.exports
            )
            remaining.remove(chunk_id)

    return ordered


def _language_dataset() -> str:
    return """
<script id="sli-language-dataset-provider">
window.SLI_EXERCISE_ITEMS = [
  {prompt: "The cat sat on the ___", answer: "mat"},
  {prompt: "Birds can ___", answer: "fly"},
  {prompt: "Water is ___", answer: "wet"},
  {prompt: "The sun rises in the ___", answer: "east"}
];
</script>
"""


def _coverage(plan, source: str):
    low = source.lower()
    total = 0.0
    covered = 0.0
    missing = []

    for need in plan.capabilities:
        definition = CAPABILITIES[need.name]

        count = sum(
            signal in low
            for signal in definition["signals"]
        )

        total += need.importance

        if count >= definition["minimum_signals"]:
            covered += need.importance
        else:
            missing.append(need.name)

    return (
        covered / total if total else 1.0,
        missing,
    )


def _behavior(source: str) -> dict[str, bool]:
    low = source.lower()

    return {
        "document":
            "<html" in low
            and "<body" in low
            and 'id="app"' in low,

        "state":
            "function createstate" in low,

        "data_model":
            "function normaliseitems" in low,

        "answer_normalization":
            "function normaliseanswer" in low,

        "answer_validation":
            "function validateanswer" in low,

        "rendering":
            "function renderprompt" in low,

        "input":
            "function bindexercisecontrols" in low
            and "addeventlistener" in low,

        "feedback":
            "function renderfeedback" in low,

        "score":
            "function recordattempt" in low,

        "next":
            "function advanceitem" in low,

        "reset":
            "function resetstate" in low,

        "entry":
            "function startexerciseapp" in low
            and "domcontentloaded" in low,
    }


def compose_browser_request(
    request: str,
    workspace: Path,
    store: Any,
    *,
    progress: Progress | None = None,
) -> tuple[str, list[str]]:
    progress = progress or (lambda _message: None)
    workspace = Path(workspace)

    family = _request_family(request)

    if family == "action_game":
        (workspace / "index.html").unlink(
            missing_ok=True
        )

        return (
            "SLI capability family unavailable: action_game.\n"
            "Required capabilities: directional input, timed movement "
            "loop, grid/canvas rendering, body state, food generation, "
            "collision detection, score and restart.\n"
            "No language-exercise framework was substituted.\n"
            "No LLM fallback was used.",
            [],
        )

    plan, matches, signatures = retrieve_capability_graph(
        store,
        request,
        per_capability=2,
    )

    progress(
        f"SLI capability graph planned "
        f"{len(plan.capabilities)} requirements"
    )

    selected_ids = []
    selected = set()
    missing_evidence = []

    for need in plan.capabilities:
        rows = matches.get(need.name, [])

        progress(
            f"SLI capability {need.name}: "
            + (
                ", ".join(
                    f"{row.chunk_id}:{row.score:.2f}"
                    for row in rows
                )
                if rows
                else "no compatible evidence"
            )
        )

        if not rows:
            missing_evidence.append(need.name)
            continue

        rows = sorted(
            rows,
            key=lambda row: (
                not signatures[row.chunk_id].explicit_contract,
                -row.score,
                row.size,
                row.chunk_id,
            ),
        )

        chosen = rows[0].chunk_id

        if chosen not in selected:
            selected.add(chosen)
            selected_ids.append(chosen)

    if missing_evidence:
        return (
            "SLI capability graph could not find compatible chunks.\n"
            "Missing retrieval evidence: "
            + ", ".join(missing_evidence)
            + "\nNo LLM fallback was used.",
            [],
        )

    selected_ids, unresolved = _resolve_dependencies(
        selected_ids,
        signatures,
    )

    if unresolved:
        return (
            "SLI component linker has unresolved dependencies.\n"
            "Missing providers: "
            + ", ".join(unresolved)
            + "\nNo LLM fallback was used.",
            [],
        )

    ordered_ids = _dependency_order(
        selected_ids,
        signatures,
    )

    bodies = []
    styles = []
    scripts = []

    for chunk_id in ordered_ids:
        chunk = store.chunks.get(chunk_id)

        if chunk is None:
            continue

        source = str(chunk.text or "")
        language = str(chunk.language or "").lower()

        if language == "html":
            body, css, javascript = _extract_html(
                source
            )

            if body:
                bodies.append(
                    f"<!-- chunk:{chunk_id} -->\n{body}"
                )

            if css:
                styles.append(
                    f"/* chunk:{chunk_id} */\n{css}"
                )

            javascript = _clean_script(javascript)

            if javascript:
                scripts.append(
                    f"/* chunk:{chunk_id} */\n{javascript}"
                )

        elif language == "css":
            if source.strip():
                styles.append(
                    f"/* chunk:{chunk_id} */\n{source.strip()}"
                )

        elif language in {
            "javascript",
            "typescript",
        }:
            javascript = _clean_script(source)

            if javascript:
                scripts.append(
                    f"/* chunk:{chunk_id} */\n{javascript}"
                )

    if not bodies:
        bodies.append('<main id="app"></main>')

    dataset = (
        _language_dataset()
        if family == "language_exercise"
        else ""
    )

    final_source = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(request[:100])}</title>
<style>
html,body{{margin:0;min-height:100%;font-family:system-ui,sans-serif}}
body{{padding:1rem;background:#f4f6f8}}
{chr(10).join(styles)}
</style>
</head>
<body>
{dataset}
{chr(10).join(bodies)}
<script>
"use strict";
{chr(10).join(scripts)}
</script>
</body>
</html>
"""

    coverage, missing = _coverage(
        plan,
        final_source,
    )

    behavior = _behavior(final_source)

    failed = [
        name
        for name, passed in behavior.items()
        if not passed
    ]

    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = workspace / "index.html"

    if (
        coverage < 0.90
        or missing
        or failed
    ):
        output.unlink(missing_ok=True)

        return (
            "SLI component composition rejected.\n"
            f"Capability coverage: {coverage:.1%}\n"
            "Missing capabilities: "
            + (", ".join(missing) if missing else "none")
            + "\nFailed behavior checks: "
            + (", ".join(failed) if failed else "none")
            + "\nNo LLM fallback was used.",
            [],
        )

    output.write_text(
        final_source,
        encoding="utf-8",
    )

    return (
        "\n".join(
            [
                "Sophyane stable component-linker composer",
                f"Request: {request}",
                f"Capabilities required: {len(plan.capabilities)}",
                f"Capability coverage: {coverage:.1%}",
                "Behavior checks: "
                + ", ".join(
                    f"{name}=passed"
                    for name in behavior
                ),
                "Used chunks: "
                + ", ".join(ordered_ids),
                "Files: index.html",
                "Success: True",
                (
                    "Inference: SLI capability/component/symbol "
                    "graph only; no local/cloud LLM"
                ),
            ]
        ),
        ordered_ids,
    )
