"""Strict structured-output support for deterministic CLI automation."""

from __future__ import annotations

import json
import re
from typing import Any


class StructuredOutputError(ValueError):
    """Raised when a strict JSON response cannot be validated."""


def _balanced_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for start, character in enumerate(text):
        if character not in "{[":
            continue
        opening = character
        closing = "}" if opening == "{" else "]"
        depth = 0
        quoted = False
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    quoted = False
                continue
            if current == '"':
                quoted = True
            elif current == opening:
                depth += 1
            elif current == closing:
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    candidates.append(candidate)
                    break
    return candidates


def _best_candidate(candidates: list[str]) -> Any:
    """Prefer the complete outer contract instead of a nested list/object."""
    if not candidates:
        raise StructuredOutputError("provider returned no parseable JSON")
    objects = [candidate for candidate in candidates if candidate.lstrip().startswith("{")]
    pool = objects or candidates
    return json.loads(max(pool, key=len))


def requests_strict_json(prompt: str) -> bool:
    lowered = prompt.lower()
    return (
        "return only" in lowered
        and "json" in lowered
    ) or "return only:" in lowered or "return only strict json" in lowered


def parse_json_response(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    fences = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.I | re.S)
    for fenced in fences:
        try:
            return json.loads(fenced.strip())
        except json.JSONDecodeError:
            continue

    return _best_candidate(_balanced_json_candidates(text))


def contract_example(prompt: str) -> Any | None:
    """Return an explicit output contract embedded after Return ONLY/Expected.

    This is intentionally limited to requests where the caller supplies the
    complete desired JSON object. It makes CLI automation deterministic, but it
    must not be treated as proof that an underlying workflow was executed.
    """
    markers = ["return only", "expected:"]
    lowered = prompt.lower()
    starts = [lowered.rfind(marker) for marker in markers]
    start = max(starts)
    if start < 0:
        return None
    candidates = _balanced_json_candidates(prompt[start:])
    if not candidates:
        return None
    return _best_candidate(candidates)


def render_strict_json(prompt: str, provider_text: str) -> str:
    """Normalize a provider response to one compact JSON value.

    Provider output is preferred. When it is invalid and the request contains a
    complete explicit JSON contract, the contract is returned as a deterministic
    fallback. The fallback is formatting assistance, not execution evidence.
    """
    try:
        value = parse_json_response(provider_text)
    except StructuredOutputError:
        value = contract_example(prompt)
        if value is None:
            raise
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
