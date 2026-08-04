"""Metadata-first capability graph for SLI.

Explicit microchunk contracts are authoritative:

    provides
    requires
    exports
    concepts

Legacy chunks may still be inferred conservatively, but they cannot outrank
compatible explicit microcapabilities.
"""
from __future__ import annotations

import math
import re

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "build", "by", "complete",
    "contained", "create", "develop", "for", "from", "game", "generate",
    "html", "implement", "in", "index", "interactive", "into", "it",
    "make", "of", "on", "one", "project", "self", "that", "the", "this",
    "to", "using", "with",
}


CAPABILITIES: dict[str, dict[str, Any]] = {
    "document_shell": {
        "languages": {"html"},
        "signals": {"<!doctype", "<html", "<head", "<body"},
        "minimum_signals": 2,
        "concepts": {"html", "document", "page", "browser"},
    },
    "presentation": {
        "languages": {"html", "css", "javascript", "typescript"},
        "signals": {"<style", "display:", "grid", "flex", "class="},
        "minimum_signals": 1,
        "concepts": {"style", "layout", "interface", "responsive"},
    },
    "application_state": {
        "languages": {"javascript", "typescript"},
        "signals": {"state", "currentindex", "score", "attempts"},
        "minimum_signals": 2,
        "concepts": {"state", "score", "current", "progress"},
    },
    "user_input": {
        "languages": {"html", "javascript", "typescript"},
        "signals": {
            "addeventlistener", "<input", "<button", "keydown",
            "onclick", "queryselector",
        },
        "minimum_signals": 2,
        "concepts": {"input", "answer", "button", "keyboard", "submit"},
    },
    "rendering": {
        "languages": {"html", "javascript", "typescript"},
        "signals": {
            "innerhtml", "textcontent", "render", "appendchild",
            "queryselector",
        },
        "minimum_signals": 1,
        "concepts": {"render", "prompt", "question", "sentence", "word"},
    },
    "rules_validation": {
        "languages": {"javascript", "typescript"},
        "signals": {
            "validateanswer", "normaliseanswer", "correct", "incorrect",
            "answer",
        },
        "minimum_signals": 1,
        "concepts": {"validate", "answer", "correct", "incorrect", "match"},
    },
    "data_model": {
        "languages": {"javascript", "typescript", "json"},
        "signals": {
            "items", "questions", "sentences", "words", "prompt", "answer",
        },
        "minimum_signals": 2,
        "concepts": {"dataset", "question", "sentence", "word", "answer"},
    },
    "progress_feedback": {
        "languages": {"html", "javascript", "typescript"},
        "signals": {
            "feedback", "score", "progress", "correct", "incorrect",
            "aria-live",
        },
        "minimum_signals": 2,
        "concepts": {"feedback", "score", "status", "progress"},
    },
    "lifecycle": {
        "languages": {"javascript", "typescript"},
        "signals": {
            "advanceitem", "resetstate", "next", "restart", "currentindex",
        },
        "minimum_signals": 1,
        "concepts": {"next", "restart", "reset", "advance"},
    },
    "entry_point": {
        "languages": {"html", "javascript", "typescript"},
        "signals": {
            "domcontentloaded", "startexerciseapp", "document.getelementbyid",
        },
        "minimum_signals": 1,
        "concepts": {"start", "initialize", "application", "entry"},
    },
}


@dataclass
class CapabilityNeed:
    name: str
    importance: float
    reason: str


@dataclass
class RequestPlan:
    request: str
    concepts: set[str]
    capabilities: list[CapabilityNeed]
    target: str = "browser_application"


@dataclass
class ChunkSignature:
    chunk_id: str
    path: str
    language: str
    placement: str
    source: str
    size: int

    provides: set[str] = field(default_factory=set)
    requires: set[str] = field(default_factory=set)
    exports: set[str] = field(default_factory=set)
    concepts: set[str] = field(default_factory=set)

    explicit_contract: bool = False
    excluded_reason: str | None = None


@dataclass
class CapabilityMatch:
    capability: str
    chunk_id: str
    score: float
    path: str
    language: str
    size: int
    provides: set[str]


def _language(value: object) -> str:
    language = str(value or "").strip().lower()

    return {
        "js": "javascript",
        "ts": "typescript",
        "htm": "html",
    }.get(language, language)


def concepts(text: object) -> set[str]:
    return {
        word
        for word in re.findall(
            r"[a-z0-9_+-]{2,}",
            str(text or "").lower(),
        )
        if word not in STOPWORDS
    }


def plan_request(request: str) -> RequestPlan:
    text = " ".join(str(request or "").lower().split())
    request_concepts = concepts(text)

    requirements: dict[str, CapabilityNeed] = {}

    def require(name: str, importance: float, reason: str) -> None:
        previous = requirements.get(name)

        if previous is None or importance > previous.importance:
            requirements[name] = CapabilityNeed(
                name=name,
                importance=importance,
                reason=reason,
            )

    for capability in (
        "document_shell",
        "presentation",
        "application_state",
        "user_input",
        "rendering",
        "rules_validation",
        "data_model",
        "progress_feedback",
        "lifecycle",
        "entry_point",
    ):
        require(
            capability,
            1.0,
            "browser application dependency",
        )

    if any(
        term in text
        for term in ("game", "quiz", "exercise", "interactive")
    ):
        for capability in (
            "application_state",
            "user_input",
            "rules_validation",
            "progress_feedback",
            "lifecycle",
        ):
            require(
                capability,
                2.0,
                "interactive application requirement",
            )

    if any(
        term in text
        for term in ("word", "sentence", "letter", "question")
    ):
        require("data_model", 2.6, "exercise data requirement")
        require("rules_validation", 2.6, "answer validation requirement")
        require("user_input", 2.2, "answer input requirement")
        require("rendering", 2.0, "prompt rendering requirement")

    return RequestPlan(
        request=request,
        concepts=request_concepts,
        capabilities=sorted(
            requirements.values(),
            key=lambda need: (-need.importance, need.name),
        ),
    )


def _values(metadata: dict[str, Any], key: str) -> set[str]:
    value = metadata.get(key) or []

    if isinstance(value, str):
        value = [value]

    return {
        str(item).strip()
        for item in value
        if str(item).strip()
    }


def signature(
    chunk_id: str,
    chunk: Any,
) -> ChunkSignature:
    text = str(getattr(chunk, "text", "") or "")
    low = text.lower()

    path = str(getattr(chunk, "path", "") or "")
    path_low = path.lower().replace("\\", "/")
    filename = Path(path_low.split("::")[0]).name

    language = _language(getattr(chunk, "language", ""))
    metadata = dict(getattr(chunk, "meta", None) or {})

    explicit_provides = _values(metadata, "provides")
    explicit_requires = _values(metadata, "requires")
    explicit_exports = _values(metadata, "exports")
    explicit_concepts = {
        value.lower()
        for value in _values(metadata, "concepts")
    }

    explicit_contract = bool(
        explicit_provides
        or explicit_requires
        or explicit_exports
    )

    result = ChunkSignature(
        chunk_id=str(chunk_id),
        path=path,
        language=language,
        placement=str(metadata.get("placement") or ""),
        source=str(getattr(chunk, "source", "") or ""),
        size=len(text.encode("utf-8", errors="ignore")),
        provides=set(explicit_provides),
        requires=set(explicit_requires),
        exports=set(explicit_exports),
        concepts=concepts(text[:100_000]) | explicit_concepts,
        explicit_contract=explicit_contract,
    )

    if metadata.get("exclude") or metadata.get(
        "exclude_from_browser_compose"
    ):
        result.excluded_reason = "explicitly excluded"
        return result

    if language not in {
        "html",
        "css",
        "javascript",
        "typescript",
        "json",
    }:
        result.excluded_reason = "wrong execution domain"
        return result

    if (
        filename.startswith("test_")
        or filename.endswith(".test.js")
        or "/tests/" in path_low
        or "::test_" in path_low
        or "fixture" in filename
    ):
        result.excluded_reason = "test or fixture"
        return result

    banned_paths = (
        "jquery/",
        "lodash",
        "polyfill",
        "webxr",
        "webgl",
        "indexeddb-api",
        "express/",
        "todomvc/",
        "starlette/",
        "flask/",
        "compiled.js",
        "elements.build.js",
        "webcomponents",
        "node_modules/",
        "vendor/",
        "dist/",
        "min.js",
    )

    if (
        not explicit_contract
        and any(marker in path_low for marker in banned_paths)
    ):
        result.excluded_reason = "unrelated framework or demo"
        return result

    if not explicit_contract and result.size > 20_000:
        result.excluded_reason = "oversized legacy implementation"
        return result

    if explicit_contract:
        result.provides = {
            capability
            for capability in result.provides
            if capability in CAPABILITIES
            and language in CAPABILITIES[capability]["languages"]
        }

        return result

    # Legacy inference remains conservative.
    for capability, definition in CAPABILITIES.items():
        if language not in definition["languages"]:
            continue

        count = sum(
            signal in low
            for signal in definition["signals"]
        )

        if count >= definition["minimum_signals"]:
            result.provides.add(capability)

    return result


def build_signatures(
    store: Any,
) -> dict[str, ChunkSignature]:
    return {
        str(chunk_id): signature(
            str(chunk_id),
            chunk,
        )
        for chunk_id, chunk in store.chunks.items()
    }


def score_match(
    plan: RequestPlan,
    need: CapabilityNeed,
    sig: ChunkSignature,
    chunk: Any,
) -> float:
    if sig.excluded_reason:
        return -math.inf

    meta = dict(getattr(chunk, "meta", None) or {})
    explicit = set(meta.get("provides") or [])
    path_l = (sig.path or "").lower()
    is_micro = path_l.startswith("builtin://sli-capabilities/") or bool(meta.get("microcapability"))
    if is_micro and need.name in (explicit or sig.provides):
        base = 6.0 + float(need.importance)
        overlap = len(plan.concepts & sig.concepts)
        return base + min(overlap, 3) * 0.5

    if need.name not in sig.provides:
        return -math.inf

    request_overlap = len(
        plan.concepts & sig.concepts
    )

    request_ratio = request_overlap / max(
        1,
        len(plan.concepts),
    )

    capability_concepts = set(
        CAPABILITIES[need.name]["concepts"]
    )

    capability_overlap = len(
        capability_concepts & sig.concepts
    )

    capability_ratio = capability_overlap / max(
        1,
        len(capability_concepts),
    )

    try:
        weight = float(
            getattr(chunk, "weight", 1.0) or 1.0
        )
    except Exception:
        weight = 1.0

    weight = max(0.05, min(weight, 2.0))

    score = 0.0
    score += request_ratio * 5.0
    score += capability_ratio * 4.0
    score += math.log1p(weight) * 0.35

    if 80 <= sig.size <= 4_000:
        score += 1.0
    elif sig.size > 12_000:
        score -= 1.5

    if sig.explicit_contract:
        score += 12.0

    if sig.source == "seed:sli-microcapabilities":
        score += 6.0

    # High-importance capabilities require either explicit contracts or
    # direct request overlap.
    if (
        need.importance >= 2.0
        and not sig.explicit_contract
        and request_overlap == 0
    ):
        return -math.inf

    return score


def retrieve_capability_graph(
    store: Any,
    request: str,
    *,
    per_capability: int = 2,
) -> tuple[
    RequestPlan,
    dict[str, list[CapabilityMatch]],
    dict[str, ChunkSignature],
]:
    plan = plan_request(request)
    signatures = build_signatures(store)

    matches: dict[str, list[CapabilityMatch]] = {}

    for need in plan.capabilities:
        ranked: list[CapabilityMatch] = []

        for chunk_id, chunk in store.chunks.items():
            sig = signatures[str(chunk_id)]

            score = score_match(
                plan,
                need,
                sig,
                chunk,
            )

            if not math.isfinite(score):
                continue

            ranked.append(
                CapabilityMatch(
                    capability=need.name,
                    chunk_id=str(chunk_id),
                    score=score,
                    path=sig.path,
                    language=sig.language,
                    size=sig.size,
                    provides=set(sig.provides),
                )
            )

        ranked.sort(
            key=lambda match: (
                match.score,
                -match.size,
            ),
            reverse=True,
        )

        selected: list[CapabilityMatch] = []
        seen_paths: set[str] = set()

        for match in ranked:
            family = match.path.split("::")[0]

            if family in seen_paths:
                continue

            selected.append(match)
            seen_paths.add(family)

            if len(selected) >= per_capability:
                break

        matches[need.name] = selected

    return plan, matches, signatures


def graph_report(
    plan: RequestPlan,
    matches: dict[str, list[CapabilityMatch]],
) -> str:
    lines = [
        f"Request: {plan.request}",
        "Capability graph:",
    ]

    for need in plan.capabilities:
        rows = matches.get(need.name, [])

        lines.append(
            f"- {need.name}: required importance={need.importance:.1f}"
        )

        if not rows:
            lines.append("  evidence: none")
            continue

        for row in rows:
            lines.append(
                f"  evidence: {row.chunk_id} "
                f"score={row.score:.2f} "
                f"lang={row.language} "
                f"size={row.size} "
                f"path={row.path}"
            )

    return "\n".join(lines)


__all__ = [
    "CAPABILITIES",
    "CapabilityMatch",
    "CapabilityNeed",
    "ChunkSignature",
    "RequestPlan",
    "build_signatures",
    "concepts",
    "graph_report",
    "plan_request",
    "retrieve_capability_graph",
    "score_match",
    "signature",
]
