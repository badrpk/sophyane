"""Sparse human-like cognitive memory derived from verified execution episodes.

SOPHYANE_SPARSE_COGNITIVE_MEMORY_V1

Epistemic boundaries:

    raw execution episode
        exact evidence / audit trail

    sparse memory
        lossy, salient projection of something that happened

    thought
        temporary activation and association of sparse memories

    dream
        unverified recombination of memories

A dream is never trusted evidence.
A thought is never execution evidence.
Sparse memory never replaces the authoritative raw episode.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time

from pathlib import Path
from typing import Any


_LOCK = threading.RLock()

_MEMORY_NAMESPACE = (
    "sophyane-sparse-cognitive-memory"
)

_STOP_WORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "and",
    "are",
    "because",
    "been",
    "before",
    "being",
    "between",
    "both",
    "but",
    "can",
    "could",
    "did",
    "does",
    "during",
    "each",
    "for",
    "from",
    "had",
    "has",
    "have",
    "into",
    "its",
    "may",
    "more",
    "must",
    "not",
    "only",
    "other",
    "our",
    "should",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "use",
    "used",
    "using",
    "was",
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

_WORD_RE = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_.:-]{2,}"
)

_SENTENCE_RE = re.compile(
    r"(?<=[.!?])\s+|\n+"
)

# SOPHYANE_DREAM_SEMANTIC_HYGIENE_V1
#
# Dream association must operate on semantic experience, not on
# serialization fields, verifier bookkeeping, booleans, trace metadata,
# or other implementation vocabulary that happens to recur in episodes.
_DREAM_BOOKKEEPING_TERMS = {
    "accepted",
    "authoritative",
    "capability_class",
    "created_at",
    "dream_id",
    "event_key",
    "evidence",
    "false",
    "instruction_authority",
    "memory_id",
    "metadata",
    "model_identity",
    "passed",
    "provider_identity",
    "reward",
    "score",
    "session_mode",
    "source",
    "source_dream_id",
    "source_event_key",
    "source_trace_id",
    "status",
    "trace_id",
    "true",
    "trusted",
    "unverified",
    "validator",
    "verification",
    "verification_evidence",
    "verification_state",
    "verified",
    "verified_origin",
}


def _dream_semantic_term(value: object) -> str | None:
    term = str(value or "").strip().casefold()

    if not term:
        return None

    if term in _DREAM_BOOKKEEPING_TERMS:
        return None

    #
    # Serialization identifiers must not become concepts merely
    # because they recur across episodes.
    #
    if re.fullmatch(
        r"phase\d+(?:[-_][a-z0-9_.:-]+)*",
        term,
    ):
        return None

    if re.fullmatch(
        r"(?:test|trace|event)[-_]?[a-z0-9_.:-]*",
        term,
    ):
        return None

    if re.fullmatch(
        r"dream(?::|[-_]).+",
        term,
    ):
        return None

    #
    # Validator implementations often appear as names such as
    # smoke-validator, deterministic-validator, validator-v2, etc.
    # Those are provenance machinery, not remembered subject matter.
    #
    if (
        term == "validator"
        or term.startswith("validator-")
        or term.startswith("validator_")
        or term.endswith("-validator")
        or term.endswith("_validator")
    ):
        return None

    #
    # Boolean / null serialization values have no semantic value.
    #
    if term in {
        "true",
        "false",
        "none",
        "null",
    }:
        return None

    return term


def _root() -> Path:
    """Use the same Xerus home authority as episodic_memory."""
    value = str(
        os.environ.get(
            "XERUS_HOME",
            "",
        )
        or ""
    ).strip()

    if value:
        return Path(
            value
        ).expanduser()

    return (
        Path.home()
        / ".local"
        / "share"
        / "xerus"
    )


def _memory_journal() -> Path:
    return (
        _root()
        / "cognitive-memory.jsonl"
    )


def _dream_journal() -> Path:
    return (
        _root()
        / "cognitive-dreams.jsonl"
    )


def _canonical_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        default=str,
    )


def _digest(
    value: object,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            value
        ).encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()


def _trusted_episode(
    event: object,
) -> bool:
    if not isinstance(
        event,
        dict,
    ):
        return False

    if event.get(
        "accepted"
    ) is not True:
        return False

    if (
        str(
            event.get(
                "verification_state",
                "",
            )
            or ""
        ).casefold()
        != "verified"
    ):
        return False

    if (
        str(
            event.get(
                "status",
                "",
            )
            or ""
        ).casefold()
        not in {
            "success",
            "succeeded",
            "completed",
        }
    ):
        return False

    evidence = event.get(
        "verification_evidence"
    )

    return bool(
        isinstance(
            evidence,
            (
                list,
                dict,
            ),
        )
        and evidence
    )


def _terms(
    text: object,
) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for match in _WORD_RE.findall(
        str(
            text
            or ""
        )
    ):
        value = (
            match
            .strip("._:-")
            .casefold()
        )

        if (
            len(value) < 3
            or value in _STOP_WORDS
            or value.isdigit()
            or value in seen
        ):
            continue

        seen.add(
            value
        )

        result.append(
            value
        )

    return result


def _sentences(
    text: object,
) -> list[str]:
    raw = str(
        text
        or ""
    ).strip()

    if not raw:
        return []

    values: list[str] = []

    for piece in _SENTENCE_RE.split(
        raw
    ):
        value = " ".join(
            piece.split()
        ).strip()

        if not value:
            continue

        values.append(
            value[:420]
        )

    return values


def _fragment_score(
    text: str,
    *,
    source: str,
) -> float:
    lowered = text.casefold()

    score = 0.0

    if source == "objective":
        score += 0.45

    elif source == "verification":
        score += 0.35

    elif source == "result":
        score += 0.20

    important = (
        "verified",
        "failed",
        "failure",
        "error",
        "passed",
        "lesson",
        "remember",
        "unexpected",
        "improved",
        "regression",
        "success",
        "blocked",
    )

    score += min(
        0.30,
        0.05
        * sum(
            marker in lowered
            for marker in important
        ),
    )

    #
    # Unique symbolic markers are often salient in experiments:
    # PHASE6D_MEMORY_TOKEN_..., test IDs, protocol markers, etc.
    #
    if re.search(
        r"\b[A-Z][A-Z0-9_]{7,}\b",
        text,
    ):
        score += 0.20

    term_count = len(
        _terms(
            text
        )
    )

    score += min(
        0.10,
        term_count
        / 200.0,
    )

    return min(
        1.0,
        score,
    )


def _verification_text(
    event: dict[str, Any],
) -> str:
    evidence = event.get(
        "verification_evidence"
    )

    if not evidence:
        return ""

    try:
        return _canonical_json(
            evidence
        )

    except Exception:
        return str(
            evidence
        )


def sparse_projection(
    event: dict[str, Any],
) -> dict[str, Any]:
    """Create a deliberately lossy projection of one verified episode."""

    if not _trusted_episode(
        event
    ):
        return {
            "ok": False,
            "reason": (
                "episode is not trusted "
                "verified experience"
            ),
        }

    objective = str(
        event.get(
            "original_objective",
            "",
        )
        or ""
    ).strip()

    result = str(
        event.get(
            "result",
            "",
        )
        or ""
    ).strip()

    verification = (
        _verification_text(
            event
        )
    )

    candidates: list[
        tuple[
            float,
            int,
            str,
            str,
        ]
    ] = []

    order = 0

    for source, text in (
        (
            "objective",
            objective,
        ),
        (
            "verification",
            verification,
        ),
        (
            "result",
            result,
        ),
    ):
        for sentence in _sentences(
            text
        ):
            candidates.append(
                (
                    _fragment_score(
                        sentence,
                        source=source,
                    ),
                    order,
                    source,
                    sentence,
                )
            )
            order += 1

    candidates.sort(
        key=lambda item: (
            item[0],
            -item[1],
        ),
        reverse=True,
    )

    fragments: list[
        dict[str, Any]
    ] = []

    seen: set[str] = set()

    total_chars = 0

    #
    # Human-like sparsity boundary:
    #
    # no more than 5 remembered fragments
    # no more than ~1200 chars total
    #
    for (
        score,
        _,
        source,
        text,
    ) in candidates:
        normalized = (
            text
            .casefold()
            .strip()
        )

        if normalized in seen:
            continue

        remaining = (
            1200
            - total_chars
        )

        if remaining <= 0:
            break

        value = text[
            :min(
                360,
                remaining,
            )
        ]

        if not value:
            continue

        seen.add(
            normalized
        )

        fragments.append(
            {
                "source": source,
                "content": value,
                "salience": round(
                    float(
                        score
                    ),
                    6,
                ),
            }
        )

        total_chars += len(
            value
        )

        if len(
            fragments
        ) >= 5:
            break

    entity_source = (
        objective
        + " "
        + " ".join(
            item[
                "content"
            ]
            for item in fragments
        )
    )

    entities = _terms(
        entity_source
    )[:16]

    trace_id = str(
        event.get(
            "trace_id",
            "",
        )
        or ""
    ).strip()

    event_key = str(
        event.get(
            "event_key",
            "",
        )
        or ""
    ).strip()

    identity = (
        event_key
        or trace_id
        or _digest(
            {
                "objective": objective,
                "provider": event.get(
                    "provider_identity"
                ),
                "created_at": event.get(
                    "created_at"
                ),
            }
        )[:32]
    )

    initial_salience = 0.70

    if any(
        item[
            "salience"
        ] >= 0.75
        for item in fragments
    ):
        initial_salience += 0.10

    if (
        float(
            event.get(
                "reward",
                0.0,
            )
            or 0.0
        )
        >= 0.9
    ):
        initial_salience += 0.10

    initial_salience = min(
        1.0,
        initial_salience,
    )

    gist = ""

    if fragments:
        objective_fragments = [
            item
            for item in fragments
            if item[
                "source"
            ] == "objective"
        ]

        selected = (
            objective_fragments[0]
            if objective_fragments
            else fragments[0]
        )

        gist = str(
            selected[
                "content"
            ]
        )[:300]

    memory = {
        "memory_id": (
            "sparse:"
            + identity
        ),
        "kind": "sparse_memory",
        "namespace": (
            _MEMORY_NAMESPACE
        ),
        "source_trace_id": (
            trace_id
            or None
        ),
        "source_event_key": (
            event_key
            or None
        ),
        "gist": gist,
        "fragments": fragments,
        "entities": entities,
        "salience": round(
            initial_salience,
            6,
        ),
        "strength": round(
            initial_salience,
            6,
        ),
        "activation_count": 0,
        "created_at": float(
            event.get(
                "created_at",
                time.time(),
            )
            or time.time()
        ),
        "last_activated_at": None,
        "trusted": True,
        "experienced": True,
        "verified_origin": True,
        "instruction_authority": False,
        "lossy_projection": True,
        "raw_trace_hash": _digest(
            event
        ),
        "provider_identity": event.get(
            "provider_identity"
        ),
        "model_identity": event.get(
            "model_identity"
        ),
        "session_mode": event.get(
            "session_mode"
        ),
        "capability_class": event.get(
            "capability_class"
        ),
    }

    return {
        "ok": True,
        "memory": memory,
    }


def _latest_records(
    path: Path,
) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    latest: dict[
        str,
        dict[str, Any],
    ] = {}

    try:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()

    except Exception:
        return {}

    for line in lines[-5000:]:
        try:
            item = json.loads(
                line
            )

        except Exception:
            continue

        if not isinstance(
            item,
            dict,
        ):
            continue

        key = str(
            item.get(
                "memory_id",
                "",
            )
            or ""
        ).strip()

        if not key:
            continue

        latest[
            key
        ] = item

    return latest


def _append(
    path: Path,
    item: dict[str, Any],
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
                item
            )
            + "\n"
        )


def consolidate_verified_episode(
    event: dict[str, Any],
) -> dict[str, Any]:
    """Convert one trusted raw episode into sparse long-term memory."""

    projection = sparse_projection(
        event
    )

    if projection.get(
        "ok"
    ) is not True:
        return projection

    memory = dict(
        projection[
            "memory"
        ]
    )

    path = _memory_journal()

    with _LOCK:
        existing = _latest_records(
            path
        ).get(
            memory[
                "memory_id"
            ]
        )

        if (
            isinstance(
                existing,
                dict,
            )
            and existing.get(
                "raw_trace_hash"
            )
            == memory.get(
                "raw_trace_hash"
            )
        ):
            return {
                "ok": True,
                "memory_id": memory[
                    "memory_id"
                ],
                "path": str(
                    path
                ),
                "deduplicated": True,
                "trusted": True,
                "lossy_projection": True,
            }

        _append(
            path,
            memory,
        )

    return {
        "ok": True,
        "memory_id": memory[
            "memory_id"
        ],
        "path": str(
            path
        ),
        "deduplicated": False,
        "trusted": True,
        "lossy_projection": True,
    }


def _effective_strength(
    item: dict[str, Any],
    *,
    now: float,
) -> float:
    strength = max(
        0.0,
        min(
            1.0,
            float(
                item.get(
                    "strength",
                    0.0,
                )
                or 0.0
            ),
        ),
    )

    created = float(
        item.get(
            "last_activated_at",
            item.get(
                "created_at",
                now,
            ),
        )
        or now
    )

    age_days = max(
        0.0,
        (
            now
            - created
        )
        / 86400.0,
    )

    #
    # Slow forgetting curve.
    #
    # Strength halves roughly every 180 days
    # when never reactivated.
    #
    decay = math.pow(
        0.5,
        age_days
        / 180.0,
    )

    return (
        strength
        * decay
    )


def recall_sparse_memories(
    query: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Read relevant sparse memories without mutating them."""

    limit = max(
        1,
        min(
            int(
                limit
            ),
            16,
        ),
    )

    memories = list(
        _latest_records(
            _memory_journal()
        ).values()
    )

    if not memories:
        return []

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

    for item in memories:
        if item.get(
            "kind"
        ) != "sparse_memory":
            continue

        searchable = (
            str(
                item.get(
                    "gist",
                    "",
                )
            )
            + " "
            + " ".join(
                str(
                    fragment.get(
                        "content",
                        "",
                    )
                )
                for fragment in item.get(
                    "fragments",
                    []
                )
                if isinstance(
                    fragment,
                    dict,
                )
            )
            + " "
            + " ".join(
                str(
                    value
                )
                for value in item.get(
                    "entities",
                    []
                )
            )
        )

        memory_terms = set(
            _terms(
                searchable
            )
        )

        if query_terms:
            overlap = len(
                query_terms
                & memory_terms
            )

            if overlap <= 0:
                continue

            relevance = (
                overlap
                / max(
                    1,
                    len(
                        query_terms
                    ),
                )
            )

        else:
            relevance = 0.0

        strength = (
            _effective_strength(
                item,
                now=now,
            )
        )

        salience = float(
            item.get(
                "salience",
                0.0,
            )
            or 0.0
        )

        score = (
            (
                relevance
                * 0.65
            )
            + (
                strength
                * 0.20
            )
            + (
                salience
                * 0.15
            )
        )

        row = dict(
            item
        )

        row[
            "recall_score"
        ] = round(
            score,
            6,
        )

        row[
            "effective_strength"
        ] = round(
            strength,
            6,
        )

        ranked.append(
            (
                score,
                row,
            )
        )

    ranked.sort(
        key=lambda pair: (
            pair[0],
            float(
                pair[1].get(
                    "created_at",
                    0.0,
                )
                or 0.0
            ),
        ),
        reverse=True,
    )

    return [
        item
        for _, item
        in ranked[:limit]
    ]


def _reinforce(
    memories: list[dict[str, Any]],
) -> None:
    """Activation makes frequently useful memories slightly stronger."""

    if not memories:
        return

    path = _memory_journal()
    now = time.time()

    with _LOCK:
        latest = _latest_records(
            path
        )

        for selected in memories:
            memory_id = str(
                selected.get(
                    "memory_id",
                    "",
                )
                or ""
            )

            current = latest.get(
                memory_id
            )

            if not isinstance(
                current,
                dict,
            ):
                continue

            strength = max(
                0.0,
                min(
                    1.0,
                    float(
                        current.get(
                            "strength",
                            0.0,
                        )
                        or 0.0
                    ),
                ),
            )

            #
            # Small Hebbian-like reinforcement.
            #
            # It deliberately saturates rather than growing without bound.
            #
            strength = (
                strength
                + (
                    0.04
                    * (
                        1.0
                        - strength
                    )
                )
            )

            updated = dict(
                current
            )

            updated[
                "strength"
            ] = round(
                min(
                    1.0,
                    strength,
                ),
                6,
            )

            updated[
                "activation_count"
            ] = (
                int(
                    current.get(
                        "activation_count",
                        0,
                    )
                    or 0
                )
                + 1
            )

            updated[
                "last_activated_at"
            ] = now

            _append(
                path,
                updated,
            )


def form_thought(
    query: str,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """Temporarily activate and associate relevant sparse memories."""

    memories = recall_sparse_memories(
        query,
        limit=limit,
    )

    if not memories:
        return {
            "kind": "thought",
            "query": str(
                query
                or ""
            ),
            "memory_ids": [],
            "fragments": [],
            "associations": [],
            "created_at": time.time(),
            "persisted": False,
            "trusted": False,
            "instruction_authority": False,
            "epistemic_status": (
                "temporary_activation"
            ),
        }

    _reinforce(
        memories
    )

    fragments: list[str] = []

    seen_fragments: set[str] = set()

    for memory in memories:
        gist = str(
            memory.get(
                "gist",
                "",
            )
            or ""
        ).strip()

        if (
            gist
            and gist.casefold()
            not in seen_fragments
        ):
            fragments.append(
                gist[:320]
            )
            seen_fragments.add(
                gist.casefold()
            )

        for item in memory.get(
            "fragments",
            [],
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            value = str(
                item.get(
                    "content",
                    "",
                )
                or ""
            ).strip()

            if (
                not value
                or value.casefold()
                in seen_fragments
            ):
                continue

            fragments.append(
                value[:320]
            )
            seen_fragments.add(
                value.casefold()
            )

            if len(
                fragments
            ) >= 8:
                break

        if len(
            fragments
        ) >= 8:
            break

    associations: list[
        dict[str, Any]
    ] = []

    for index, left in enumerate(
        memories
    ):
        left_terms = set(
            left.get(
                "entities",
                [],
            )
        )

        for right in memories[
            index
            + 1:
        ]:
            shared = sorted(
                left_terms
                & set(
                    right.get(
                        "entities",
                        [],
                    )
                )
            )

            if not shared:
                continue

            associations.append(
                {
                    "left": left.get(
                        "memory_id"
                    ),
                    "right": right.get(
                        "memory_id"
                    ),
                    "shared": shared[:6],
                }
            )

            if len(
                associations
            ) >= 6:
                break

        if len(
            associations
        ) >= 6:
            break

    return {
        "kind": "thought",
        "query": str(
            query
            or ""
        )[:1000],
        "memory_ids": [
            item.get(
                "memory_id"
            )
            for item in memories
        ],
        "fragments": fragments,
        "associations": associations,
        "created_at": time.time(),
        "persisted": False,
        #
        # A thought may contain trusted memories,
        # but the thought itself is an interpretation,
        # therefore it is not evidence.
        #
        "trusted": False,
        "instruction_authority": False,
        "epistemic_status": (
            "temporary_activation"
        ),
    }


def dream_cycle(
    *,
    seed: str = "",
    limit: int = 6,
) -> dict[str, Any]:
    """Recombine sparse memories into one explicitly unverified dream."""

    memories = list(
        _latest_records(
            _memory_journal()
        ).values()
    )

    memories = [
        item
        for item in memories
        if item.get(
            "kind"
        ) == "sparse_memory"
    ]

    if seed.strip():
        seeded = recall_sparse_memories(
            seed,
            limit=limit,
        )

        selected_ids = {
            item.get(
                "memory_id"
            )
            for item in seeded
        }

        rest = [
            item
            for item in memories
            if item.get(
                "memory_id"
            )
            not in selected_ids
        ]

        memories = (
            seeded
            + rest
        )

    memories.sort(
        key=lambda item: (
            float(
                item.get(
                    "strength",
                    0.0,
                )
                or 0.0
            ),
            float(
                item.get(
                    "salience",
                    0.0,
                )
                or 0.0
            ),
        ),
        reverse=True,
    )

    memories = memories[
        :max(
            1,
            min(
                int(
                    limit
                ),
                8,
            ),
        )
    ]

    if not memories:
        return {
            "ok": False,
            "reason": (
                "no sparse memories "
                "available"
            ),
        }

    source_ids = [
        str(
            item.get(
                "memory_id",
                "",
            )
            or ""
        )
        for item in memories
        if str(
            item.get(
                "memory_id",
                "",
            )
            or ""
        )
    ]

    # SOPHYANE_DREAM_SEMANTIC_HYGIENE_RANKING_V2
    #
    # Frequency alone is not enough. When several concepts recur
    # equally often, prioritize terms relevant to the current dream
    # seed and then preserve first semantic occurrence rather than
    # reverse-alphabetical serialization accidents.
    term_frequency: dict[
        str,
        int,
    ] = {}

    first_seen: dict[
        str,
        int,
    ] = {}

    semantic_order = 0

    for memory in memories:
        seen_in_memory: set[str] = set()

        for term in memory.get(
            "entities",
            [],
        ):
            value = _dream_semantic_term(
                term
            )

            if (
                not value
                or value in seen_in_memory
            ):
                continue

            seen_in_memory.add(
                value
            )

            if value not in first_seen:
                first_seen[
                    value
                ] = semantic_order

                semantic_order += 1

            term_frequency[
                value
            ] = (
                term_frequency.get(
                    value,
                    0,
                )
                + 1
            )

    seed_terms = {
        value
        for raw in _terms(
            seed
        )
        if (
            value := _dream_semantic_term(
                raw
            )
        )
    }

    recurring = [
        term
        for term, count
        in sorted(
            term_frequency.items(),
            key=lambda pair: (
                -pair[1],
                -int(
                    pair[0]
                    in seed_terms
                ),
                first_seen.get(
                    pair[0],
                    10**9,
                ),
                pair[0],
            ),
        )
        if count >= 2
    ][:8]

    gists = [
        str(
            item.get(
                "gist",
                "",
            )
            or ""
        )[:240]
        for item in memories[:4]
        if str(
            item.get(
                "gist",
                "",
            )
            or ""
        ).strip()
    ]

    if recurring:
        possible_pattern = (
            "Possible recurring association around: "
            + ", ".join(
                recurring
            )
            + "."
        )

    else:
        possible_pattern = (
            "Possible association between otherwise "
            "separate remembered experiences."
        )

    dream_material = {
        "source_memory_ids": source_ids,
        "recurring_terms": recurring,
        "gists": gists,
        "possible_pattern": possible_pattern,
        "seed": str(
            seed
            or ""
        )[:500],
        "time_ns": time.time_ns(),
    }

    dream_id = (
        "dream:"
        + _digest(
            dream_material
        )[:32]
    )

    dream = {
        "dream_id": dream_id,
        "kind": "dream",
        "source_memory_ids": source_ids,
        "recurring_terms": recurring,
        "remembered_gists": gists,
        "possible_pattern": possible_pattern,
        "created_at": time.time(),
        "verified": False,
        "trusted": False,
        "accepted": False,
        "instruction_authority": False,
        "epistemic_status": (
            "dream_unverified"
        ),
        "requires_external_verification": True,
    }

    with _LOCK:
        _append(
            _dream_journal(),
            dream,
        )

    return {
        "ok": True,
        "dream": dream,
        "path": str(
            _dream_journal()
        ),
    }


def recall_dreams(
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Read dreams separately; dreams never enter trusted recall automatically."""

    path = _dream_journal()

    if not path.exists():
        return []

    result: list[
        dict[str, Any]
    ] = []

    try:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()

    except Exception:
        return []

    for line in reversed(
        lines[-5000:]
    ):
        try:
            item = json.loads(
                line
            )

        except Exception:
            continue

        if not isinstance(
            item,
            dict,
        ):
            continue

        if item.get(
            "kind"
        ) != "dream":
            continue

        #
        # Harden the boundary even if old/corrupt data
        # attempted to claim authority.
        #
        item = {
            **item,
            "verified": False,
            "trusted": False,
            "accepted": False,
            "instruction_authority": False,
            "epistemic_status": (
                "dream_unverified"
            ),
        }

        result.append(
            item
        )

        if len(
            result
        ) >= max(
            1,
            min(
                int(
                    limit
                ),
                32,
            ),
        ):
            break

    return result


def cognitive_status() -> dict[str, Any]:
    memories = _latest_records(
        _memory_journal()
    )

    dreams = recall_dreams(
        limit=32,
    )

    return {
        "memory_backend": (
            "xerus-disk-first"
        ),
        "memory_path": str(
            _memory_journal()
        ),
        "dream_path": str(
            _dream_journal()
        ),
        "sparse_memory_count": len(
            memories
        ),
        "dream_count_recent": len(
            dreams
        ),
        "raw_episode_authority_preserved": True,
        "thoughts_persisted": False,
        "dreams_trusted": False,
        "neuron_write_contract": (
            "not_proven"
        ),
    }


__all__ = [
    "cognitive_status",
    "consolidate_verified_episode",
    "dream_cycle",
    "form_thought",
    "recall_dreams",
    "recall_sparse_memories",
    "sparse_projection",
]
