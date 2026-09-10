"""Sparse experiential memory for human conversation.

SOPHYANE_CONVERSATION_EXPERIENTIAL_MEMORY_V1

Conversation memory is intentionally distinct from verified knowledge.

A conversation may be:
    experienced=True
without being:
    verified=True
    trusted_world_knowledge=True

This preserves the invariant:

    experienced != remembered != verified knowledge
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
import uuid

from pathlib import Path
from typing import Any, Mapping


_WORD_RE = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_.:-]{2,}"
)

_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "before",
    "being",
    "could",
    "does",
    "from",
    "have",
    "into",
    "just",
    "like",
    "more",
    "much",
    "should",
    "some",
    "than",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "very",
    "want",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "will",
    "with",
    "would",
    "your",
}

_EXPLICIT_MEMORY_PHRASES = (
    "remember",
    "don't forget",
    "do not forget",
    "important",
    "my preference",
    "i prefer",
    "i like",
    "i dislike",
    "my goal",
    "my plan",
    "we decided",
    "we agreed",
)


def _root() -> Path:
    configured = str(
        os.environ.get(
            "XERUS_HOME",
            "",
        )
        or ""
    ).strip()

    if configured:
        return Path(
            configured
        ).expanduser()

    return (
        Path.home()
        / ".local"
        / "share"
        / "xerus"
    )


def exact_conversation_path() -> Path:
    return (
        _root()
        / "conversation-turns.jsonl"
    )


def sparse_conversation_path() -> Path:
    return (
        _root()
        / "conversation-memory.jsonl"
    )


def _canonical_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _append_jsonl(
    path: Path,
    value: Mapping[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write(
            _canonical_json(
                dict(value)
            )
            + "\n"
        )


def _terms(
    value: object,
) -> list[str]:
    text = str(
        value
        or ""
    ).casefold()

    values: list[str] = []

    for match in _WORD_RE.findall(
        text
    ):
        term = match.strip(
            "._:-"
        )

        if (
            not term
            or term in _STOPWORDS
        ):
            continue

        values.append(
            term
        )

    return values


def _gist(
    text: object,
    *,
    maximum: int,
) -> str:
    value = " ".join(
        str(
            text
            or ""
        ).split()
    ).strip()

    if len(value) <= maximum:
        return value

    return (
        value[
            : maximum - 1
        ].rstrip()
        + "…"
    )


def _salience(
    user_text: str,
    assistant_text: str,
) -> float:
    text = str(
        user_text
        or ""
    ).strip()

    lowered = text.casefold()

    score = 0.12

    if len(text) >= 40:
        score += 0.12

    if len(text) >= 100:
        score += 0.10

    if len(text) >= 220:
        score += 0.08

    if "?" in text:
        score += 0.06

    if any(
        phrase in lowered
        for phrase in _EXPLICIT_MEMORY_PHRASES
    ):
        score += 0.35

    if re.search(
        r"\b\d+(?:\.\d+)?\b",
        text,
    ):
        score += 0.07

    user_terms = set(
        _terms(
            text
        )
    )

    reply_terms = set(
        _terms(
            assistant_text
        )
    )

    overlap = len(
        user_terms
        & reply_terms
    )

    if overlap >= 2:
        score += 0.08

    return min(
        1.0,
        score,
    )


def sparse_conversation_projection(
    event: Mapping[str, Any],
) -> dict[str, Any] | None:
    user_text = str(
        event.get(
            "user_text",
            "",
        )
        or ""
    ).strip()

    assistant_text = str(
        event.get(
            "assistant_text",
            "",
        )
        or ""
    ).strip()

    if not user_text:
        return None

    salience = _salience(
        user_text,
        assistant_text,
    )

    #
    # Ordinary acknowledgements and trivial greetings remain in exact
    # conversational history but should not occupy sparse long-term memory.
    #
    if salience < 0.26:
        return None

    topics: list[str] = []

    for term in (
        _terms(
            user_text
        )
        + _terms(
            assistant_text
        )
    ):
        if term in topics:
            continue

        topics.append(
            term
        )

        if len(topics) >= 10:
            break

    turn_id = str(
        event.get(
            "turn_id",
            "",
        )
        or ""
    )

    return {
        "memory_id": (
            "conversation:"
            + (
                turn_id
                or uuid.uuid4().hex
            )
        ),
        "kind": (
            "experiential_conversation_memory"
        ),
        "user_gist": _gist(
            user_text,
            maximum=420,
        ),
        "assistant_gist": _gist(
            assistant_text,
            maximum=300,
        ),
        "topics": topics,
        "salience": salience,
        "strength": min(
            1.0,
            0.45
            + salience * 0.45,
        ),
        "experienced": True,
        "remembered": True,
        "verified": False,
        "trusted": False,
        "accepted": False,
        "trusted_world_knowledge": False,
        "instruction_authority": False,
        "source_turn_id": turn_id,
        "created_at": float(
            event.get(
                "created_at",
                time.time(),
            )
            or time.time()
        ),
    }


def persist_conversation_turn(
    *,
    user_text: str,
    assistant_text: str,
    perception: Mapping[str, Any] | None = None,
    thought: Mapping[str, Any] | None = None,
    authority: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    turn_id = (
        "turn:"
        + uuid.uuid4().hex
    )

    event = {
        "turn_id": turn_id,
        "kind": "conversation_turn",
        "user_text": str(
            user_text
            or ""
        ),
        "assistant_text": str(
            assistant_text
            or ""
        ),
        "perception": dict(
            perception
            or {}
        ),
        "thought": dict(
            thought
            or {}
        ),
        "authority": dict(
            authority
            or {}
        ),
        "metadata": dict(
            metadata
            or {}
        ),
        "experienced": True,
        "verified": False,
        "trusted_world_knowledge": False,
        "instruction_authority": False,
        "created_at": time.time(),
    }

    _append_jsonl(
        exact_conversation_path(),
        event,
    )

    sparse = (
        sparse_conversation_projection(
            event
        )
    )

    if sparse is not None:
        _append_jsonl(
            sparse_conversation_path(),
            sparse,
        )

    return {
        "ok": True,
        "turn_id": turn_id,
        "exact_recorded": True,
        "sparse_memory_created": (
            sparse is not None
        ),
        "sparse_memory": sparse,
        "verified": False,
        "trusted_world_knowledge": False,
    }


def _read_sparse() -> list[dict[str, Any]]:
    path = sparse_conversation_path()

    if not path.exists():
        return []

    rows: list[
        dict[str, Any]
    ] = []

    for line in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        value = line.strip()

        if not value:
            continue

        try:
            payload = json.loads(
                value
            )

        except Exception:
            continue

        if isinstance(
            payload,
            dict,
        ):
            rows.append(
                payload
            )

    return rows


def recall_conversation_memories(
    query: str,
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    query_terms = set(
        _terms(
            query
        )
    )

    now = time.time()

    ranked: list[
        tuple[
            float,
            dict[str, Any],
        ]
    ] = []

    for memory in _read_sparse():
        text = (
            str(
                memory.get(
                    "user_gist",
                    "",
                )
            )
            + " "
            + str(
                memory.get(
                    "assistant_gist",
                    "",
                )
            )
            + " "
            + " ".join(
                memory.get(
                    "topics",
                    [],
                )
                or []
            )
        )

        terms = set(
            _terms(
                text
            )
        )

        overlap = len(
            query_terms
            & terms
        )

        if (
            query_terms
            and overlap == 0
        ):
            continue

        lexical = (
            overlap
            / max(
                1,
                len(
                    query_terms
                ),
            )
        )

        salience = float(
            memory.get(
                "salience",
                0.0,
            )
            or 0.0
        )

        strength = float(
            memory.get(
                "strength",
                0.0,
            )
            or 0.0
        )

        age_seconds = max(
            0.0,
            now
            - float(
                memory.get(
                    "created_at",
                    now,
                )
                or now
            ),
        )

        age_days = (
            age_seconds
            / 86400.0
        )

        recency = math.exp(
            -age_days
            / 180.0
        )

        score = (
            lexical * 0.55
            + salience * 0.20
            + strength * 0.15
            + recency * 0.10
        )

        item = dict(
            memory
        )

        item[
            "recall_score"
        ] = score

        #
        # Reassert boundaries during recall.
        #
        item[
            "verified"
        ] = False

        item[
            "trusted"
        ] = False

        item[
            "trusted_world_knowledge"
        ] = False

        item[
            "instruction_authority"
        ] = False

        ranked.append(
            (
                score,
                item,
            )
        )

    ranked.sort(
        key=lambda pair: (
            -pair[0],
            str(
                pair[1].get(
                    "memory_id",
                    "",
                )
            ),
        )
    )

    return [
        item
        for _score, item
        in ranked[
            : max(
                1,
                int(
                    limit
                ),
            )
        ]
    ]


def conversation_memory_status() -> dict[str, Any]:
    return {
        "marker": (
            "SOPHYANE_CONVERSATION_EXPERIENTIAL_MEMORY_V1"
        ),
        "exact_path": str(
            exact_conversation_path()
        ),
        "sparse_path": str(
            sparse_conversation_path()
        ),
        "conversation_is_experience": True,
        "conversation_is_verified_knowledge": False,
        "assistant_reply_is_verified_by_default": False,
        "instruction_authority": False,
    }


__all__ = [
    "conversation_memory_status",
    "exact_conversation_path",
    "persist_conversation_turn",
    "recall_conversation_memories",
    "sparse_conversation_path",
    "sparse_conversation_projection",
]
