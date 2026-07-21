"""Controlled semantic consultation for SLI.

SLI freezes deterministic intent anchors and asks an LLM only about uncertain
terms. Model output is treated as a candidate and rejected when it changes the
known action, artifact, profile, location or scope.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

_ACTIONS = {
    "build", "make", "create", "design", "develop", "implement", "write", "fix",
    "repair", "patch", "run", "test", "deploy", "open", "continue", "convert",
    "install", "integrate", "optimize", "optimise", "add", "remove", "change",
    "update", "improve", "modify",
}
_ARTIFACTS = {
    "website", "site", "web", "app", "application", "game", "dashboard", "api",
    "server", "script", "page", "portfolio", "store", "shop", "marketplace",
}
_KNOWN = _ACTIONS | _ARTIFACTS | {
    "for", "a", "an", "the", "local", "in", "on", "with", "without", "and",
    "mobile", "phone", "android", "ios", "html", "css", "javascript", "premium",
    "luxury", "luxurious", "editorial", "cinematic", "responsive", "snake", "pong",
    "pingpong", "tetris", "chess", "tic", "tac", "toe", "admin", "panel",
    "analytics", "cart", "grocery", "kiryana", "store", "pakistan",
}
_SEMANTIC_MEMORY = {
    "mak3": ("make", 0.999),
    "maek": ("make", 0.98),
    "craete": ("create", 0.98),
    "websit": ("website", 0.98),
    "webiste": ("website", 0.98),
    "gamr": ("game", 0.97),
    "pingpong": ("pong", 0.99),
    "kiryana": ("grocery store", 0.999),
}


@dataclass(frozen=True)
class SemanticLedger:
    original: str
    normalized: str
    anchors: tuple[str, ...]
    proper_nouns: tuple[str, ...]
    uncertain_terms: tuple[str, ...]
    resolutions: tuple[tuple[str, str], ...]
    confidence: float
    consulted: bool = False
    drift_rejected: bool = False


def _state_root() -> Path:
    return Path(os.environ.get("SOPHYANE_HOME", Path.home() / ".local/share/sophyane")).expanduser()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w.-]+", text, flags=re.UNICODE)


def _looks_proper(token: str, index: int) -> bool:
    return bool(token[:1].isupper() and index > 0) or bool(re.fullmatch(r"[A-Z][A-Za-z0-9.-]+", token))


def analyze(message: str) -> SemanticLedger:
    raw = " ".join(str(message or "").strip().split())
    anchors: list[str] = []
    proper: list[str] = []
    unknown: list[str] = []
    resolutions: list[tuple[str, str]] = []
    normalized_tokens: list[str] = []
    confidences: list[float] = []

    for index, token in enumerate(_tokens(raw)):
        lower = token.lower()
        if lower in _SEMANTIC_MEMORY:
            resolved, confidence = _SEMANTIC_MEMORY[lower]
            resolutions.append((token, resolved))
            normalized_tokens.extend(resolved.split())
            confidences.append(confidence)
            if resolved in _ACTIONS or any(x in _ARTIFACTS for x in resolved.split()):
                anchors.extend(resolved.split())
        elif lower in _KNOWN or lower in _ACTIONS or lower in _ARTIFACTS:
            normalized_tokens.append(token)
            if lower in _ACTIONS or lower in _ARTIFACTS:
                anchors.append(lower)
        elif re.fullmatch(r"\d+(?:\.\d+)*", token) or _looks_proper(token, index):
            normalized_tokens.append(token)
            proper.append(token)
        elif len(lower) <= 2:
            normalized_tokens.append(token)
        else:
            normalized_tokens.append(token)
            unknown.append(token)

    confidence = min(confidences) if confidences else (1.0 if not unknown else 0.0)
    return SemanticLedger(
        original=raw,
        normalized=" ".join(normalized_tokens),
        anchors=tuple(dict.fromkeys(anchors)),
        proper_nouns=tuple(dict.fromkeys(proper)),
        uncertain_terms=tuple(dict.fromkeys(unknown)),
        resolutions=tuple(resolutions),
        confidence=confidence,
    )


def consultation_prompt(ledger: SemanticLedger) -> str:
    payload = {
        "known_anchors": ledger.anchors,
        "preserve_verbatim": ledger.proper_nouns,
        "uncertain_terms": ledger.uncertain_terms,
        "original_request": ledger.original[:700],
    }
    return (
        "You are a constrained semantic resolver. Interpret ONLY uncertain_terms. "
        "Do not plan, add features, broaden scope, change known anchors, alter names/locations, "
        "or replace the requested artifact. Return JSON only: "
        '{"resolved_terms":{"term":"meaning"},"confidence":0.0,"material_change":false}. '
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )[:1400]


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except Exception:
            return None


def apply_consultation(ledger: SemanticLedger, raw: str) -> SemanticLedger:
    data = _extract_json(raw)
    if not data or data.get("material_change") is True:
        return SemanticLedger(**{**asdict(ledger), "consulted": True, "drift_rejected": True})
    mapping = data.get("resolved_terms")
    if not isinstance(mapping, dict):
        return SemanticLedger(**{**asdict(ledger), "consulted": True, "drift_rejected": True})

    allowed = {x.lower(): x for x in ledger.uncertain_terms}
    accepted: list[tuple[str, str]] = list(ledger.resolutions)
    normalized = ledger.normalized
    for source, meaning in mapping.items():
        source_key = str(source).lower().strip()
        meaning_text = " ".join(str(meaning or "").strip().split())[:120]
        if source_key not in allowed or not meaning_text:
            continue
        original_term = allowed[source_key]
        normalized = re.sub(rf"\b{re.escape(original_term)}\b", meaning_text, normalized, flags=re.I)
        accepted.append((original_term, meaning_text))

    # Drift firewall: all known anchors and proper nouns must survive unchanged.
    lower = normalized.lower()
    drift = any(anchor not in lower for anchor in ledger.anchors)
    drift = drift or any(name.lower() not in lower for name in ledger.proper_nouns)
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if drift:
        normalized = ledger.normalized
        accepted = list(ledger.resolutions)

    return SemanticLedger(
        original=ledger.original,
        normalized=normalized,
        anchors=ledger.anchors,
        proper_nouns=ledger.proper_nouns,
        uncertain_terms=ledger.uncertain_terms,
        resolutions=tuple(accepted),
        confidence=max(0.0, min(1.0, confidence)),
        consulted=True,
        drift_rejected=drift,
    )


def resolve(message: str, ask: Callable[..., Any] | None = None, *, timeout: int = 18) -> SemanticLedger:
    ledger = analyze(message)
    if not ledger.uncertain_terms or ask is None:
        _record(ledger)
        return ledger
    try:
        response = ask(consultation_prompt(ledger), timeout=timeout)
        ledger = apply_consultation(ledger, getattr(response, "text", str(response)))
    except Exception:
        ledger = SemanticLedger(**{**asdict(ledger), "consulted": True})
    _record(ledger)
    return ledger


def _record(ledger: SemanticLedger) -> None:
    try:
        path = _state_root() / "sli-semantic-events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": time.time(), **asdict(ledger)}, ensure_ascii=False) + "\n")
    except Exception:
        pass
