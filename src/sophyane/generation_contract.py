"""Explicit provider-generation contracts.

Generation mode is selected by the caller rather than inferred from ordinary
natural-language phrases. Contract markers may survive agent/runtime wrapping,
so parsing deliberately searches the complete prompt instead of requiring the
marker to be the first character.
"""

from __future__ import annotations

from dataclasses import dataclass


PREFIX = "[[SOPHYANE_GENERATION:"
SUFFIX = "]]"

VALID_MODES = frozenset(
    {
        "structured",
        "raw_artifact",
        "continuation",
        "chat",
    }
)


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    mode: str = "structured"
    minimum_output_tokens: int = 0


def mark_generation(
    prompt: str,
    *,
    mode: str,
    minimum_output_tokens: int = 0,
) -> str:
    clean_mode = str(mode or "structured").strip().lower()

    if clean_mode not in VALID_MODES:
        raise ValueError(
            f"Unsupported Sophyane generation mode: {clean_mode!r}"
        )

    minimum = max(0, int(minimum_output_tokens or 0))

    return (
        f"{PREFIX}{clean_mode};MIN={minimum}{SUFFIX}\n"
        f"{prompt}"
    )


def mark_raw_artifact(
    prompt: str,
    *,
    minimum_output_tokens: int = 4096,
) -> str:
    return mark_generation(
        prompt,
        mode="raw_artifact",
        minimum_output_tokens=minimum_output_tokens,
    )


def parse_generation_request(prompt: str) -> GenerationRequest:
    """Extract an explicit generation contract from a possibly wrapped prompt."""

    value = str(prompt or "")
    start = value.find(PREFIX)

    if start < 0:
        return GenerationRequest(prompt=value)

    end = value.find(SUFFIX, start + len(PREFIX))

    if end < 0:
        return GenerationRequest(prompt=value)

    header = value[start + len(PREFIX):end]
    pieces = [
        item.strip()
        for item in header.split(";")
        if item.strip()
    ]

    mode = pieces[0].lower() if pieces else "structured"

    if mode not in VALID_MODES:
        # Do not let arbitrary prompt text activate an unknown provider mode.
        return GenerationRequest(prompt=value)

    minimum = 0

    for piece in pieces[1:]:
        key, separator, raw_value = piece.partition("=")

        if separator and key.strip().upper() == "MIN":
            try:
                minimum = max(0, int(raw_value.strip()))
            except ValueError:
                minimum = 0

    # Remove only the recognized control marker. Keep surrounding runtime
    # context because it may contain useful task instructions.
    cleaned = (
        value[:start]
        + value[end + len(SUFFIX):]
    ).strip()

    return GenerationRequest(
        prompt=cleaned,
        mode=mode,
        minimum_output_tokens=minimum,
    )
