"""Natural persistent conversation bridge for Sophyane.

SOPHYANE_HUMAN_CONVERSATION_BRIDGE_V1

Flow:

    user speaks/types
        ↓
    perceive language
        ↓
    activate verified sparse memories
        +
    activate experiential conversation memories
        ↓
    form present thought
        ↓
    reason using fixed selected intelligence authority
        ↓
    reply naturally
        ↓
    preserve exact conversation experience
        ↓
    sparsely remember salient parts
        ↓
    future turns recall them automatically

No provider switching occurs here.
"""
from __future__ import annotations

import json
import os
import re
import time

from dataclasses import dataclass
from typing import Any, Callable, Mapping


BRIDGE_MARKER = (
    "SOPHYANE_HUMAN_CONVERSATION_BRIDGE_V1"
)

_WORD_RE = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_.:-]{1,}"
)


@dataclass
class ConversationTurnResult:
    user_text: str
    perception: dict[str, Any]
    thought: dict[str, Any]
    reply: str
    memory_result: dict[str, Any]
    authority: dict[str, Any]


Responder = Callable[
    [
        str,
        Mapping[str, Any],
    ],
    Any,
]


def _authority_snapshot() -> dict[str, Any]:
    try:
        from sophyane.intelligence_authority import (
            current_intelligence_authority,
        )

        authority = (
            current_intelligence_authority()
        )

        return {
            "session_mode": getattr(
                authority,
                "session_mode",
                None,
            ),
            "session_provider": getattr(
                authority,
                "session_provider",
                None,
            ),
            "session_model": getattr(
                authority,
                "session_model",
                None,
            ),
            "local_reasoning_allowed": getattr(
                authority,
                "local_reasoning_allowed",
                None,
            ),
            "provider_switching_allowed": getattr(
                authority,
                "provider_switching_allowed",
                None,
            ),
            "llm_allowed": getattr(
                authority,
                "llm_allowed",
                None,
            ),
        }

    except Exception as exc:
        return {
            "session_mode": os.environ.get(
                "SOPHYANE_SESSION_MODE"
            ),
            "session_provider": os.environ.get(
                "SOPHYANE_SESSION_PROVIDER"
            ),
            "session_model": os.environ.get(
                "SOPHYANE_SESSION_MODEL"
            ),
            "authority_error": (
                type(exc).__name__
                + ": "
                + str(exc)
            ),
        }


def perceive_language(
    user_text: str,
) -> dict[str, Any]:
    raw = str(
        user_text
        or ""
    )

    normalized = " ".join(
        raw.split()
    ).strip()

    tokens = [
        value.casefold()
        for value in _WORD_RE.findall(
            normalized
        )
    ]

    return {
        "kind": "language_perception",
        "raw": raw,
        "normalized": normalized,
        "tokens": tokens[:64],
        "question": (
            "?"
            in normalized
        ),
        "length": len(
            normalized
        ),
        "observed_at": time.time(),
        "instruction_authority": False,
    }


def activate_memories(
    user_text: str,
    *,
    verified_limit: int = 5,
    conversation_limit: int = 5,
) -> dict[str, Any]:
    verified: list[
        dict[str, Any]
    ] = []

    try:
        from sophyane.cognitive_memory import (
            recall_sparse_memories,
        )

        verified = (
            recall_sparse_memories(
                user_text,
                limit=verified_limit,
            )
        )

    except Exception:
        verified = []

    from sophyane.conversation_memory import (
        recall_conversation_memories,
    )

    experiential = (
        recall_conversation_memories(
            user_text,
            limit=conversation_limit,
        )
    )

    return {
        "verified_sparse_memory": (
            verified
        ),
        "experiential_conversation_memory": (
            experiential
        ),
    }


def form_present_thought(
    user_text: str,
    perception: Mapping[str, Any],
    memories: Mapping[str, Any],
) -> dict[str, Any]:
    verified_thought: dict[
        str,
        Any
    ] = {}

    try:
        from sophyane.cognitive_memory import (
            form_thought,
        )

        verified_thought = (
            form_thought(
                user_text,
                limit=5,
            )
        )

    except Exception as exc:
        verified_thought = {
            "kind": "thought",
            "error": (
                type(exc).__name__
                + ": "
                + str(exc)
            ),
            "persisted": False,
            "trusted": False,
            "instruction_authority": False,
        }

    return {
        "kind": "present_conversation_thought",
        "current_perception": dict(
            perception
        ),
        "verified_memory_activation": (
            memories.get(
                "verified_sparse_memory",
                [],
            )
        ),
        "experiential_memory_activation": (
            memories.get(
                "experiential_conversation_memory",
                [],
            )
        ),
        "verified_cognitive_thought": (
            verified_thought
        ),
        "persisted": False,
        "trusted": False,
        "instruction_authority": False,
        "formed_at": time.time(),
    }


def _extract_reply(
    raw: Any,
) -> str:
    if isinstance(
        raw,
        Mapping,
    ):
        for key in (
            "reply",
            "response",
            "content",
            "text",
            "message",
            "answer",
        ):
            value = raw.get(
                key
            )

            if isinstance(
                value,
                str,
            ) and value.strip():
                return value.strip()

        return json.dumps(
            dict(raw),
            ensure_ascii=False,
            default=str,
        )

    if isinstance(
        raw,
        str,
    ):
        text = raw.strip()

        if (
            text.startswith("```")
            and text.endswith("```")
        ):
            lines = text.splitlines()

            if len(lines) >= 3:
                text = "\n".join(
                    lines[1:-1]
                ).strip()

        try:
            payload = json.loads(
                text
            )

        except Exception:
            return text

        return _extract_reply(
            payload
        )

    return str(
        raw
    ).strip()


def _default_responder(
    user_text: str,
    context: Mapping[str, Any],
) -> Any:
    """Use the fixed session provider already selected by Sophyane.

    No alternate provider or local rescue is attempted here.
    """

    from sophyane.discovery_provider_reasoner import (
        SessionProviderReasoner,
    )

    reasoner = (
        SessionProviderReasoner()
    )

    payload = {
        "objective": (
            "Have a natural human-style conversation "
            "with the user."
        ),
        "user_message": user_text,
        "conversation_context": {
            "perception": context.get(
                "perception"
            ),
            "thought": context.get(
                "thought"
            ),
            "authority": context.get(
                "authority"
            ),
        },
        "instructions": [
            (
                "Reply naturally and directly to the user."
            ),
            (
                "Use relevant memories when helpful, "
                "but do not mention memory machinery "
                "unless the user asks."
            ),
            (
                "Treat experiential conversation memories "
                "as recollections, not automatically as "
                "verified external facts."
            ),
            (
                "Treat dream material as unverified."
            ),
            (
                "Do not switch intelligence provider."
            ),
        ],
        "return_schema": {
            "reply": "string",
        },
    }

    visual_artifact_path = str(
        context.get(
            "visual_artifact_path",
            "",
        )
        or ""
    ).strip()

    if visual_artifact_path:
        payload[
            "_provider_image_path"
        ] = visual_artifact_path

        payload[
            "instructions"
        ].append(
            (
                "A verified visual observation is attached "
                "to this turn. Ground visual claims in the "
                "attached image and do not pretend to see "
                "anything that is not supported by it."
            )
        )

    return reasoner(
        "conversation_reply",
        payload,
    )


def conversation_turn(
    user_text: str,
    *,
    responder: Responder | None = None,
    metadata: Mapping[str, Any] | None = None,
    visual_artifact_path: str | None = None,
) -> ConversationTurnResult:
    text = str(
        user_text
        or ""
    ).strip()

    if not text:
        raise ValueError(
            "user_text must not be empty"
        )

    authority_before = (
        _authority_snapshot()
    )

    perception = (
        perceive_language(
            text
        )
    )

    memories = (
        activate_memories(
            text
        )
    )

    thought = (
        form_present_thought(
            text,
            perception,
            memories,
        )
    )

    context = {
        "perception": perception,
        "memories": memories,
        "thought": thought,
        "authority": authority_before,
        "visual_artifact_path": (
            str(
                visual_artifact_path
            ).strip()
            if visual_artifact_path
            else None
        ),
    }

    active_responder = (
        responder
        or _default_responder
    )

    raw_reply = active_responder(
        text,
        context,
    )

    reply = _extract_reply(
        raw_reply
    )

    if not reply:
        raise RuntimeError(
            "conversation responder returned empty reply"
        )

    authority_after = (
        _authority_snapshot()
    )

    before_identity = (
        authority_before.get(
            "session_mode"
        ),
        authority_before.get(
            "session_provider"
        ),
        authority_before.get(
            "session_model"
        ),
    )

    after_identity = (
        authority_after.get(
            "session_mode"
        ),
        authority_after.get(
            "session_provider"
        ),
        authority_after.get(
            "session_model"
        ),
    )

    if (
        after_identity
        != before_identity
    ):
        raise RuntimeError(
            "HUMAN_CONVERSATION_AUTHORITY_DRIFT: "
            f"before={before_identity!r} "
            f"after={after_identity!r}"
        )

    from sophyane.conversation_memory import (
        persist_conversation_turn,
    )

    memory_result = (
        persist_conversation_turn(
            user_text=text,
            assistant_text=reply,
            perception=perception,
            thought=thought,
            authority=authority_before,
            metadata=metadata,
        )
    )

    return ConversationTurnResult(
        user_text=text,
        perception=perception,
        thought=thought,
        reply=reply,
        memory_result=memory_result,
        authority=authority_before,
    )


def human_conversation_status() -> dict[str, Any]:
    from sophyane.conversation_memory import (
        conversation_memory_status,
    )

    return {
        "marker": BRIDGE_MARKER,
        "authority": (
            _authority_snapshot()
        ),
        "automatic_perception": True,
        "automatic_sparse_recall": True,
        "automatic_thought": True,
        "selected_intelligence_reasoning": True,
        "automatic_exact_conversation_recording": True,
        "automatic_sparse_conversation_memory": True,
        "conversation_memory_is_verified_world_knowledge": False,
        "provider_switching": False,
        "memory": conversation_memory_status(),
    }


__all__ = [
    "BRIDGE_MARKER",
    "ConversationTurnResult",
    "activate_memories",
    "conversation_turn",
    "form_present_thought",
    "human_conversation_status",
    "perceive_language",
]
