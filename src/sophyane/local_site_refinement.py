"""Bounded deterministic-SLI → local-GGUF website refinement pipeline."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

from sophyane.code_memory import sli_rich_site_compose as rich
from sophyane.config import load_config
from sophyane.providers.local_gguf import (
    LocalGgufProvider,
    load_gguf_runtime_state,
)

Progress = Callable[[str], None]

MAX_REFINEMENT_ROUNDS = 2
MAX_PATCH_CHARS = 12_000


def _progress(
    callback: Progress | None,
    message: str,
) -> None:
    if callback is not None:
        callback(message)


def _provider() -> LocalGgufProvider:
    """Construct only the configured local GGUF provider."""
    config = load_config()
    state = load_gguf_runtime_state()

    return LocalGgufProvider(
        model=str(
            config.get("model")
            or state.get("model")
            or "local-gguf"
        ),
        timeout=min(
            300,
            int(config.get("timeout") or 300),
        ),
        temperature=0.2,
        max_tokens=768,
        endpoint=str(
            state.get("runtime_url")
            or state.get("endpoint")
            or ""
        ),
        gguf_path=str(state.get("gguf_path") or ""),
        cli_path=str(
            state.get("cli")
            or state.get("cli_path")
            or ""
        ),
    )


def _artifact_summary(
    request: str,
    document: str,
) -> str:
    """Create a small evidence summary suitable for a 1.5B model."""
    titles = re.findall(
        r"<(?:title|h1|h2|h3)\b[^>]*>(.*?)</(?:title|h1|h2|h3)>",
        document,
        flags=re.I | re.S,
    )

    cleaned_titles = [
        re.sub(r"<[^>]+>", "", value).strip()
        for value in titles[:18]
    ]

    return json.dumps(
        {
            "request": request,
            "bytes": len(document.encode("utf-8")),
            "titles": cleaned_titles,
            "has_navigation": "<nav" in document.casefold(),
            "has_main": "<main" in document.casefold(),
            "has_footer": "<footer" in document.casefold(),
            "has_search": "search" in document.casefold(),
            "has_theme_toggle": (
                "theme" in document.casefold()
                and "toggle" in document.casefold()
            ),
            "has_reduced_motion": (
                "prefers-reduced-motion"
                in document.casefold()
            ),
            "has_provenance": (
                "source" in document.casefold()
                or "provenance" in document.casefold()
            ),
        },
        ensure_ascii=False,
    )


def _extract_json(text: str) -> dict:
    value = str(text or "").strip()

    fenced = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        value,
        flags=re.I | re.S,
    )
    if fenced:
        value = fenced.group(1)

    start = value.find("{")
    end = value.rfind("}")

    if start < 0 or end <= start:
        return {}

    try:
        parsed = json.loads(value[start : end + 1])
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _critique(
    provider: LocalGgufProvider,
    request: str,
    document: str,
    round_number: int,
) -> dict:
    prompt = f"""
Review this deterministic website artifact summary.

Round: {round_number}
Artifact summary:
{_artifact_summary(request, document)}

Return JSON only:
{{
  "verdict": "pass" or "improve",
  "issues": ["maximum 4 concrete issues"],
  "improvements": ["maximum 4 safe additive improvements"]
}}

Judge:
- subject relevance
- readability
- accessibility
- responsive behavior
- navigation
- interaction quality
- provenance
- obvious broken JavaScript

Do not request a total rewrite.
""".strip()

    response = provider.generate(
        prompt,
        (
            "You are the local Sophyane website critic. "
            "Be concise, practical and deterministic. "
            "Return valid JSON only."
        ),
    )

    return _extract_json(response)


def _clean_patch(value: str) -> str:
    patch = str(value or "").strip()

    fenced = re.search(
        r"```(?:html)?\s*(.*?)\s*```",
        patch,
        flags=re.I | re.S,
    )
    if fenced:
        patch = fenced.group(1).strip()

    # The local model may only add bounded style/script/template fragments.
    allowed = re.findall(
        r"<style\b[^>]*>.*?</style>"
        r"|<script\b[^>]*>.*?</script>"
        r"|<template\b[^>]*>.*?</template>",
        patch,
        flags=re.I | re.S,
    )

    cleaned = "\n".join(allowed).strip()

    if len(cleaned) > MAX_PATCH_CHARS:
        cleaned = cleaned[:MAX_PATCH_CHARS]

    return cleaned


def _generate_patch(
    provider: LocalGgufProvider,
    request: str,
    document: str,
    critique: dict,
    round_number: int,
) -> str:
    prompt = f"""
Improve an existing deterministic HTML website using a small additive patch.

User request:
{request}

Round:
{round_number}

Artifact summary:
{_artifact_summary(request, document)}

Local critique:
{json.dumps(critique, ensure_ascii=False)}

Return only one or more of:
<style>...</style>
<script>...</script>
<template>...</template>

Rules:
- additive patch only
- no markdown
- no complete HTML document
- no external frameworks
- no destructive DOM replacement
- no document.write
- no eval
- preserve all existing content
- improve accessibility, responsiveness or interaction
- keep output under 600 tokens
""".strip()

    response = provider.generate(
        prompt,
        (
            "You are the local Sophyane frontend improver. "
            "Return a safe additive HTML patch only."
        ),
    )

    return _clean_patch(response)


def _apply_patch(
    document: str,
    patch: str,
    round_number: int,
) -> str:
    marker = (
        f"<!-- SOPHYANE_LOCAL_GGUF_REFINEMENT_"
        f"ROUND_{round_number} -->"
    )
    payload = f"\n{marker}\n{patch}\n"

    lowered = patch.casefold()

    if "<style" in lowered and "</head>" in document.casefold():
        index = document.lower().rfind("</head>")
        document = (
            document[:index]
            + payload
            + document[index:]
        )
        return document

    if "</body>" in document.casefold():
        index = document.lower().rfind("</body>")
        return document[:index] + payload + document[index:]

    return document + payload


def _validate(document: str) -> list[str]:
    """Validate the complete artifact after every local refinement."""
    errors: list[str] = []
    lowered = document.casefold()

    required = (
        "<!doctype html",
        "<html",
        "<head",
        "<body",
        "</html>",
        "</head>",
        "</body>",
    )

    for token in required:
        if token not in lowered:
            errors.append(f"missing:{token}")

    if len(document.encode("utf-8")) < 1_000:
        errors.append("document_too_small")

    if "```" in document:
        errors.append("markdown_fence_present")

    if document.count("<style") != document.count("</style>"):
        errors.append("unbalanced_style")

    if document.count("<script") != document.count("</script>"):
        errors.append("unbalanced_script")

    if re.search(
        r"\b(?:eval|document\.write)\s*\(",
        document,
        flags=re.I,
    ):
        errors.append("unsafe_javascript")

    return errors


def _local_runtime_failure_report(
    *,
    request: str,
    output: Path,
    error: Exception,
) -> str:
    """Stop safely when strict local GGUF review cannot run."""
    return "\n".join(
        [
            "Sophyane hybrid SLI + local GGUF website pipeline",
            f"Request: {request}",
            "Initial artifact: deterministic SLI completed",
            f"Initial artifact path: {output}",
            "Local GGUF critique attempted: True",
            "Local GGUF critique completed: False",
            f"Local runtime error: {type(error).__name__}: {error}",
            "Final validation: not run after local-runtime failure",
            "Browser opened: False",
            "Cloud LLM used: False",
            "Provider fallback used: False",
            "Success: False",
            "Action required: configure llama-server or llama-cli, then retry.",
        ]
    )


def compose_refined_local_topic_site(
    request: str,
    workspace: Path,
    *,
    progress: Progress | None = None,
) -> str:
    """Create via deterministic SLI, refine locally, validate, then open."""
    workspace = Path(workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    output = workspace / "index.html"

    previous_no_browser = os.environ.get("SOPHYANE_NO_BROWSER")
    os.environ["SOPHYANE_NO_BROWSER"] = "1"

    try:
        _progress(
            progress,
            "Website route: deterministic SLI initial composition",
        )
        initial_report = rich.compose_rich_topic_site(
            request,
            workspace,
            progress=progress,
        )
    finally:
        if previous_no_browser is None:
            os.environ.pop("SOPHYANE_NO_BROWSER", None)
        else:
            os.environ["SOPHYANE_NO_BROWSER"] = previous_no_browser

    if not output.is_file():
        raise RuntimeError(
            "Deterministic SLI did not create index.html"
        )

    document = output.read_text(encoding="utf-8")
    initial_errors = _validate(document)

    if initial_errors:
        raise RuntimeError(
            "Initial deterministic artifact failed validation: "
            + ", ".join(initial_errors)
        )

    provider = _provider()
    rounds_completed = 0
    critiques: list[dict] = []

    for round_number in range(
        1,
        MAX_REFINEMENT_ROUNDS + 1,
    ):
        _progress(
            progress,
            f"Website route: local GGUF critique round {round_number}",
        )

        try:
            critique = _critique(
                provider,
                request,
                document,
                round_number,
            )
        except Exception as error:
            _progress(
                progress,
                "Strict local GGUF critique failed; "
                "preserving the deterministic artifact and stopping.",
            )
            return _local_runtime_failure_report(
                request=request,
                output=output,
                error=error,
            )

        critiques.append(critique)

        verdict = str(
            critique.get("verdict") or "improve"
        ).strip().casefold()

        if verdict == "pass":
            _progress(
                progress,
                "Local GGUF accepted the current artifact",
            )
            break

        _progress(
            progress,
            f"Website route: local GGUF improvement round {round_number}",
        )

        try:
            patch = _generate_patch(
                provider,
                request,
                document,
                critique,
                round_number,
            )
        except Exception as error:
            _progress(
                progress,
                "Strict local GGUF improvement failed; "
                "preserving the deterministic artifact and stopping.",
            )
            return _local_runtime_failure_report(
                request=request,
                output=output,
                error=error,
            )

        if not patch:
            raise RuntimeError(
                "Local GGUF returned no valid additive HTML patch"
            )

        candidate = _apply_patch(
            document,
            patch,
            round_number,
        )
        errors = _validate(candidate)

        if errors:
            _progress(
                progress,
                "Local GGUF candidate rejected by validator: "
                + ", ".join(errors),
            )
            continue

        document = candidate
        output.write_text(document, encoding="utf-8")
        rounds_completed += 1

        _progress(
            progress,
            f"Validator accepted local refinement round {round_number}",
        )

    final_errors = _validate(document)

    if final_errors:
        raise RuntimeError(
            "Final website validation failed: "
            + ", ".join(final_errors)
        )

    # Browser opens only after local review and final validation.
    browser_opened, browser_target = rich._open_generated_site(
        output,
        progress or (lambda _message: None),
    )

    critique_path = workspace / "local-gguf-critique.json"
    critique_path.write_text(
        json.dumps(
            critiques,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return "\n".join(
        [
            "Sophyane hybrid SLI + local GGUF website pipeline",
            f"Request: {request}",
            "Initial artifact: deterministic SLI",
            "Local GGUF critique: completed",
            f"Local refinement rounds accepted: {rounds_completed}",
            f"Validator retries allowed: {MAX_REFINEMENT_ROUNDS}",
            "Final validation: passed",
            f"Files: {output.name}, {critique_path.name}",
            f"Browser opened: {browser_opened}",
            f"Browser target: {browser_target}",
            "Cloud LLM used: False",
            "Local GGUF used: True",
            "Success: True",
        ]
    )
