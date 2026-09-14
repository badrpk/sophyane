"""Bounded in-memory conversation state for Sophyane Mode 6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ConversationRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class ConversationMessage:
    """One user-visible Mode-6 conversation message."""

    role: ConversationRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant"}:
            raise ValueError(
                "role must be 'user' or 'assistant'"
            )


class Mode6ConversationSession:
    """Keep a bounded ordered history of Mode-6 conversation turns."""

    def __init__(self, *, max_turns: int = 12) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns must be positive")

        self.max_turns = max_turns
        self._messages: list[ConversationMessage] = []

    def append_user(self, text: str) -> None:
        self._append("user", text)

    def append_assistant(self, text: str) -> None:
        self._append("assistant", text)

    def _append(
        self,
        role: ConversationRole,
        text: str,
    ) -> None:
        content = str(text or "").strip()

        if not content:
            return

        self._messages.append(
            ConversationMessage(
                role=role,
                content=content,
            )
        )

        overflow = len(self._messages) - self.max_turns

        if overflow > 0:
            del self._messages[:overflow]

    def recent_turns(self) -> list[dict[str, str]]:
        return [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in self._messages
        ]
