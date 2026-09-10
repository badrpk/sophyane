"""Provider-aware context admission for Sophyane model calls."""

from __future__ import annotations

from dataclasses import dataclass, field

from sophyane.providers.base import ProviderCapabilities


@dataclass(frozen=True)
class ContextItem:
    """One model-facing context unit."""

    label: str
    content: str
    priority: int = 0
    pinned: bool = False


@dataclass
class ContextPacket:
    """Structured context before provider-specific admission."""

    items: list[ContextItem] = field(default_factory=list)

    def add(
        self,
        label: str,
        content: str,
        *,
        priority: int = 0,
        pinned: bool = False,
    ) -> None:
        self.items.append(
            ContextItem(
                label=str(label),
                content=str(content),
                priority=int(priority),
                pinned=bool(pinned),
            )
        )


@dataclass(frozen=True)
class ContextBuildResult:
    text: str
    included: tuple[ContextItem, ...]
    omitted: tuple[ContextItem, ...]
    max_input_chars: int | None


class ContextBuilder:
    """Admit useful context according to effective provider capacity.

    Numeric token windows receive a conservative character budget.

    ``provider_managed_context`` means the external session owns admission,
    so Sophyane preserves the complete packet instead of inventing a smaller
    ceiling.

    Unknown numeric capacity is also left unbounded here. Unknown does not
    mean unlimited; it means this layer lacks evidence for a truthful limit.
    Provider adapters should expose numeric capability when they know it.
    """

    # SOPHYANE_PROVIDER_AWARE_CONTEXT_BUILDER_V1
    def __init__(
        self,
        capabilities: ProviderCapabilities,
        *,
        chars_per_token: int = 3,
        safety_ratio: float = 0.08,
        reserved_output_tokens: int | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.chars_per_token = max(
            1,
            int(chars_per_token),
        )
        self.safety_ratio = min(
            0.25,
            max(
                0.0,
                float(safety_ratio),
            ),
        )
        self.reserved_output_tokens = (
            None
            if reserved_output_tokens is None
            else max(
                0,
                int(reserved_output_tokens),
            )
        )

    @staticmethod
    def _item_size(item: ContextItem) -> int:
        # Match the rendered representation closely enough for admission.
        return (
            len(item.label)
            + len(item.content)
            + 4
        )

    @staticmethod
    def _render(items: list[ContextItem]) -> str:
        return "\n\n".join(
            f"[{item.label}]\n{item.content}"
            for item in items
        )

    def max_input_chars(self) -> int | None:
        caps = self.capabilities

        if caps.provider_managed_context:
            return None

        context_tokens = caps.context_window_tokens

        if context_tokens is None:
            # Do not fabricate a universal cloud/model context ceiling.
            return None

        context_tokens = max(
            1,
            int(context_tokens),
        )

        safety_tokens = max(
            32,
            int(
                context_tokens
                * self.safety_ratio
            ),
        )

        if self.reserved_output_tokens is not None:
            output_reserve = self.reserved_output_tokens
        elif caps.max_output_tokens is not None:
            # A provider's maximum output can be as large as or larger than
            # its context window. Reserving all of it would leave no prompt.
            output_reserve = min(
                max(
                    0,
                    int(caps.max_output_tokens),
                ),
                max(
                    256,
                    context_tokens // 4,
                ),
            )
        else:
            output_reserve = max(
                256,
                context_tokens // 4,
            )

        available_tokens = max(
            1,
            context_tokens
            - safety_tokens
            - output_reserve,
        )

        return (
            available_tokens
            * self.chars_per_token
        )

    def build(
        self,
        packet: ContextPacket,
    ) -> ContextBuildResult:
        items = list(packet.items)
        limit = self.max_input_chars()

        if limit is None:
            return ContextBuildResult(
                text=self._render(items),
                included=tuple(items),
                omitted=(),
                max_input_chars=None,
            )

        included = list(items)
        omitted: list[ContextItem] = []

        def total_size() -> int:
            if not included:
                return 0

            return (
                sum(
                    self._item_size(item)
                    for item in included
                )
                + (
                    2
                    * (
                        len(included)
                        - 1
                    )
                )
            )

        while (
            included
            and total_size() > limit
        ):
            candidates = [
                (
                    item.priority,
                    index,
                )
                for index, item in enumerate(included)
                if not item.pinned
            ]

            if not candidates:
                # Pinned context makes the numeric budget soft. The immutable
                # goal is more important than silently deleting requirements.
                break

            _, victim = min(candidates)
            omitted.append(
                included.pop(victim)
            )

        # Omission order describes eviction order; included context preserves
        # original packet ordering for model readability.
        return ContextBuildResult(
            text=self._render(included),
            included=tuple(included),
            omitted=tuple(omitted),
            max_input_chars=limit,
        )
