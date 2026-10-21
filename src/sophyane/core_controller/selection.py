"""Pure, deterministic mode selection for the Sophyane controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import ControllerContext, ControllerRequest, ModeName


@dataclass(frozen=True)
class ModeSelection:
    mode: ModeName
    source: str


def _coerce_mode(value: ModeName | str | None) -> ModeName | None:
    if value is None:
        return None
    if isinstance(value, ModeName):
        return value
    try:
        return ModeName(str(value))
    except ValueError as error:
        raise ValueError(f"mode unavailable: {value!r}") from error


def select_mode(
    request: ControllerRequest,
    context: ControllerContext,
    *,
    classifier: Callable[[ControllerRequest], ModeName | str | None] | None = None,
) -> ModeSelection:
    available = set(context.available_modes) or set(ModeName)

    def choose(candidate: ModeName | str | None, source: str) -> ModeSelection | None:
        mode = _coerce_mode(candidate)
        if mode is None:
            return None
        if mode not in available:
            raise ValueError(f"mode unavailable: {mode.value}")
        return ModeSelection(mode, source)

    selected = choose(request.requested_mode, "explicit")
    if selected is not None:
        return selected
    selected = choose(context.session_mode, "session")
    if selected is not None:
        return selected
    if classifier is not None:
        selected = choose(classifier(request), "classifier")
        if selected is not None:
            return selected
    return choose(ModeName.HUMAN_CONVERSATION, "default")  # type: ignore[return-value]
