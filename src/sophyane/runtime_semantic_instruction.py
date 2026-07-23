"""Semantic handling of instructions entered during active work."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SemanticInstruction:
    raw: str
    provider: str | None = None
    is_provider_only: bool = False


_LOCAL_PATTERNS = (
    r"\buse (?:the )?local model\b",
    r"\bswitch to (?:the )?local\b",
    r"\bchange to (?:the )?local model\b",
    r"\breplace gemini with (?:the )?local\b",
    r"\bdo not use gemini\b",
    r"\bstop using gemini\b",
    r"\bsave (?:api )?tokens\b",
    r"\buse local_gguf\b",
    r"\blocal first\b",
)

_GEMINI_PATTERNS = (
    r"\buse gemini\b",
    r"\bswitch to gemini\b",
    r"\bchange to gemini\b",
    r"\buse (?:the )?cloud model\b",
    r"\bcloud only\b",
)

_PROVIDER_WORDS = (
    "model",
    "provider",
    "gemini",
    "local",
    "cloud",
    "tokens",
    "local_gguf",
)


def _clean(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def classify_instruction(text: str) -> SemanticInstruction:
    raw = _clean(text)
    lowered = raw.casefold()

    provider: str | None = None

    if any(
        re.search(pattern, lowered)
        for pattern in _LOCAL_PATTERNS
    ):
        provider = "local"

    elif any(
        re.search(pattern, lowered)
        for pattern in _GEMINI_PATTERNS
    ):
        provider = "gemini"

    provider_only = (
        provider is not None
        and any(word in lowered for word in _PROVIDER_WORDS)
        and not any(
            marker in lowered
            for marker in (
                "background",
                "design",
                "feature",
                "button",
                "screen",
                "game",
                "page",
                "color",
                "colour",
                "controls",
                "mobile",
                "browser",
                "file",
                "test",
                "fix",
                "add",
                "remove",
                "change the ",
            )
        )
    )

    return SemanticInstruction(
        raw=raw,
        provider=provider,
        is_provider_only=provider_only,
    )


def _walk(value: Any, seen: set[int] | None = None, depth: int = 0):
    if value is None or depth > 8:
        return

    seen = seen or set()
    marker = id(value)

    if marker in seen:
        return

    seen.add(marker)
    yield value

    owner = getattr(value, "__self__", None)

    if owner is not None:
        yield from _walk(owner, seen, depth + 1)

    closure = getattr(value, "__closure__", None) or ()

    for cell in closure:
        try:
            child = cell.cell_contents
        except ValueError:
            continue

        yield from _walk(child, seen, depth + 1)

    for attr in (
        "provider",
        "dispatcher",
        "backend",
        "llm",
        "model_provider",
        "primary",
        "fallback",
        "_provider",
    ):
        try:
            child = getattr(value, attr)
        except Exception:
            continue

        yield from _walk(child, seen, depth + 1)


def _provider_name(item: Any) -> str:
    if isinstance(item, (tuple, list)) and item:
        return str(item[0]).casefold()

    for attr in (
        "name",
        "provider_name",
        "provider",
        "model",
    ):
        try:
            value = getattr(item, attr)
        except Exception:
            continue

        if value:
            return str(value).casefold()

    return type(item).__name__.casefold()


def _reorder_provider_list(
    providers: list[Any],
    preference: str,
) -> bool:
    if not providers:
        return False

    def rank(item: Any) -> tuple[int, str]:
        name = _provider_name(item)

        is_local = any(
            marker in name
            for marker in (
                "local",
                "gguf",
                "ollama",
                "llama",
            )
        )

        is_gemini = "gemini" in name

        if preference == "local":
            return (
                0 if is_local else 2 if is_gemini else 1,
                name,
            )

        return (
            0 if is_gemini else 2 if is_local else 1,
            name,
        )

    reordered = sorted(providers, key=rank)

    if reordered == providers:
        return False

    providers[:] = reordered
    return True


def apply_provider_preference(
    tui: Any,
    preference: str,
) -> bool:
    """Update persistent state and reorder accessible fallback chains."""

    preference = preference.casefold().strip()

    if preference not in {"local", "gemini"}:
        return False

    tui._semantic_provider_preference = preference

    config = getattr(tui, "config", None)

    if isinstance(config, dict):
        config["runtime_provider_preference"] = preference

        if preference == "local":
            config["provider"] = "local_gguf"
            config["mode"] = "local"
            config["allow_local_fallbacks"] = True
        else:
            config["provider"] = "gemini"
            config["mode"] = "cloud"

    changed = False

    for value in _walk(getattr(tui, "ask", None)):
        providers = getattr(value, "_providers", None)

        if isinstance(providers, list):
            changed = (
                _reorder_provider_list(
                    providers,
                    preference,
                )
                or changed
            )

        for attr in (
            "active_provider",
            "current_provider",
            "last_provider",
        ):
            if not hasattr(value, attr):
                continue

            try:
                setattr(
                    value,
                    attr,
                    "local_gguf"
                    if preference == "local"
                    else "gemini",
                )
            except Exception:
                pass

    try:
        tui.active_provider = (
            "local_gguf"
            if preference == "local"
            else "gemini"
        )
    except Exception:
        pass

    return changed


def _instruction_history(tui: Any) -> list[str]:
    history = getattr(
        tui,
        "_semantic_live_instructions",
        None,
    )

    if not isinstance(history, list):
        history = []
        tui._semantic_live_instructions = history

    return history


def apply_live_instruction(
    tui: Any,
    active_request: str,
    instruction_text: str,
) -> str:
    """
    Apply an instruction as authoritative state.

    The returned request always contains the latest semantic requirements,
    so restarted generations and later intent refinement cannot lose them.
    """

    instruction = classify_instruction(instruction_text)

    if not instruction.raw:
        return active_request

    if instruction.provider:
        apply_provider_preference(
            tui,
            instruction.provider,
        )

        provider_name = (
            "local_gguf"
            if instruction.provider == "local"
            else "gemini"
        )

        print(
            f"[semantic steering] Provider preference is now "
            f"{provider_name}.",
            flush=True,
        )

    history = _instruction_history(tui)

    if not instruction.is_provider_only:
        history.append(instruction.raw)

    # Prevent unbounded repetition during several restarts.
    deduplicated: list[str] = []
    seen: set[str] = set()

    for item in history:
        normalized = _clean(item)
        marker = normalized.casefold()

        if not normalized or marker in seen:
            continue

        seen.add(marker)
        deduplicated.append(normalized)

    tui._semantic_live_instructions = deduplicated[-20:]

    base = _clean(
        getattr(tui, "_semantic_original_request", "")
        or active_request
    )

    if not getattr(tui, "_semantic_original_request", None):
        tui._semantic_original_request = base

    requirements = tui._semantic_live_instructions

    if not requirements:
        return base

    lines = [
        "CURRENT AUTHORITATIVE USER REQUEST",
        f"Original goal: {base}",
        "",
        "Live instructions received after the original request:",
    ]

    for index, item in enumerate(requirements, start=1):
        lines.append(f"{index}. {item}")

    lines.extend(
        [
            "",
            "Interpret these instructions semantically.",
            "The latest instruction overrides any conflicting earlier one.",
            "Retain every non-conflicting requirement in planning, "
            "implementation, validation, and the final result.",
        ]
    )

    merged = "\n".join(lines)

    try:
        tui.active_request = merged
    except Exception:
        pass

    return merged


def reset_semantic_request(tui: Any) -> None:
    tui._semantic_original_request = ""
    tui._semantic_live_instructions = []


def semantic_status(tui: Any) -> str:
    preference = getattr(
        tui,
        "_semantic_provider_preference",
        None,
    )

    instructions = list(
        getattr(
            tui,
            "_semantic_live_instructions",
            [],
        )
        or []
    )

    lines = [
        "Semantic steering:",
        f"- provider preference: {preference or 'session default'}",
        f"- retained live instructions: {len(instructions)}",
    ]

    for index, item in enumerate(instructions, start=1):
        lines.append(f"  {index}. {item}")

    return "\n".join(lines)
