"""Unified agentic memory for Sophyane Mode-3.

Design
======

Execution state:
    What is true now for the running task.

Short-term memory:
    Episode-scoped useful information.

Long-term memory:
    Cross-session verified reusable knowledge.

Trace/evidence:
    Historical audit truth; never injected wholesale into model context.

The local LLM may PROPOSE memory actions.
Sophyane validates and executes them.

Durable memory requires deterministic evidence. NIFDU recommendations alone
cannot establish truth.

This module intentionally has no:
- subprocess authority;
- shell authority;
- provider/network authority;
- Git promotion authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable


MEMORY_STATE_VERSION = 1

DEFAULT_MEMORY_ROOT = (
    Path.home()
    / ".local"
    / "share"
    / "sophyane"
    / "agentic-memory"
)

DEFAULT_LTM_PATH = (
    DEFAULT_MEMORY_ROOT
    / "long-term.json"
)

DEFAULT_STM_PATH = (
    DEFAULT_MEMORY_ROOT
    / "short-term.json"
)

MAX_LTM_RECORDS = 1000
MAX_STM_RECORDS = 96
MAX_RETRIEVED_MEMORIES = 8
MAX_MEMORY_TEXT_CHARS = 4000

ALLOWED_MEMORY_ACTIONS = {
    "STORE",
    "RETRIEVE",
    "UPDATE",
    "SUMMARIZE",
    "DISCARD",
    "CONSOLIDATE",
    "PROMOTE",
    "DEMOTE",
}


@dataclass(frozen=True)
class MemoryProvenance:
    source: str = ""
    task_family: str = ""
    candidate_identity: str = ""
    verification_ok: bool = False
    held_out_attempted: bool = False
    held_out_not_regressed: bool = True
    environment_state_digest: str = ""
    created_at: int = 0
    last_verified_at: int = 0
    success_count: int = 0
    failure_count: int = 0


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    kind: str
    text: str
    tags: tuple[str, ...] = ()
    confidence: float = 0.5
    salience: float = 0.5
    utility: float = 0.5
    provenance: MemoryProvenance = field(
        default_factory=MemoryProvenance
    )
    supersedes: tuple[str, ...] = ()
    active: bool = True


@dataclass(frozen=True)
class MemoryAction:
    action: str
    text: str = ""
    memory_id: str = ""
    target_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    reason: str = ""
    confidence: float = 0.5


@dataclass(frozen=True)
class RetrievedMemory:
    memory_id: str
    text: str
    score: float
    confidence: float
    utility: float
    tags: tuple[str, ...] = ()


def _bounded_float(
    value: Any,
    low: float,
    high: float,
    default: float,
) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default

    if math.isnan(parsed):
        return default

    return max(
        low,
        min(
            high,
            parsed,
        ),
    )


def _normalize_text(
    value: Any,
    *,
    limit: int = MAX_MEMORY_TEXT_CHARS,
) -> str:
    text = " ".join(
        str(
            value
            or ""
        ).split()
    ).strip()

    return text[:limit]


def _tokens(
    text: str,
) -> set[str]:
    return {
        token
        for token in re.findall(
            r"[a-z0-9_]{2,}",
            str(
                text
                or ""
            ).casefold(),
        )
    }


def _stable_id(
    *,
    kind: str,
    text: str,
    tags: Iterable[str],
) -> str:
    payload = {
        "kind": str(
            kind
            or ""
        ),
        "text": _normalize_text(
            text
        ),
        "tags": sorted(
            {
                str(tag).casefold()
                for tag in tags
                if str(tag).strip()
            }
        ),
    }

    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(
            "utf-8"
        )
    ).hexdigest()[:24]

    return (
        "mem-"
        + digest
    )


def _empty_store() -> dict[str, Any]:
    return {
        "version": MEMORY_STATE_VERSION,
        "records": {},
        "stats": {
            "writes": 0,
            "retrievals": 0,
            "accepted_actions": 0,
            "rejected_actions": 0,
        },
    }


def load_memory_store(
    path: Path | None = None,
) -> dict[str, Any]:
    target = Path(
        path
        or DEFAULT_LTM_PATH
    )

    try:
        raw = json.loads(
            target.read_text(
                encoding="utf-8",
            )
        )
    except Exception:
        return _empty_store()

    if not isinstance(
        raw,
        dict,
    ):
        return _empty_store()

    if int(
        raw.get(
            "version",
            0,
        )
        or 0
    ) != MEMORY_STATE_VERSION:
        return _empty_store()

    raw.setdefault(
        "records",
        {},
    )

    raw.setdefault(
        "stats",
        {},
    )

    for key in (
        "writes",
        "retrievals",
        "accepted_actions",
        "rejected_actions",
    ):
        raw[
            "stats"
        ].setdefault(
            key,
            0,
        )

    return raw


def save_memory_store(
    store: dict[str, Any],
    path: Path | None = None,
) -> Path:
    target = Path(
        path
        or DEFAULT_LTM_PATH
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = target.with_suffix(
        target.suffix
        + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            store,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        target,
    )

    return target


def _record_from_dict(
    memory_id: str,
    raw: dict[str, Any],
) -> MemoryRecord:
    provenance_raw = raw.get(
        "provenance",
        {},
    )

    if not isinstance(
        provenance_raw,
        dict,
    ):
        provenance_raw = {}

    provenance = MemoryProvenance(
        source=str(
            provenance_raw.get(
                "source",
                "",
            )
        ),
        task_family=str(
            provenance_raw.get(
                "task_family",
                "",
            )
        ),
        candidate_identity=str(
            provenance_raw.get(
                "candidate_identity",
                "",
            )
        ),
        verification_ok=bool(
            provenance_raw.get(
                "verification_ok",
                False,
            )
        ),
        held_out_attempted=bool(
            provenance_raw.get(
                "held_out_attempted",
                False,
            )
        ),
        held_out_not_regressed=bool(
            provenance_raw.get(
                "held_out_not_regressed",
                True,
            )
        ),
        environment_state_digest=str(
            provenance_raw.get(
                "environment_state_digest",
                "",
            )
        ),
        created_at=int(
            provenance_raw.get(
                "created_at",
                0,
            )
            or 0
        ),
        last_verified_at=int(
            provenance_raw.get(
                "last_verified_at",
                0,
            )
            or 0
        ),
        success_count=int(
            provenance_raw.get(
                "success_count",
                0,
            )
            or 0
        ),
        failure_count=int(
            provenance_raw.get(
                "failure_count",
                0,
            )
            or 0
        ),
    )

    return MemoryRecord(
        memory_id=memory_id,
        kind=str(
            raw.get(
                "kind",
                "experience",
            )
        ),
        text=_normalize_text(
            raw.get(
                "text",
                "",
            )
        ),
        tags=tuple(
            str(item)
            for item in raw.get(
                "tags",
                [],
            )
            if str(item).strip()
        ),
        confidence=_bounded_float(
            raw.get(
                "confidence",
                0.5,
            ),
            0.0,
            1.0,
            0.5,
        ),
        salience=_bounded_float(
            raw.get(
                "salience",
                0.5,
            ),
            0.0,
            1.0,
            0.5,
        ),
        utility=_bounded_float(
            raw.get(
                "utility",
                0.5,
            ),
            0.0,
            1.0,
            0.5,
        ),
        provenance=provenance,
        supersedes=tuple(
            str(item)
            for item in raw.get(
                "supersedes",
                [],
            )
        ),
        active=bool(
            raw.get(
                "active",
                True,
            )
        ),
    )


def verified_for_long_term(
    provenance: MemoryProvenance,
) -> bool:
    if not provenance.verification_ok:
        return False

    if (
        provenance.held_out_attempted
        and not provenance.held_out_not_regressed
    ):
        return False

    return True


def store_verified_memory(
    *,
    text: str,
    kind: str = "experience",
    tags: tuple[str, ...] = (),
    confidence: float = 0.7,
    salience: float = 0.7,
    utility: float = 0.7,
    provenance: MemoryProvenance,
    supersedes: tuple[str, ...] = (),
    path: Path | None = None,
) -> tuple[
    MemoryRecord | None,
    bool,
]:
    cleaned = _normalize_text(
        text
    )

    if not cleaned:
        return (
            None,
            False,
        )

    if not verified_for_long_term(
        provenance
    ):
        return (
            None,
            False,
        )

    store = load_memory_store(
        path
    )

    memory_id = _stable_id(
        kind=kind,
        text=cleaned,
        tags=tags,
    )

    records = store[
        "records"
    ]

    existing = records.get(
        memory_id
    )

    now = int(
        time.time()
    )

    if isinstance(
        existing,
        dict,
    ):
        record = _record_from_dict(
            memory_id,
            existing,
        )

        success_count = (
            record.provenance.success_count
            + 1
        )

        updated_provenance = (
            asdict(
                record.provenance
            )
        )

        updated_provenance.update(
            {
                "last_verified_at":
                    now,
                "success_count":
                    success_count,
                "verification_ok":
                    True,
                "held_out_attempted":
                    provenance.held_out_attempted,
                "held_out_not_regressed":
                    provenance.held_out_not_regressed,
            }
        )

        existing[
            "confidence"
        ] = min(
            1.0,
            max(
                record.confidence,
                float(
                    confidence
                ),
            )
            + 0.01,
        )

        existing[
            "utility"
        ] = min(
            1.0,
            max(
                record.utility,
                float(
                    utility
                ),
            )
            + 0.01,
        )

        existing[
            "provenance"
        ] = updated_provenance

        save_memory_store(
            store,
            path,
        )

        return (
            _record_from_dict(
                memory_id,
                existing,
            ),
            False,
        )

    record = MemoryRecord(
        memory_id=memory_id,
        kind=str(
            kind
            or "experience"
        ),
        text=cleaned,
        tags=tuple(
            str(tag)
            for tag in tags
            if str(tag).strip()
        ),
        confidence=_bounded_float(
            confidence,
            0.0,
            1.0,
            0.7,
        ),
        salience=_bounded_float(
            salience,
            0.0,
            1.0,
            0.7,
        ),
        utility=_bounded_float(
            utility,
            0.0,
            1.0,
            0.7,
        ),
        provenance=MemoryProvenance(
            **{
                **asdict(
                    provenance
                ),
                "created_at":
                    provenance.created_at
                    or now,
                "last_verified_at":
                    now,
                "success_count":
                    max(
                        1,
                        provenance.success_count,
                    ),
            }
        ),
        supersedes=tuple(
            supersedes
        ),
        active=True,
    )

    records[
        memory_id
    ] = asdict(
        record
    )

    store[
        "stats"
    ][
        "writes"
    ] += 1

    #
    # Hard bound persistent memory size.
    #
    if len(
        records
    ) > MAX_LTM_RECORDS:
        ranked = sorted(
            records.items(),
            key=lambda item: (
                float(
                    item[1].get(
                        "utility",
                        0.0,
                    )
                ),
                float(
                    item[1].get(
                        "confidence",
                        0.0,
                    )
                ),
                int(
                    item[1]
                    .get(
                        "provenance",
                        {},
                    )
                    .get(
                        "last_verified_at",
                        0,
                    )
                    or 0
                ),
            ),
        )

        while len(
            ranked
        ) > MAX_LTM_RECORDS:
            memory_id_to_remove, _ = (
                ranked.pop(
                    0
                )
            )

            records.pop(
                memory_id_to_remove,
                None,
            )

    save_memory_store(
        store,
        path,
    )

    return (
        record,
        True,
    )


def retrieval_score(
    *,
    objective: str,
    record: MemoryRecord,
    difficulty: int = 1,
    quality_target: float = 0.75,
    context_cost: float = 0.0,
    latency_cost: float = 0.0,
    contamination_risk: float = 0.0,
) -> float:
    if not record.active:
        return -1.0

    query_tokens = _tokens(
        objective
    )

    memory_tokens = _tokens(
        record.text
        + " "
        + " ".join(
            record.tags
        )
    )

    if not query_tokens:
        relevance = 0.0

    else:
        relevance = (
            len(
                query_tokens
                & memory_tokens
            )
            / max(
                1,
                len(
                    query_tokens
                )
            )
        )

    difficulty_factor = min(
        1.0,
        max(
            0.2,
            int(
                difficulty
            )
            / 5.0,
        ),
    )

    required_quality = _bounded_float(
        quality_target,
        0.0,
        1.0,
        0.75,
    )

    expected_quality_gain = (
        record.utility
        * (
            0.5
            + (
                0.5
                * difficulty_factor
            )
        )
    )

    confidence = record.confidence

    score = (
        relevance
        * expected_quality_gain
        * confidence
        * (
            0.5
            + (
                0.5
                * required_quality
            )
        )
        - max(
            0.0,
            context_cost,
        )
        - max(
            0.0,
            latency_cost,
        )
        - max(
            0.0,
            contamination_risk,
        )
    )

    return float(
        score
    )


def retrieve_memories(
    *,
    objective: str,
    difficulty: int = 1,
    quality_target: float = 0.75,
    context_budget_chars: int = 6000,
    limit: int = MAX_RETRIEVED_MEMORIES,
    minimum_score: float = 0.01,
    path: Path | None = None,
) -> tuple[
    RetrievedMemory,
    ...
]:
    store = load_memory_store(
        path
    )

    candidates: list[
        tuple[
            float,
            MemoryRecord,
        ]
    ] = []

    for memory_id, raw in (
        store[
            "records"
        ].items()
    ):
        if not isinstance(
            raw,
            dict,
        ):
            continue

        record = _record_from_dict(
            memory_id,
            raw,
        )

        #
        # Stale or repeatedly failing memory carries contamination risk.
        #
        total_outcomes = (
            record.provenance.success_count
            + record.provenance.failure_count
        )

        failure_ratio = (
            record.provenance.failure_count
            / max(
                1,
                total_outcomes,
            )
        )

        score = retrieval_score(
            objective=objective,
            record=record,
            difficulty=difficulty,
            quality_target=quality_target,
            context_cost=min(
                0.20,
                len(
                    record.text
                )
                / max(
                    1,
                    context_budget_chars,
                )
                * 0.12,
            ),
            contamination_risk=(
                failure_ratio
                * 0.25
            ),
        )

        if score < minimum_score:
            continue

        candidates.append(
            (
                score,
                record,
            )
        )

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1].confidence,
            item[1].utility,
        ),
        reverse=True,
    )

    budget = max(
        0,
        int(
            context_budget_chars
        ),
    )

    used = 0

    selected: list[
        RetrievedMemory
    ] = []

    for score, record in (
        candidates[
            : max(
                1,
                min(
                    MAX_RETRIEVED_MEMORIES,
                    int(
                        limit
                    ),
                ),
            )
        ]
    ):
        length = len(
            record.text
        )

        if (
            selected
            and used
            + length
            > budget
        ):
            continue

        if length > budget:
            continue

        used += length

        selected.append(
            RetrievedMemory(
                memory_id=(
                    record.memory_id
                ),
                text=record.text,
                score=round(
                    score,
                    6,
                ),
                confidence=(
                    record.confidence
                ),
                utility=(
                    record.utility
                ),
                tags=(
                    record.tags
                ),
            )
        )

    store[
        "stats"
    ][
        "retrievals"
    ] += 1

    save_memory_store(
        store,
        path,
    )

    return tuple(
        selected
    )


def render_verified_memory_context(
    memories: tuple[
        RetrievedMemory,
        ...
    ],
) -> str:
    if not memories:
        return (
            "VERIFIED_LONG_TERM_MEMORY\n"
            "none\n"
            "END_VERIFIED_LONG_TERM_MEMORY"
        )

    payload = [
        {
            "memory_id":
                item.memory_id,
            "principle":
                item.text,
            "retrieval_score":
                item.score,
            "confidence":
                item.confidence,
            "utility":
                item.utility,
            "tags":
                list(
                    item.tags
                ),
        }
        for item in memories
    ]

    return (
        "VERIFIED_LONG_TERM_MEMORY\n"
        + json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
        "Memory is advisory context. "
        "Current deterministic evidence overrides remembered material.\n"
        "END_VERIFIED_LONG_TERM_MEMORY"
    )


def augment_instruction_with_memory(
    instruction: str,
    *,
    objective: str,
    difficulty: int,
    quality_target: float,
    context_budget_chars: int,
    path: Path | None = None,
) -> tuple[
    str,
    tuple[
        RetrievedMemory,
        ...
    ],
]:
    #
    # Give at most 30% of the TXQ context allowance to historical memory.
    #
    memory_budget = max(
        0,
        min(
            8000,
            int(
                context_budget_chars
                * 0.30
            ),
        ),
    )

    memories = retrieve_memories(
        objective=objective,
        difficulty=difficulty,
        quality_target=quality_target,
        context_budget_chars=(
            memory_budget
        ),
        path=path,
    )

    rendered = (
        str(
            instruction
            or ""
        ).rstrip()
        + "\n\n"
        + render_verified_memory_context(
            memories
        )
    )

    return (
        rendered,
        memories,
    )


_MEMORY_ACTION_PATTERN = re.compile(
    r"MEMORY_ACTION_JSON:\s*(\{.*\})",
    flags=re.DOTALL,
)


def parse_memory_action(
    response: str,
) -> MemoryAction | None:
    match = _MEMORY_ACTION_PATTERN.search(
        str(
            response
            or ""
        )
    )

    if not match:
        return None

    decoder = json.JSONDecoder()

    try:
        raw, _ = decoder.raw_decode(
            match.group(
                1
            ).strip()
        )
    except Exception:
        return None

    if not isinstance(
        raw,
        dict,
    ):
        return None

    action = str(
        raw.get(
            "action",
            "",
        )
    ).strip().upper()

    if action not in (
        ALLOWED_MEMORY_ACTIONS
    ):
        return None

    target_ids = raw.get(
        "target_ids",
        [],
    )

    if not isinstance(
        target_ids,
        list,
    ):
        target_ids = []

    tags = raw.get(
        "tags",
        [],
    )

    if not isinstance(
        tags,
        list,
    ):
        tags = []

    return MemoryAction(
        action=action,
        text=_normalize_text(
            raw.get(
                "text",
                "",
            )
        ),
        memory_id=str(
            raw.get(
                "memory_id",
                "",
            )
        ).strip(),
        target_ids=tuple(
            str(item)
            for item in target_ids
            if str(item).strip()
        ),
        tags=tuple(
            str(item)
            for item in tags
            if str(item).strip()
        ),
        reason=_normalize_text(
            raw.get(
                "reason",
                "",
            ),
            limit=1000,
        ),
        confidence=_bounded_float(
            raw.get(
                "confidence",
                0.5,
            ),
            0.0,
            1.0,
            0.5,
        ),
    )


def apply_verified_memory_action(
    action: MemoryAction,
    *,
    provenance: MemoryProvenance,
    path: Path | None = None,
) -> bool:
    #
    # Any persistent modification requires deterministic truth.
    #
    if not verified_for_long_term(
        provenance
    ):
        return False

    if action.action in {
        "STORE",
        "PROMOTE",
        "SUMMARIZE",
        "CONSOLIDATE",
    }:
        if not action.text:
            return False

        _, created = (
            store_verified_memory(
                text=action.text,
                kind=(
                    "consolidated"
                    if action.action
                    in {
                        "SUMMARIZE",
                        "CONSOLIDATE",
                    }
                    else "experience"
                ),
                tags=action.tags,
                confidence=(
                    action.confidence
                ),
                provenance=(
                    provenance
                ),
                supersedes=(
                    action.target_ids
                ),
                path=path,
            )
        )

        if action.target_ids:
            store = (
                load_memory_store(
                    path
                )
            )

            for memory_id in (
                action.target_ids
            ):
                record = (
                    store[
                        "records"
                    ].get(
                        memory_id
                    )
                )

                if isinstance(
                    record,
                    dict,
                ):
                    record[
                        "active"
                    ] = False

            save_memory_store(
                store,
                path,
            )

        return bool(
            created
            or action.target_ids
        )

    if action.action in {
        "DISCARD",
        "DEMOTE",
    }:
        store = load_memory_store(
            path
        )

        changed = False

        ids = (
            action.target_ids
            or (
                (
                    action.memory_id,
                )
                if action.memory_id
                else ()
            )
        )

        for memory_id in ids:
            raw = store[
                "records"
            ].get(
                memory_id
            )

            if not isinstance(
                raw,
                dict,
            ):
                continue

            raw[
                "active"
            ] = False

            changed = True

        if changed:
            save_memory_store(
                store,
                path,
            )

        return changed

    #
    # RETRIEVE is read-only and is performed through retrieve_memories().
    #
    # UPDATE deliberately requires a future explicit replacement contract
    # rather than mutating facts in place.
    #
    return False


def learn_verified_mode3_experience(
    *,
    objective: str,
    candidate_identity: str,
    candidate_diff: str,
    task_family: str,
    verification_ok: bool,
    held_out_attempted: bool,
    held_out_not_regressed: bool,
    review_status: str,
    environment_state_digest: str = "",
    path: Path | None = None,
) -> tuple[
    MemoryRecord | None,
    bool,
]:
    if not verification_ok:
        return (
            None,
            False,
        )

    if (
        held_out_attempted
        and not held_out_not_regressed
    ):
        return (
            None,
            False,
        )

    if str(
        review_status
        or ""
    ).upper() not in {
        "SUCCESS",
        "CONTINUE",
    }:
        return (
            None,
            False,
        )

    diff = _normalize_text(
        candidate_diff,
        limit=2500,
    )

    if not diff:
        return (
            None,
            False,
        )

    #
    # V1 stores a compact verified experience rather than complete transcript.
    #
    text = (
        "Verified Mode-3 experience for "
        + _normalize_text(
            objective,
            limit=700,
        )
        + ". Candidate change passed deterministic verification"
        + (
            " and held-out non-regression"
            if held_out_attempted
            else ""
        )
        + ". Relevant change summary: "
        + diff
    )

    provenance = MemoryProvenance(
        source="mode3-meta-rsi",
        task_family=str(
            task_family
            or ""
        ),
        candidate_identity=str(
            candidate_identity
            or ""
        ),
        verification_ok=True,
        held_out_attempted=bool(
            held_out_attempted
        ),
        held_out_not_regressed=bool(
            held_out_not_regressed
        ),
        environment_state_digest=str(
            environment_state_digest
            or ""
        ),
    )

    tags = tuple(
        sorted(
            {
                str(
                    task_family
                    or "general"
                ),
                "mode3",
                "verified",
            }
        )
    )

    return store_verified_memory(
        text=text,
        kind="experience",
        tags=tags,
        confidence=0.80,
        salience=0.70,
        utility=0.75,
        provenance=provenance,
        path=path,
    )


def record_memory_failure(
    memory_id: str,
    *,
    path: Path | None = None,
) -> bool:
    store = load_memory_store(
        path
    )

    raw = store[
        "records"
    ].get(
        memory_id
    )

    if not isinstance(
        raw,
        dict,
    ):
        return False

    provenance = raw.setdefault(
        "provenance",
        {},
    )

    provenance[
        "failure_count"
    ] = (
        int(
            provenance.get(
                "failure_count",
                0,
            )
            or 0
        )
        + 1
    )

    successes = int(
        provenance.get(
            "success_count",
            0,
        )
        or 0
    )

    failures = int(
        provenance.get(
            "failure_count",
            0,
        )
        or 0
    )

    #
    # Adaptive forgetting:
    # repeated negative evidence demotes memory automatically.
    #
    if (
        failures >= 3
        and failures
        > successes
    ):
        raw[
            "active"
        ] = False

    raw[
        "utility"
    ] = max(
        0.0,
        float(
            raw.get(
                "utility",
                0.5,
            )
        )
        - 0.08,
    )

    save_memory_store(
        store,
        path,
    )

    return True


def consolidate_memories(
    *,
    memory_ids: tuple[str, ...],
    consolidated_text: str,
    tags: tuple[str, ...],
    provenance: MemoryProvenance,
    path: Path | None = None,
) -> MemoryRecord | None:
    if len(
        memory_ids
    ) < 2:
        return None

    action = MemoryAction(
        action="CONSOLIDATE",
        text=consolidated_text,
        target_ids=memory_ids,
        tags=tags,
        reason=(
            "verified memory consolidation"
        ),
        confidence=0.85,
    )

    if not apply_verified_memory_action(
        action,
        provenance=provenance,
        path=path,
    ):
        return None

    memory_id = _stable_id(
        kind="consolidated",
        text=consolidated_text,
        tags=tags,
    )

    store = load_memory_store(
        path
    )

    raw = store[
        "records"
    ].get(
        memory_id
    )

    if not isinstance(
        raw,
        dict,
    ):
        return None

    return _record_from_dict(
        memory_id,
        raw,
    )


def memory_stats(
    path: Path | None = None,
) -> dict[str, Any]:
    store = load_memory_store(
        path
    )

    records = [
        _record_from_dict(
            memory_id,
            raw,
        )
        for memory_id, raw
        in store[
            "records"
        ].items()
        if isinstance(
            raw,
            dict,
        )
    ]

    active = [
        record
        for record in records
        if record.active
    ]

    return {
        "total":
            len(
                records
            ),
        "active":
            len(
                active
            ),
        "inactive":
            len(
                records
            )
            - len(
                active
            ),
        "mean_confidence":
            (
                sum(
                    item.confidence
                    for item in active
                )
                / max(
                    1,
                    len(
                        active
                    ),
                )
            ),
        "mean_utility":
            (
                sum(
                    item.utility
                    for item in active
                )
                / max(
                    1,
                    len(
                        active
                    ),
                )
            ),
        **store.get(
            "stats",
            {},
        ),
    }


__all__ = [
    "ALLOWED_MEMORY_ACTIONS",
    "DEFAULT_LTM_PATH",
    "DEFAULT_MEMORY_ROOT",
    "DEFAULT_STM_PATH",
    "MAX_LTM_RECORDS",
    "MAX_RETRIEVED_MEMORIES",
    "MemoryAction",
    "MemoryProvenance",
    "MemoryRecord",
    "RetrievedMemory",
    "apply_verified_memory_action",
    "augment_instruction_with_memory",
    "consolidate_memories",
    "learn_verified_mode3_experience",
    "load_memory_store",
    "memory_stats",
    "parse_memory_action",
    "record_memory_failure",
    "render_verified_memory_context",
    "retrieval_score",
    "retrieve_memories",
    "save_memory_store",
    "store_verified_memory",
    "verified_for_long_term",
]
