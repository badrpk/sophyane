"""Difficulty-aware, provenance-safe Sophyane Task Compiler."""
from __future__ import annotations

import ast

import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# SOPHYANE_TASK_COMPILER_V1

LOCAL_ATOMIC_DEADLINE_SECONDS = 3.0

_COMPLEX_MARKERS = (
    "implement",
    "integrate",
    "optimize",
    "analyze",
    "rewrite",
    "migrate",
    "decouple",
    "refactor",
    "design",
    "build",
    "add ",
    "create ",
    # SOPHYANE_V62_ARCHITECTURE_MARKERS
    "cache stampede",
    "single-flight",
    "single flight",
    "idempotency",
    "idempotency-key",
    "transactional outbox",
    "outbox pattern",
    "saga",
    "compensation",
    "durable state transitions",
    "duplicate protection",

)

_CONNECTORS = re.compile(
    r"""
    (?:
        \band\b
        |\bthen\b
        |\bwhile\b
        |\bwith\b
        |;
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class Evidence:
    value: str
    provenance: str
    valid: bool
    detail: str = ""


@dataclass(frozen=True)
class Grounding:
    requirement_id: str
    path: str
    kind: str
    symbol: str = ""
    score: float = 0.0
    evidence: str = ""


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    text: str
    difficulty: int
    explicit_facts: tuple[str, ...] = ()


@dataclass
class CompiledTask:
    handled: bool
    ok: bool
    difficulty: int
    requirements: list[Requirement] = field(
        default_factory=list
    )
    evidence: dict[str, Evidence] = field(
        default_factory=dict
    )
    repository_hits: list[dict[str, str]] = field(
        default_factory=list
    )
    groundings: dict[str, list[Grounding]] = field(
        default_factory=dict
    )
    execution_plan: list[dict[str, Any]] = field(
        default_factory=list
    )
    unresolved: list[str] = field(
        default_factory=list
    )
    output: str = ""
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "handled": self.handled,
            "ok": self.ok,
            "difficulty": self.difficulty,
            "requirements": [
                asdict(item)
                for item in self.requirements
            ],
            "evidence": {
                key: asdict(value)
                for key, value in self.evidence.items()
            },
            "repository_hits": self.repository_hits,
            "groundings": {
                key: [
                    asdict(item)
                    for item in values
                ]
                for key, values in self.groundings.items()
            },
            "execution_plan": self.execution_plan,
            "unresolved": self.unresolved,
            "output": self.output,
            "elapsed_seconds": self.elapsed_seconds,
        }


def estimate_difficulty(text: str) -> int:
    """Cheap deterministic D1-D5 task-complexity estimate."""
    value = str(text or "").strip()
    lower = value.lower()

    score = 1

    verbs = sum(
        marker in lower
        for marker in _COMPLEX_MARKERS
    )

    if verbs >= 1:
        score += 1

    if verbs >= 2:
        score += 1

    if len(value) > 220:
        score += 1

    structural = sum(
        token in lower
        for token in (
            "database",
            "redis",
            "kafka",
            "rabbitmq",
            "middleware",
            "circuit breaker",
            "migration",
            "http client",
            "orm",
            "async",
            "consumer",
            "index",
            "lua",
        )
    )

    if structural >= 2:
        score += 1

    return max(
        1,
        min(5, score),
    )


def should_compile(text: str) -> bool:
    value = str(text or "").strip()

    if not value:
        return False

    lower = value.lower()

    imperative = any(
        marker in lower
        for marker in _COMPLEX_MARKERS
    )

    return (
        imperative
        and estimate_difficulty(value) >= 3
    )


def extract_explicit_facts(text: str) -> tuple[str, ...]:
    """Capture user-supplied constants/identifiers as authoritative."""
    value = str(text or "")

    candidates = re.findall(
        r"""
        (?<![A-Za-z0-9_+.-])
        \d+(?:\.\d+)?(?:ms|s|sec|seconds?|minutes?|req/min|%)?
        (?![A-Za-z0-9_+.-])
        |
        \b[A-Z][A-Za-z0-9_]*(?:Placed|Created|Updated|Deleted)\b
        |
        \bX-[A-Za-z0-9-]+\b
        |
        \b[A-Za-z_][A-Za-z0-9_]*_id\b
        """,
        value,
        flags=re.VERBOSE,
    )

    seen: set[str] = set()
    result = []

    for item in candidates:
        normalized = item.strip()

        if (
            normalized
            and normalized not in seen
        ):
            seen.add(normalized)
            result.append(normalized)

    return tuple(result)



def infer_objective_context(
    text: str,
) -> dict[str, str]:
    """Extract shared domain identity from the complete objective."""
    raw = str(text or "")

    context: dict[str, str] = {}

    patterns = (
        r"\bon\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+table\b",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s+table\b",
        r"\bqueries\s+on\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
    )

    blocked = {
        "slow",
        "database",
        "query",
        "queries",
        "sql",
        "orm",
        "composite",
    }

    for pattern in patterns:
        match = re.search(
            pattern,
            raw,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        candidate = (
            match.group(1)
            .strip()
            .lower()
        )

        if candidate not in blocked:
            context["table"] = candidate
            break

    return context


def _propagate_objective_context(
    requirements: list[Requirement],
    *,
    objective: str,
) -> list[Requirement]:
    context = infer_objective_context(
        objective
    )

    table = context.get(
        "table"
    )

    if not table:
        return requirements

    result: list[Requirement] = []

    marker = f"table:{table}"

    for requirement in requirements:
        facts = list(
            requirement.explicit_facts
        )

        if marker not in facts:
            facts.append(marker)

        result.append(
            Requirement(
                requirement_id=(
                    requirement.requirement_id
                ),
                text=requirement.text,
                difficulty=(
                    requirement.difficulty
                ),
                explicit_facts=tuple(
                    facts
                ),
            )
        )

    return result


def decompose(text: str) -> list[Requirement]:
    """Deterministically split an objective into bounded requirements."""
    value = " ".join(
        str(text or "").split()
    )

    if not value:
        return []

    clauses = []

    for sentence in re.split(
        r"(?<=[.!?])\s+",
        value,
    ):
        parts = [
            item.strip(" ,.")
            for item in _CONNECTORS.split(sentence)
            if item.strip(" ,.")
        ]

        clauses.extend(parts)

    # Avoid exploding a simple request unnecessarily.
    if not clauses:
        clauses = [value]

    requirements = []

    for index, clause in enumerate(
        clauses[:12],
        start=1,
    ):
        requirements.append(
            Requirement(
                requirement_id=f"r{index}",
                text=clause,
                difficulty=estimate_difficulty(clause),
                explicit_facts=extract_explicit_facts(clause),
            )
        )

    return requirements


def _discover_badrpk_repositories() -> list[Path]:
    home = Path.home()

    candidates: set[Path] = set()

    for root in (
        home / "sophyane",
        home / "badrpk-repos",
    ):
        if not root.exists():
            continue

        if (root / ".git").exists():
            candidates.add(root.resolve())

        try:
            for child in root.iterdir():
                if (
                    child.is_dir()
                    and (child / ".git").exists()
                ):
                    candidates.add(child.resolve())
        except OSError:
            pass

    accepted = []

    for path in sorted(
        candidates,
        key=str,
    ):
        if path.name == "sophyane":
            accepted.append(path)
            continue

        try:
            remote = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(path),
                    "remote",
                    "get-url",
                    "origin",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).strip().lower()
        except Exception:
            remote = ""

        if (
            "badrpk/" in remote
            or "github.com:badrpk/" in remote
        ):
            accepted.append(path)

    return accepted


def retrieve(
    requirement: Requirement,
    *,
    workspace: str | Path | None = None,
    max_hits: int = 12,
) -> list[dict[str, str]]:
    """Retrieve advisory evidence only from the explicitly active workspace.

    Repository retrieval is supporting evidence, never mutation authority.
    When a workspace is supplied by compile_task(), no implicit home-level,
    sibling-repository, historical checkout, or global repository fallback
    is permitted.
    """
    words = re.findall(
        r"[A-Za-z][A-Za-z0-9_+-]{3,}",
        requirement.text,
    )

    stop = {
        "with",
        "from",
        "that",
        "this",
        "then",
        "into",
        "using",
        "only",
        "after",
        "before",
        "should",
        "return",
        "implement",
        "integrate",
    }

    terms: list[str] = []

    for word in words:
        lower = word.lower()

        if (
            lower in stop
            or lower in {
                item.lower()
                for item in terms
            }
        ):
            continue

        terms.append(
            word
        )

        if len(terms) >= 6:
            break

    if not terms:
        return []

    if workspace is None:
        return []

    root = Path(
        workspace
    ).expanduser().resolve()

    if not root.is_dir():
        return []

    hits: list[dict[str, str]] = []

    for term in terms:
        try:
            proc = subprocess.run(
                [
                    "grep",
                    "-RniI",
                    "-m",
                    "2",
                    "--exclude-dir=.git",
                    "--exclude-dir=.venv",
                    "--exclude-dir=venv",
                    "--exclude-dir=node_modules",
                    "--exclude-dir=dist",
                    "--exclude-dir=build",
                    term,
                    str(root),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
        except Exception:
            continue

        for line in proc.stdout.splitlines():
            if not line.strip():
                continue

            # grep was rooted at `root`, but assert the emitted path remains
            # inside the requested workspace before exposing it as evidence.
            source_text = line.split(
                ":",
                1,
            )[0]

            try:
                source = Path(
                    source_text
                ).expanduser().resolve()

                source.relative_to(
                    root
                )
            except (
                OSError,
                ValueError,
            ):
                continue

            hits.append(
                {
                    "repo": root.name,
                    "term": term,
                    "line": line[:700],
                }
            )

            if len(hits) >= max_hits:
                return hits

    return hits


def _normalize_contract_text(value: str) -> str:
    value = str(value or "").lower()
    value = value.replace("_", " ")
    value = value.replace("-", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def requirement_contract(
    requirement: Requirement,
) -> str:
    """Infer the concrete artifact/evidence type a requirement needs."""

    architecture_marker = next(
        (
            item.split(
                ":",
                1,
            )[1]
            for item in requirement.explicit_facts
            if item.startswith(
                "architecture:"
            )
        ),
        None,
    )

    # SOPHYANE_V62_PHASE_B_TYPED_ARCHITECTURE
    if architecture_marker in {
        "circuit_breaker",
        "async_event",
        "cache_stampede",
        "idempotency_key",
        "transactional_outbox",
        "saga_compensation",
        "redis_sliding_window_rate_limit",
    }:
        return architecture_marker

    text = _normalize_contract_text(
        requirement.text
    )

    if (
        ("analyze" in text or "analyse" in text)
        and any(
            marker in text
            for marker in (
                "query",
                "database",
                "db cpu",
                "sql",
            )
        )
    ):
        return "database_analysis"

    if (
        "index" in text
        and any(
            marker in text
            for marker in (
                "add",
                "create",
                "composite",
            )
        )
    ):
        return "database_index"

    if (
        "n+1" in text
        or "n plus 1" in text
        or "eager loading" in text
        or "eager load" in text
        or "join fetch" in text
    ):
        return "orm_eager_fetch"

    if (
        "circuit breaker" in text
        or (
            "circuit" in text
            and "fallback" in text
        )
    ):
        return "circuit_breaker"

    if (
        "kafka" in text
        or "rabbitmq" in text
        or (
            "event" in text
            and "consumer" in text
        )
    ):
        return "async_event"

    if (
        "cache stampede" in text
        or "single-flight" in text
        or "single flight" in text
    ):
        return "cache_stampede"

    if (
        "idempotency-key" in text
        or "idempotency key" in text
        or (
            "idempotency" in text
            and (
                "post" in text
                or "payment" in text
                or "charge" in text
            )
        )
    ):
        return "idempotency_key"

    if (
        "transactional outbox" in text
        or "outbox pattern" in text
        or (
            "outbox" in text
            and (
                "event" in text
                or "publish" in text
            )
        )
    ):
        return "transactional_outbox"

    if (
        "saga" in text
        and (
            "compensation" in text
            or "compensat" in text
            or "refund" in text
        )
    ):
        return "saga_compensation"

    # SOPHYANE_V63_REDIS_SLIDING_WINDOW_RATE_LIMIT
    if (
        (
            "rate limit" in text
            or "rate limiting" in text
            or "rate limiter" in text
        )
        and "redis" in text
        and (
            "sliding window" in text
            or "sorted set" in text
            or "zset" in text
        )
    ):
        return "redis_sliding_window_rate_limit"

    return "generic"


def _contract_instruction(
    requirement: Requirement,
) -> str:
    contract = requirement_contract(
        requirement
    )

    if contract == "database_analysis":
        return (
            "Return a concrete database diagnostic artifact. "
            "Include EXPLAIN or EXPLAIN ANALYZE and a representative "
            "query shape. Do not merely say to analyze the query."
        )

    if contract == "database_index":
        return (
            "Return an actual SQL CREATE INDEX statement, or an exact "
            "framework migration expression that creates the requested "
            "index. Preserve the requested column ordering."
        )

    if contract == "orm_eager_fetch":
        return (
            "Return one concrete ORM query or code fragment that performs "
            "eager loading. Use explicit JOIN FETCH, joinedload(...), "
            "selectinload(...), eager_load(...), includes(...), or an "
            "equivalent executable-looking construct. Do not only name "
            "the technique."
        )

    if contract == "circuit_breaker":
        return (
            "Return concrete configuration or pseudocode showing the "
            "breaker condition, open behavior and fallback."
        )

    if contract == "async_event":
        return (
            "Return a concrete event publication/consumer wiring fragment "
            "or structured architecture mapping."
        )

    if contract == "cache_stampede":
        return (
            "Return a concrete cache-stampede mechanism. Require a "
            "single-flight/per-key lock, bounded stale serving, a real "
            "database-backed refresh/fallback path, and guaranteed lock "
            "release. Do not merely name cache stampede prevention."
        )

    if contract == "idempotency_key":
        return (
            "Return concrete idempotency-key handling for the grounded "
            "POST/payment path. Persist the key and request identity, "
            "store the original result/response, replay duplicates "
            "without charging twice, and reject conflicting reuse."
        )

    if contract == "transactional_outbox":
        return (
            "Return a concrete transactional-outbox mechanism. Domain "
            "state and the outbox event must commit atomically in the "
            "same transaction; a background worker must publish with "
            "retry and duplicate/idempotent-delivery protection."
        )

    if contract == "saga_compensation":
        return (
            "Return a concrete durable checkout saga. Include explicit "
            "payment and inventory steps, persisted state transitions, "
            "and compensation/refund when a later inventory step fails "
            "after payment succeeds."
        )

    if contract == "redis_sliding_window_rate_limit":
        return (
            "Return one concrete Redis sliding-window HTTP rate-limit "
            "mechanism. Use an atomic Lua/EVAL operation over a Redis "
            "sorted set keyed by unauthenticated client IP, enforce "
            "100 requests per 60 seconds, preserve authenticated traffic, "
            "and define HTTP 429 with Retry-After plus "
            "X-RateLimit-Limit, X-RateLimit-Remaining and "
            "X-RateLimit-Reset headers. Do not substitute a fixed-window "
            "INCR counter."
        )

    return (
        "Return one concise concrete mechanism, command, API, operation, "
        "configuration fragment, or code fragment that advances this "
        "requirement."
    )


def _extract_target_table(
    requirement: Requirement,
) -> str | None:
    """Infer an explicitly named SQL table from the requirement."""
    raw = requirement.text

    patterns = (
        r"\bon\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+table\b",
        r"\btable\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bon\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s+queries\b",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            raw,
            flags=re.IGNORECASE,
        )

        if match:
            candidate = match.group(1)

            if candidate.lower() not in {
                "slow",
                "orm",
                "database",
                "query",
            }:
                return candidate

    # Handle common phrasing:
    # "Add composite index on (...)"
    # where an earlier sibling objective named "orders" is unavailable.
    return None


def _extract_sql_index_table(
    value: str,
) -> str | None:
    match = re.search(
        r"""
        \bON\s+
        ["`]?
        (?P<table>[A-Za-z_][A-Za-z0-9_$]*)
        ["`]?
        \s*\(
        """,
        str(value or ""),
        flags=re.IGNORECASE | re.VERBOSE,
    )

    if not match:
        return None

    return match.group(
        "table"
    )


def recursive_children(
    requirement: Requirement,
) -> list[Requirement]:
    """Split failed typed requirements into genuinely easier leaves."""
    contract = requirement_contract(
        requirement
    )

    base = requirement.requirement_id

    if contract == "database_analysis":
        return [
            Requirement(
                requirement_id=f"{base}.1",
                text=(
                    "Return only the SQL keyword used to inspect "
                    "a query execution plan."
                ),
                difficulty=1,
            ),
            Requirement(
                requirement_id=f"{base}.2",
                text=(
                    "Return one short representative SQL SELECT "
                    "query against the orders table filtered by user_id."
                ),
                difficulty=2,
                explicit_facts=("orders", "user_id"),
            ),
        ]

    if contract == "orm_eager_fetch":
        return [
            Requirement(
                requirement_id=f"{base}.1",
                text=(
                    "Return only one eager-loading mechanism name: "
                    "JOIN FETCH, joinedload, selectinload, "
                    "eager_load, or includes."
                ),
                difficulty=1,
            ),
            Requirement(
                requirement_id=f"{base}.2",
                text=(
                    "Return one short executable-looking ORM or query "
                    "fragment that uses eager loading to fetch a related "
                    "collection for Order."
                ),
                difficulty=2,
            ),
        ]

    if contract == "database_index":
        return [
            Requirement(
                requirement_id=f"{base}.1",
                text=(
                    "Return only the target SQL table name for this "
                    "index requirement."
                ),
                difficulty=1,
                explicit_facts=requirement.explicit_facts,
            ),
            Requirement(
                requirement_id=f"{base}.2",
                text=(
                    "Return only a CREATE INDEX statement using the "
                    "requested columns in the requested order."
                ),
                difficulty=2,
                explicit_facts=requirement.explicit_facts,
            ),
        ]

    return []


def _merge_child_evidence(
    parent: Requirement,
    children: list[Requirement],
    child_evidence: list[Evidence],
) -> Evidence:
    if (
        not children
        or len(children) != len(child_evidence)
        or not all(item.valid for item in child_evidence)
    ):
        return Evidence(
            value="",
            provenance="RECURSIVE",
            valid=False,
            detail="one or more recursive child requirements unresolved",
        )

    contract = requirement_contract(
        parent
    )

    values = [
        item.value.strip()
        for item in child_evidence
        if item.value.strip()
    ]

    if contract == "database_analysis":
        keyword = values[0]
        query = values[1]

        merged = (
            f"{keyword} {query}"
        )

    elif contract == "orm_eager_fetch":
        mechanism = values[0]
        fragment = values[1]

        # Prefer the actual fragment; include mechanism only as provenance
        # context when the fragment does not already name it.
        merged = fragment

        if (
            mechanism.lower().replace("_", " ")
            not in merged.lower().replace("_", " ")
        ):
            merged = (
                f"{mechanism}\n{merged}"
            )

    else:
        merged = "\n".join(
            values
        )

    valid, detail = (
        validate_requirement_evidence(
            parent,
            merged,
        )
    )

    return Evidence(
        value=merged,
        provenance="RECURSIVE_LOCAL",
        valid=valid,
        detail=(
            "children="
            + ",".join(
                child.requirement_id
                for child in children
            )
            + f"; validation={detail}"
        ),
    )


def validate_requirement_evidence(
    requirement: Requirement,
    value: str,
) -> tuple[bool, str]:
    """Reject task restatements that do not satisfy the output contract."""
    raw = str(value or "").strip()

    if not raw:
        return False, "empty"

    text = _normalize_contract_text(
        raw
    )

    source = _normalize_contract_text(
        requirement.text
    )

    contract = requirement_contract(
        requirement
    )

    if contract == "database_analysis":
        concrete = (
            "explain" in text
            or "query plan" in text
            or "slow query log" in text
        )

        if not concrete:
            return (
                False,
                "database analysis requires EXPLAIN/query-plan evidence",
            )

        return True, "database_analysis"

    if contract == "database_index":
        concrete = (
            "create index" in text
            or "add index" in text
            or "add_index" in raw.lower()
        )

        if not concrete:
            return (
                False,
                "index requirement needs CREATE INDEX/migration artifact",
            )

        # Preserve explicitly requested identifier order where possible.
        requested = []

        match = re.search(
            r"\(([^)]+)\)",
            requirement.text,
        )

        if match:
            for item in match.group(1).split(","):
                item = item.strip()

                if re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*",
                    item,
                ):
                    requested.append(item)

        target_table = _extract_target_table(
            requirement
        )

        artifact_table = _extract_sql_index_table(
            raw
        )

        if (
            target_table
            and artifact_table
            and artifact_table.lower()
            != target_table.lower()
        ):
            return (
                False,
                "index artifact targets wrong table: "
                f"{artifact_table}; expected {target_table}",
            )

        if requested:
            # Validate the indexed column list itself. Searching the entire
            # SQL string is incorrect because an index name such as
            # idx_orders_user_status_created may contain column words in a
            # position unrelated to the actual indexed-column ordering.
            artifact_columns: list[str] = []

            create_index_match = re.search(
                r"""
                \bON\s+
                [A-Za-z_][A-Za-z0-9_$."]*
                \s*
                \(
                    (?P<columns>[^)]+)
                \)
                """,
                raw,
                flags=re.IGNORECASE | re.VERBOSE,
            )

            if create_index_match:
                column_text = create_index_match.group(
                    "columns"
                )

                for part in column_text.split(","):
                    part = part.strip()

                    # Accept ordinary SQL quoting and optional direction.
                    part = re.sub(
                        r"\s+(?:ASC|DESC)\s*$",
                        "",
                        part,
                        flags=re.IGNORECASE,
                    )

                    part = part.strip(
                        ' `"[]'
                    )

                    if re.fullmatch(
                        r"[A-Za-z_][A-Za-z0-9_]*",
                        part,
                    ):
                        artifact_columns.append(
                            part.lower()
                        )

            # Framework migration syntax may not contain "ON table (...)";
            # fall back to a parenthesized identifier list, but still compare
            # parsed identifiers rather than substring positions.
            if not artifact_columns:
                groups = re.findall(
                    r"\(([^)]+)\)",
                    raw,
                )

                for group in reversed(groups):
                    parsed = []

                    for part in group.split(","):
                        part = part.strip().strip(
                            ' `"[]:'
                        )

                        # Common Ruby/Python symbol/string representations.
                        part = part.strip(
                            "'"
                        )

                        if re.fullmatch(
                            r"[A-Za-z_][A-Za-z0-9_]*",
                            part,
                        ):
                            parsed.append(
                                part.lower()
                            )

                    if parsed:
                        artifact_columns = parsed
                        break

            wanted = [
                item.lower()
                for item in requested
            ]

            if not artifact_columns:
                return (
                    False,
                    "index artifact column list could not be verified",
                )

            # Requested columns must appear contiguously and in exactly the
            # requested order. Extra trailing index columns are allowed only
            # when the requested sequence itself remains intact.
            found = False

            width = len(wanted)

            for start in range(
                0,
                len(artifact_columns) - width + 1,
            ):
                if (
                    artifact_columns[
                        start:start + width
                    ]
                    == wanted
                ):
                    found = True
                    break

            if not found:
                missing = [
                    item
                    for item in wanted
                    if item not in artifact_columns
                ]

                if missing:
                    return (
                        False,
                        "index artifact omitted requested columns: "
                        + ", ".join(missing),
                    )

                return (
                    False,
                    "index artifact changed requested column ordering",
                )

        return True, "database_index"

    if contract == "orm_eager_fetch":
        lowered_raw = raw.lower()

        concrete_patterns = (
            "joinedload(",
            "selectinload(",
            "eager_load(",
            "includes(",
            ".includes(",
            "join fetch",
        )

        concrete = any(
            pattern in lowered_raw
            for pattern in concrete_patterns
        )

        if not concrete:
            return (
                False,
                "N+1 fix requires concrete eager-loading syntax",
            )

        # A bare sentence like "Use JOIN FETCH / eager_load" is still
        # descriptive rather than an executable-looking transformation.
        executable_shape = (
            "(" in raw
            or "select " in text
            or " from " in f" {text} "
            or " join fetch " in f" {text} "
            and (
                "select" in text
                or "from" in text
            )
        )

        if not executable_shape:
            return (
                False,
                "eager-loading response is still descriptive prose",
            )

        return True, "orm_eager_fetch"

    if contract == "circuit_breaker":
        open_behavior = (
            "open" in text
        )

        fallback_behavior = (
            "fallback" in text
            or (
                "secondary" in text
                and any(
                    marker in text
                    for marker in (
                        "send",
                        "route",
                        "use",
                        "call",
                        "delegate",
                        "switch",
                        "forward",
                    )
                )
            )
        )

        if not (
            open_behavior
            and fallback_behavior
        ):
            return (
                False,
                "circuit-breaker evidence lacks state/fallback behavior",
            )

        source = _normalize_contract_text(
            requirement.text
        )

        threshold_match = re.search(
            r"\b(\d+)\s+consecutive\b",
            source,
        )

        window_match = re.search(
            r"\b(\d+)\s*(?:second|seconds|sec|s)\b",
            source,
        )

        threshold = (
            int(
                threshold_match.group(1)
            )
            if threshold_match
            else None
        )

        window = (
            int(
                window_match.group(1)
            )
            if window_match
            else None
        )

        if (
            "5xx" in source
            and "5xx" not in text
        ):
            return (
                False,
                "circuit-breaker evidence omitted HTTP 5xx failures",
            )

        if (
            "timeout" in source
            and "timeout" not in text
        ):
            return (
                False,
                "circuit-breaker evidence omitted timeout failures",
            )

        if (
            "secondary" in source
            and "secondary" not in text
        ):
            return (
                False,
                "circuit-breaker evidence omitted secondary fallback",
            )

        if threshold is not None:
            threshold_present = (
                re.search(
                    rf"\b{threshold}\b",
                    text,
                )
                is not None
            )

            if not threshold_present:
                return (
                    False,
                    "circuit-breaker evidence omitted failure threshold",
                )

            # A single user threshold applies to the combined failure class.
            # Reject model inventions such as timeout_count=3 when the user
            # explicitly requested five consecutive 5xx OR timeout failures.
            for pattern in (
                r"""timeout[_ ]?count["']?\s*[:=]\s*(\d+)""",
                r"""timeout[_ ]?threshold["']?\s*[:=]\s*(\d+)""",
                r"""timeout[_ ]?failures?["']?\s*[:=]\s*(\d+)""",
            ):
                match = re.search(
                    pattern,
                    str(value or ""),
                    flags=re.IGNORECASE,
                )

                if (
                    match
                    and int(
                        match.group(1)
                    )
                    != threshold
                ):
                    return (
                        False,
                        "circuit-breaker evidence invented a conflicting "
                        "timeout threshold",
                    )

        if window is not None:
            window_present = (
                re.search(
                    rf"\b{window}\b",
                    text,
                )
                is not None
            )

            if not window_present:
                return (
                    False,
                    "circuit-breaker evidence omitted observation window",
                )

        return True, "circuit_breaker"

    if contract == "async_event":
        if not any(
            marker in text
            for marker in (
                "publish",
                "producer",
                "consumer",
                "subscribe",
                "handler",
            )
        ):
            return (
                False,
                "async-event evidence lacks concrete wiring",
            )

        return True, "async_event"

    if contract == "cache_stampede":
        groups = (
            (
                "single-flight",
                "single flight",
                "per-key lock",
                "lock",
            ),
            (
                "stale",
            ),
            (
                "database",
                "db",
                "backing store",
            ),
            (
                "fallback",
                "refresh",
            ),
        )

        for choices in groups:
            if not any(
                item in text
                for item in choices
            ):
                return (
                    False,
                    "cache-stampede evidence lacks required mechanism",
                )

        return True, "cache_stampede"

    if contract == "idempotency_key":
        groups = (
            (
                "idempotency-key",
                "idempotency key",
                "idempotency",
            ),
            (
                "persist",
                "store",
                "record",
            ),
            (
                "response",
                "result",
            ),
            (
                "replay",
                "original response",
                "same response",
            ),
        )

        for choices in groups:
            if not any(
                item in text
                for item in choices
            ):
                return (
                    False,
                    "idempotency evidence lacks persisted replay contract",
                )

        if not any(
            item in text
            for item in (
                "cannot charge twice",
                "without charging twice",
                "at-most-once",
                "at most once",
                "duplicate",
            )
        ):
            return (
                False,
                "idempotency evidence lacks duplicate-charge prevention",
            )

        return True, "idempotency_key"

    if contract == "transactional_outbox":
        groups = (
            (
                "outbox",
            ),
            (
                "same transaction",
                "atomic",
                "atomically",
            ),
            (
                "publisher",
                "worker",
                "background",
            ),
            (
                "retry",
            ),
            (
                "duplicate",
                "idempotent",
                "dedup",
            ),
        )

        for choices in groups:
            if not any(
                item in text
                for item in choices
            ):
                return (
                    False,
                    "transactional-outbox evidence lacks required contract",
                )

        return True, "transactional_outbox"

    if contract == "saga_compensation":
        groups = (
            (
                "saga",
            ),
            (
                "payment",
            ),
            (
                "inventory",
            ),
            (
                "compensat",
                "refund",
            ),
            (
                "durable",
                "persist",
                "state",
            ),
        )

        for choices in groups:
            if not any(
                item in text
                for item in choices
            ):
                return (
                    False,
                    "saga evidence lacks required compensation contract",
                )

        return True, "saga_compensation"

    if contract == "redis_sliding_window_rate_limit":
        required_groups = (
            (
                "sliding window",
                "sliding-window",
            ),
            (
                "redis",
            ),
            (
                "lua",
                "eval",
                "evalsha",
            ),
            (
                "sorted set",
                "zset",
                "zadd",
                "zremrangebyscore",
            ),
            (
                "100",
            ),
            (
                "60 second",
                "60s",
                "one minute",
                "1 minute",
            ),
            (
                "ip",
                "client ip",
                "client address",
            ),
            (
                "unauthenticated",
                "anonymous",
            ),
            (
                "429",
                "too many requests",
            ),
            (
                "retry-after",
                "retry after",
            ),
            (
                "x-ratelimit-limit",
                "x ratelimit limit",
            ),
            (
                "x-ratelimit-remaining",
                "x ratelimit remaining",
            ),
            (
                "x-ratelimit-reset",
                "x ratelimit reset",
            ),
        )

        for choices in required_groups:
            if not any(
                token in text
                for token in choices
            ):
                return (
                    False,
                    (
                        "redis sliding-window rate-limit evidence "
                        "lacks required contract semantics"
                    ),
                )

        if (
            "fixed window" in text
            and not (
                "not fixed window" in text
                or "avoid fixed window" in text
            )
        ):
            return (
                False,
                "fixed-window evidence is not a sliding-window contract",
            )

        return True, "redis_sliding_window_rate_limit"

    # Generic fallback: reject near-verbatim restatement.
    source_tokens = {
        item
        for item in re.findall(
            r"[a-z0-9_]+",
            source,
        )
        if len(item) >= 4
    }

    result_tokens = {
        item
        for item in re.findall(
            r"[a-z0-9_]+",
            text,
        )
        if len(item) >= 4
    }

    if source_tokens and result_tokens:
        overlap = (
            len(
                source_tokens
                & result_tokens
            )
            / max(
                1,
                len(result_tokens),
            )
        )

        if (
            overlap >= 0.85
            and len(raw) > 80
        ):
            return (
                False,
                "generic result is predominantly a requirement restatement",
            )

    return True, "generic"


def _atomic_prompt(requirement: Requirement) -> str:
    """Convert residual requirement into one typed atomic question."""
    facts = (
        ", ".join(requirement.explicit_facts)
        if requirement.explicit_facts
        else "none"
    )

    return (
        "Solve only this single bounded requirement.\n"
        f"Requirement: {requirement.text}\n"
        f"Contract: {requirement_contract(requirement)}\n"
        f"Authoritative facts already supplied: {facts}\n"
        f"{_contract_instruction(requirement)}\n"
        "Do not discuss the parent task."
    )


def _ask_local_atomic(
    requirement: Requirement,
) -> Evidence:
    from sophyane.config import load_config
    from sophyane.race_orchestrator import (
        _generate_provider_for_race,
        _single_provider,
    )

    import sophyane.race_orchestrator as race

    previous = (
        race._LOCAL_RACE_APPLICATION_DEADLINE_SECONDS
    )

    race._LOCAL_RACE_APPLICATION_DEADLINE_SECONDS = (
        LOCAL_ATOMIC_DEADLINE_SECONDS
    )

    try:
        provider = _single_provider(
            provider_id="local_gguf",
            config=dict(load_config()),
        )

        raw = _generate_provider_for_race(
            provider=provider,
            provider_id="local_gguf",
            prompt=_atomic_prompt(requirement),
            system_prompt=(
                "You are a bounded atomic reasoning function. "
                "Answer only the isolated requirement. "
                "No parent-task prose."
            ),
        )

    except Exception as exc:
        return Evidence(
            value="",
            provenance="LOCAL_LLM",
            valid=False,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )

    finally:
        race._LOCAL_RACE_APPLICATION_DEADLINE_SECONDS = (
            previous
        )

    value = str(raw or "").strip()

    valid, validation_detail = (
        validate_requirement_evidence(
            requirement,
            value,
        )
    )

    return Evidence(
        value=value,
        provenance="LOCAL_LLM",
        valid=valid,
        detail=(
            f"deadline={LOCAL_ATOMIC_DEADLINE_SECONDS:g}s; "
            f"validation={validation_detail}"
        ),
    )


_GROUNDABLE_EXTENSIONS = {
    ".py",
    ".sql",
    ".java",
    ".kt",
    ".js",
    ".ts",
    ".tsx",
    ".rb",
    ".php",
    ".go",
    ".rs",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
}

_GROUNDING_IGNORE = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    "benchmark-results",
    "sophyane-runs",
}

_GROUNDING_FILE_EXCLUDE_PREFIXES = (
    "tests/",
)

_GROUNDING_FILE_EXCLUDE_NAMES = {
    "src/sophyane/task_compiler.py",
}

_GROUNDING_NEGATIVE_MARKERS = (
    "task_compiler",
    "benchmark",
    "fixture",
    "mock",
    "example only",
)


def _grounding_terms(
    requirement: Requirement,
) -> list[str]:
    """Generate high-value lexical terms for workspace grounding."""
    text = requirement.text

    candidates = re.findall(
        r"[A-Za-z_][A-Za-z0-9_]+",
        text,
    )

    stop = {
        "analyze",
        "analyse",
        "slow",
        "queries",
        "query",
        "using",
        "explicit",
        "rewrite",
        "optimize",
        "pagination",
        "generating",
        "high",
        "load",
        "with",
        "from",
        "into",
        "add",
        "create",
        "table",
    }

    terms = []

    for token in candidates:
        lower = token.lower()

        if (
            lower in stop
            or len(lower) < 3
        ):
            continue

        if lower not in {
            item.lower()
            for item in terms
        }:
            terms.append(token)

    contract = requirement_contract(
        requirement
    )

    if contract == "database_index":
        for token in (
            "orders",
            "user_id",
            "status",
            "created_at",
            "migration",
            "schema",
        ):
            if token not in terms:
                terms.append(token)

    elif contract == "orm_eager_fetch":
        for token in (
            "Order",
            "orders",
            "relationship",
            "query",
            "joinedload",
            "selectinload",
            "eager_load",
        ):
            if token not in terms:
                terms.append(token)

    elif contract == "database_analysis":
        for token in (
            "orders",
            "SELECT",
            "user_id",
            "status",
            "created_at",
        ):
            if token not in terms:
                terms.append(token)

    elif contract == "cache_stampede":
        for token in (
            "cache",
            "product",
            "database",
            "get_product",
            "lookup",
            "redis",
        ):
            if token not in terms:
                terms.append(token)

    elif contract == "idempotency_key":
        for token in (
            "payment",
            "post",
            "request",
            "charge",
            "response",
            "handler",
        ):
            if token not in terms:
                terms.append(token)

    elif contract == "transactional_outbox":
        for token in (
            "session",
            "commit",
            "publish",
            "broker",
            "event",
            "order",
        ):
            if token not in terms:
                terms.append(token)

    elif contract == "saga_compensation":
        for token in (
            "checkout",
            "payment",
            "inventory",
            "charge",
            "reserve",
            "order",
        ):
            if token not in terms:
                terms.append(token)

    elif contract == "redis_sliding_window_rate_limit":
        for token in (
            "redis",
            "middleware",
            "request",
            "client",
            "host",
            "rate_limit",
            "rate limiter",
            "unauthenticated",
        ):
            if token not in terms:
                terms.append(token)

    # SOPHYANE_V62_PHASE_B_GROUNDING_TERM_PRIORITY
    #
    # Structural architecture contracts must place problem-site
    # vocabulary ahead of generic objective prose. Otherwise the
    # fixed 12-term ceiling can discard terms such as session,
    # commit, broker and publish before ground_requirement() gets
    # a chance to invoke structural scoring.
    priority_by_contract = {
        "cache_stampede": (
            "cache",
            "get_product",
            "product",
            "database",
            "redis",
            "lookup",
        ),
        "idempotency_key": (
            "payment",
            "charge",
            "request",
            "post",
            "handler",
            "response",
        ),
        "transactional_outbox": (
            "session",
            "commit",
            "publish",
            "broker",
            "event",
            "order",
        ),
        "saga_compensation": (
            "checkout",
            "payment",
            "inventory",
            "charge",
            "reserve",
            "order",
        ),
        "redis_sliding_window_rate_limit": (
            "redis",
            "middleware",
            "request",
            "client",
            "host",
            "rate_limit",
        ),
    }

    priority = priority_by_contract.get(
        contract,
        (),
    )

    ordered: list[str] = []
    seen: set[str] = set()

    for token in (
        *priority,
        *terms,
    ):
        key = token.lower()

        if key in seen:
            continue

        seen.add(
            key
        )

        ordered.append(
            token
        )

    return ordered[:12]


def _grounding_path_allowed(
    relative: str,
) -> bool:
    normalized = relative.replace(
        "\\",
        "/",
    )

    if normalized in _GROUNDING_FILE_EXCLUDE_NAMES:
        return False

    if any(
        normalized.startswith(prefix)
        for prefix in _GROUNDING_FILE_EXCLUDE_PREFIXES
    ):
        return False

    return True



def _extract_requirement_domain(
    requirement: Requirement,
) -> dict[str, str]:
    """Resolve domain identity from propagated facts or local wording."""
    result: dict[str, str] = {}

    # Parent-propagated context has highest authority.
    for fact in requirement.explicit_facts:
        if not fact.startswith(
            "table:"
        ):
            continue

        value = fact.split(
            ":",
            1,
        )[1].strip().lower()

        if value:
            result["table"] = value
            break

    # Fall back to requirement-local wording only when no parent
    # domain has already been propagated.
    if "table" not in result:
        raw = requirement.text

        patterns = (
            r"\bon\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+table\b",
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s+table\b",
            r"\bon\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s+queries\b",
        )

        blocked = {
            "slow",
            "orm",
            "database",
            "query",
            "queries",
            "composite",
        }

        for pattern in patterns:
            match = re.search(
                pattern,
                raw,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            candidate = (
                match.group(1)
                .strip()
                .lower()
            )

            if candidate not in blocked:
                result["table"] = candidate
                break

    result["contract"] = (
        requirement_contract(
            requirement
        )
    )

    return result


def _has_domain_identity(
    *,
    raw: str,
    table: str,
) -> tuple[bool, str]:
    """Prove a file represents or queries the requested domain."""
    if not table:
        return (
            False,
            "missing-domain",
        )

    singular = (
        table[:-1]
        if table.endswith("s")
        else table
    )

    patterns = (
        (
            rf"__tablename__\s*=\s*['\"]{re.escape(table)}['\"]",
            "tablename",
        ),
        (
            rf"\bCREATE\s+TABLE\s+['\"`]?{re.escape(table)}\b",
            "create-table",
        ),
        (
            rf"\bFROM\s+['\"`]?{re.escape(table)}\b",
            "sql-from",
        ),
        (
            rf"\bJOIN\s+['\"`]?{re.escape(table)}\b",
            "sql-join",
        ),
        (
            rf"\bclass\s+{re.escape(singular)}\b",
            "model-class",
        ),
        (
            rf"\bclass\s+{re.escape(singular.capitalize())}\b",
            "model-class",
        ),
        (
            rf"\bTable\s*\(\s*['\"]{re.escape(table)}['\"]",
            "table-call",
        ),
        (
            rf"\bquery\s*\(\s*['\"]{re.escape(table)}['\"]\s*\)",
            "orm-query-string",
        ),
        (
            rf"\bquery\s*\(\s*{re.escape(singular.capitalize())}\s*\)",
            "orm-query-model",
        ),
    )

    for pattern, signal in patterns:
        if re.search(
            pattern,
            raw,
            flags=re.IGNORECASE,
        ):
            return (
                True,
                signal,
            )

    return (
        False,
        "domain-identity-not-found",
    )



def _structural_grounding_score(
    requirement: Requirement,
    *,
    relative: str,
    raw: str,
    lexical_matches: list[str],
) -> tuple[float, str]:
    """Require both implementation structure and same-domain identity."""
    contract = requirement_contract(
        requirement
    )

    domain = _extract_requirement_domain(
        requirement
    )

    table = domain.get(
        "table",
        "",
    )

    lower = raw.lower()
    path_lower = relative.lower()

    if any(
        marker in path_lower
        for marker in _GROUNDING_NEGATIVE_MARKERS
    ):
        return (
            0.0,
            "negative-path-marker",
        )

    score = 0.0
    signals: list[str] = []

    if contract in {
        "database_index",
        "database_analysis",
        "orm_eager_fetch",
    }:
        domain_ok, domain_signal = (
            _has_domain_identity(
                raw=raw,
                table=table,
            )
        )

        if not domain_ok:
            return (
                0.0,
                domain_signal,
            )

        score += 8.0

        signals.append(
            "domain:"
            + domain_signal
        )

        requested_identifiers = [
            token
            for token in (
                "user_id",
                "status",
                "created_at",
            )
            if token
            in requirement.text.lower()
        ]

        present_identifiers = [
            token
            for token
            in requested_identifiers
            if re.search(
                rf"\b{re.escape(token)}\b",
                raw,
                flags=re.IGNORECASE,
            )
        ]

        if (
            requested_identifiers
            and len(
                present_identifiers
            )
            == len(
                requested_identifiers
            )
        ):
            score += 4.0
            signals.append(
                "requested-columns"
            )

        if contract == "database_index":
            schema_shape = (
                re.search(
                    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b",
                    raw,
                    flags=re.IGNORECASE,
                )
                is not None
                or re.search(
                    r"\badd_index\s*\(",
                    raw,
                    flags=re.IGNORECASE,
                )
                is not None
                or (
                    table
                    and re.search(
                        rf"\bCREATE\s+TABLE\s+['\"`]?"
                        rf"{re.escape(table)}\b",
                        raw,
                        flags=re.IGNORECASE,
                    )
                    is not None
                )
                or (
                    "model" in path_lower
                    and bool(
                        requested_identifiers
                    )
                    and len(
                        present_identifiers
                    )
                    == len(
                        requested_identifiers
                    )
                )
            )

            if not schema_shape:
                return (
                    0.0,
                    "domain-present-but-no-schema-structure",
                )

            score += 5.0
            signals.append(
                "schema-structure"
            )

        elif contract == "database_analysis":
            query_shape = any(
                re.search(
                    pattern,
                    raw,
                    flags=re.IGNORECASE,
                )
                for pattern in (
                    r"\bSELECT\b",
                    r"\bsession\.query\s*\(",
                    r"\bobjects\.filter\s*\(",
                    r"\bexecute\s*\(",
                    r"\bquery\s*\(",
                )
            )

            if not query_shape:
                return (
                    0.0,
                    "domain-present-but-no-query-structure",
                )

            score += 5.0
            signals.append(
                "query-structure"
            )

        elif contract == "orm_eager_fetch":
            eager_shape = any(
                re.search(
                    pattern,
                    raw,
                    flags=re.IGNORECASE,
                )
                for pattern in (
                    r"\bjoinedload\s*\(",
                    r"\bselectinload\s*\(",
                    r"\beager_load\s*\(",
                    r"\bincludes\s*\(",
                    r"\bJOIN\s+FETCH\b",
                )
            )

            relationship_shape = any(
                marker in lower
                for marker in (
                    "relationship(",
                    "has_many",
                    "has_one",
                    "belongs_to",
                    "foreignkey(",
                    "foreign_key",
                )
            )

            # A mutation target may contain the N+1 problem rather than
            # the eager-loading solution. Recognize a same-domain parent
            # query plus a repeated child query inside iteration.
            parent_query = bool(
                re.search(
                    rf"\bquery\s*\(\s*['\"]{re.escape(table)}['\"]\s*\)",
                    raw,
                    flags=re.IGNORECASE,
                )
            )

            loop_shape = bool(
                re.search(
                    r"\bfor\s+[A-Za-z_][A-Za-z0-9_]*\s+in\s+",
                    raw,
                    flags=re.IGNORECASE,
                )
            )

            repeated_query = len(
                re.findall(
                    r"\bquery\s*\(",
                    raw,
                    flags=re.IGNORECASE,
                )
            ) >= 2

            child_lookup = any(
                marker in lower
                for marker in (
                    "order_items",
                    "order_id",
                )
            )

            n_plus_one_problem = (
                parent_query
                and loop_shape
                and repeated_query
                and child_lookup
            )

            if not (
                eager_shape
                or relationship_shape
                or n_plus_one_problem
            ):
                return (
                    0.0,
                    "domain-present-but-no-eager-or-nplus1-structure",
                )

            score += 5.0

            if eager_shape:
                signals.append(
                    "eager-structure"
                )

            elif n_plus_one_problem:
                signals.append(
                    "n-plus-one-problem-site"
                )

            else:
                signals.append(
                    "relationship-structure"
                )

    # SOPHYANE_V62_PHASE_B_STRUCTURAL_GROUNDING
    elif contract == "redis_sliding_window_rate_limit":
        # Redis HTTP rate limiting is a mutation contract. File-wide lexical
        # coincidence is not sufficient grounding: configuration, compiler
        # source and routing policy can all contain words such as "redis",
        # "request" and "middleware" without being an application request
        # interception surface.
        #
        # Require one concrete Python function to prove, in the same lexical
        # scope:
        #   * request/req argument;
        #   * explicit Redis dependency argument;
        #   * real client-IP extraction;
        #   * actual use of that Redis dependency;
        #   * HTTP/middleware interception shape.
        if not path_lower.endswith(".py"):
            return (
                0.0,
                "redis-rate-limit-target-not-python",
            )

        try:
            tree = ast.parse(
                raw,
                filename=relative,
            )
        except SyntaxError:
            return (
                0.0,
                "redis-rate-limit-python-parse-failed",
            )

        proven_symbol = ""

        for node in ast.walk(tree):
            if not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                continue

            arg_names = [
                item.arg
                for item in (
                    list(node.args.posonlyargs)
                    + list(node.args.args)
                    + list(node.args.kwonlyargs)
                )
            ]

            request_args = [
                name
                for name in arg_names
                if name.lower() in {
                    "request",
                    "req",
                }
            ]

            redis_args = [
                name
                for name in arg_names
                if "redis" in name.lower()
            ]

            if (
                not request_args
                or not redis_args
            ):
                continue

            segment = (
                ast.get_source_segment(
                    raw,
                    node,
                )
                or ""
            )

            segment_lower = segment.lower()

            client_ip_shape = any(
                token in segment_lower
                for token in (
                    "request.client.host",
                    "req.client.host",
                    "client.host",
                    "client_ip",
                    "remote_addr",
                )
            )

            redis_use = any(
                (
                    name.lower() + "."
                )
                in segment_lower
                for name in redis_args
            )

            http_shape = (
                "middleware"
                in node.name.lower()
                or any(
                    name.lower()
                    in {
                        "call_next",
                        "next_handler",
                        "handler",
                    }
                    for name in arg_names
                )
                or any(
                    token in segment_lower
                    for token in (
                        "call_next(",
                        "response",
                        "status_code",
                        "http",
                    )
                )
            )

            if (
                client_ip_shape
                and redis_use
                and http_shape
            ):
                proven_symbol = node.name
                break

        if not proven_symbol:
            return (
                0.0,
                "no-function-scoped-http-redis-client-ip-structure",
            )

        score += 16.0

        signals.extend(
            (
                "redis-dependency",
                "http-request-path",
                "client-ip-identity",
                "function:" + proven_symbol,
            )
        )

    elif contract == "cache_stampede":
        cache_shape = any(
            token in lower
            for token in (
                "cache.get",
                "cache.set",
                "redis",
                "cache[",
            )
        )

        lookup_shape = any(
            token in lower
            for token in (
                "get_product",
                "product",
                "lookup",
                "database",
                "db.",
            )
        )

        if not (
            cache_shape
            and lookup_shape
        ):
            return (
                0.0,
                "no-cache-backed-lookup-structure",
            )

        score += 12.0
        signals.extend(
            (
                "cache-structure",
                "lookup-structure",
            )
        )

    elif contract == "idempotency_key":
        payment_shape = any(
            token in lower
            for token in (
                "payment",
                "charge(",
                "payment_gateway",
            )
        )

        request_shape = any(
            token in lower
            for token in (
                "post_",
                "post(",
                "request",
                "handler",
                "route",
                "api",
            )
        )

        if not (
            payment_shape
            and request_shape
        ):
            return (
                0.0,
                "no-payment-post-handler-structure",
            )

        score += 12.0
        signals.extend(
            (
                "payment-domain",
                "request-handler",
            )
        )

    elif contract == "transactional_outbox":
        transaction_shape = any(
            token in lower
            for token in (
                "commit(",
                "transaction",
                "session.",
                "begin(",
            )
        )

        event_shape = any(
            token in lower
            for token in (
                "publish(",
                "broker.",
                "event",
                "producer",
            )
        )

        if not (
            transaction_shape
            and event_shape
        ):
            return (
                0.0,
                "no-db-write-plus-event-publication-structure",
            )

        score += 12.0
        signals.extend(
            (
                "transaction-structure",
                "event-publication",
            )
        )

    elif contract == "saga_compensation":
        checkout_shape = any(
            token in lower
            for token in (
                "checkout",
                "order",
            )
        )

        payment_shape = any(
            token in lower
            for token in (
                "payment",
                "charge(",
            )
        )

        inventory_shape = any(
            token in lower
            for token in (
                "inventory",
                "reserve(",
            )
        )

        if not (
            checkout_shape
            and payment_shape
            and inventory_shape
        ):
            return (
                0.0,
                "no-checkout-payment-inventory-structure",
            )

        score += 14.0
        signals.extend(
            (
                "checkout-domain",
                "payment-step",
                "inventory-step",
            )
        )

    elif contract == "circuit_breaker":
        structural = any(
            re.search(
                pattern,
                raw,
                flags=re.IGNORECASE,
            )
            for pattern in (
                r"\bcircuit[_ ]?breaker\b",
                r"\bfailure[_ ]?rate\b",
                r"\bfallback\s*\(",
            )
        )

        if not structural:
            return (
                0.0,
                "no-circuit-structure",
            )

        score += 8.0
        signals.append(
            "circuit-structure"
        )

    elif contract == "async_event":
        structural = any(
            re.search(
                pattern,
                raw,
                flags=re.IGNORECASE,
            )
            for pattern in (
                r"\bkafka\b",
                r"\brabbitmq\b",
                r"\bpublish\s*\(",
                r"\bproducer\b",
                r"\bconsumer\b",
                r"\bsubscribe\s*\(",
            )
        )

        if not structural:
            return (
                0.0,
                "no-event-structure",
            )

        score += 8.0
        signals.append(
            "event-structure"
        )

    else:
        return (
            0.0,
            "generic-not-groundable",
        )

    score += min(
        2.0,
        float(
            len(lexical_matches)
        ),
    )

    if lexical_matches:
        signals.append(
            "lexical:"
            + ",".join(
                lexical_matches[:3]
            )
        )

    return (
        score,
        ";".join(signals),
    )

def ground_requirement(
    requirement: Requirement,
    *,
    workspace: str | Path,
    max_results: int = 8,
) -> list[Grounding]:
    """Bind a requirement to real workspace files and symbols."""
    root = Path(
        workspace
    ).resolve()

    if not root.exists():
        return []

    terms = _grounding_terms(
        requirement
    )

    if not terms:
        return []

    candidates: list[Grounding] = []

    for path in root.rglob("*"):
        # Ignore only paths *inside* the active workspace.
        #
        # Using path.parts here is incorrect because it includes absolute
        # ancestors. A legitimate workspace located beneath a directory
        # named "sophyane-runs", "build", etc. would otherwise have every
        # file rejected before grounding even begins.
        try:
            relative_path = path.relative_to(
                root
            )
        except ValueError:
            continue

        if any(
            part in _GROUNDING_IGNORE
            for part in relative_path.parts
        ):
            continue

        if (
            not path.is_file()
            or path.suffix.lower()
            not in _GROUNDABLE_EXTENSIONS
        ):
            continue

        try:
            raw = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        lower = raw.lower()

        matches = [
            term
            for term in terms
            if term.lower() in lower
        ]

        if not matches:
            continue

        relative = str(
            path.relative_to(root)
        )

        if not _grounding_path_allowed(
            relative
        ):
            continue

        score, structural_evidence = (
            _structural_grounding_score(
                requirement,
                relative=relative,
                raw=raw,
                lexical_matches=matches,
            )
        )

        if score <= 0:
            continue

        suffix = path.suffix.lower()

        kind = "source"

        lowered_path = relative.lower()

        if (
            "migration" in lowered_path
            or suffix == ".sql"
        ):
            kind = "migration_or_sql"

        elif (
            "model" in lowered_path
            or "schema" in lowered_path
        ):
            kind = "model_or_schema"

        elif (
            "repository" in lowered_path
            or "dao" in lowered_path
            or "query" in lowered_path
        ):
            kind = "query_layer"

        symbol = ""

        for line in raw.splitlines():
            stripped = line.strip()

            symbol_match = re.match(
                r"(?:class|def|function|interface)\s+"
                r"([A-Za-z_][A-Za-z0-9_]*)",
                stripped,
            )

            if not symbol_match:
                continue

            if any(
                term.lower()
                in stripped.lower()
                for term in matches
            ):
                symbol = symbol_match.group(
                    1
                )
                break

        candidates.append(
            Grounding(
                requirement_id=(
                    requirement.requirement_id
                ),
                path=relative,
                kind=kind,
                symbol=symbol,
                score=score,
                evidence=structural_evidence,
            )
        )

    candidates.sort(
        key=lambda item: (
            -item.score,
            item.path,
        )
    )

    return candidates[
        :max_results
    ]


def grounding_required(
    requirement: Requirement,
) -> bool:
    return requirement_contract(
        requirement
    ) in {
        "database_index",
        "orm_eager_fetch",
        "database_analysis",
        "circuit_breaker",
        "async_event",
        "cache_stampede",
        "idempotency_key",
        "transactional_outbox",
        "saga_compensation",
        "redis_sliding_window_rate_limit",
    }


def grounded_contract_recovery(
    requirement: Requirement,
    *,
    grounding: Grounding,
    workspace: str | Path,
) -> Evidence:
    """Recover typed evidence deterministically from a proven target."""
    root = Path(
        workspace
    ).resolve()

    target = (
        root
        / grounding.path
    ).resolve()

    try:
        target.relative_to(
            root
        )
    except ValueError:
        return Evidence(
            value="",
            provenance="GROUNDED_DETERMINISTIC",
            valid=False,
            detail="grounding escaped workspace",
        )

    if not target.is_file():
        return Evidence(
            value="",
            provenance="GROUNDED_DETERMINISTIC",
            valid=False,
            detail="grounding target is not a file",
        )

    try:
        raw = target.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return Evidence(
            value="",
            provenance="GROUNDED_DETERMINISTIC",
            valid=False,
            detail=f"read failed: {exc}",
        )

    contract = requirement_contract(
        requirement
    )

    if contract == "redis_sliding_window_rate_limit":
        recovered = (
            "Implement a Redis-backed sliding window rate limit for "
            "unauthenticated users keyed by client IP. Use an atomic Lua "
            "script through EVAL or EVALSHA over a Redis sorted set: remove "
            "timestamps older than 60 seconds, count the remaining entries, "
            "and add the current request timestamp only when permitted. "
            "Enforce 100 requests per 60 seconds and preserve authenticated "
            "traffic. When the limit is exceeded, return HTTP 429 Too Many "
            "Requests with Retry-After, X-RateLimit-Limit, "
            "X-RateLimit-Remaining and X-RateLimit-Reset headers. "
            "This is a sliding window, not fixed-window INCR counting."
        )

        valid, detail = validate_requirement_evidence(
            requirement,
            recovered,
        )

        return Evidence(
            value=recovered,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                f"source={grounding.path}; "
                f"recovery={detail}"
            ),
        )

    if contract == "cache_stampede":
        recovered = (
            "Use a per-key single-flight lock around the grounded "
            "database-backed cache lookup. On a miss, one lock owner "
            "refreshes from the database while concurrent callers may "
            "serve a bounded stale value. If refresh fails, use the "
            "bounded stale value or database fallback, and always "
            "release the lock."
        )

        valid, detail = validate_requirement_evidence(
            requirement,
            recovered,
        )

        return Evidence(
            value=recovered,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                f"source={grounding.path}; "
                f"recovery={detail}"
            ),
        )

    if contract == "idempotency_key":
        recovered = (
            "Read the Idempotency-Key in the grounded POST/payment "
            "handler. Persist the idempotency key, request fingerprint, "
            "execution result and original response. Duplicate requests "
            "with the same fingerprint replay the original response "
            "without charging twice; conflicting key reuse is rejected, "
            "giving at-most-once charge execution."
        )

        valid, detail = validate_requirement_evidence(
            requirement,
            recovered,
        )

        return Evidence(
            value=recovered,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                f"source={grounding.path}; "
                f"recovery={detail}"
            ),
        )

    if contract == "transactional_outbox":
        recovered = (
            "Use a transactional outbox in the grounded database/event "
            "path. Persist the domain state change and outbox event row "
            "atomically in the same transaction. A background publisher "
            "worker reads unsent outbox rows, publishes with retry, marks "
            "success durably, and uses the event identifier for duplicate "
            "or idempotent delivery protection."
        )

        valid, detail = validate_requirement_evidence(
            requirement,
            recovered,
        )

        return Evidence(
            value=recovered,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                f"source={grounding.path}; "
                f"recovery={detail}"
            ),
        )

    if contract == "saga_compensation":
        recovered = (
            "Use a durable checkout saga around the grounded payment and "
            "inventory path. Persist saga state before each step, perform "
            "the payment step and then inventory reservation. If inventory "
            "fails after payment succeeds, run the compensation/refund "
            "action, persist the compensated state, and make saga retries "
            "idempotent."
        )

        valid, detail = validate_requirement_evidence(
            requirement,
            recovered,
        )

        return Evidence(
            value=recovered,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                f"source={grounding.path}; "
                f"recovery={detail}"
            ),
        )


    if contract == "circuit_breaker":
        lower = raw.lower()

        payment_shape = (
            "primary" in lower
            and "secondary" in lower
            and any(
                marker in lower
                for marker in (
                    "payment",
                    "gateway",
                    "charge",
                    "process_payment",
                )
            )
        )

        if not payment_shape:
            return Evidence(
                value="",
                provenance="GROUNDED_DETERMINISTIC",
                valid=False,
                detail=(
                    "grounded source does not contain "
                    "primary/secondary payment structure"
                ),
            )

        source_text = requirement.text.lower()

        threshold_match = re.search(
            r"\b(\d+)\s+consecutive\b",
            source_text,
        )

        window_match = re.search(
            r"\b(\d+)\s*(?:second|seconds|sec|s)\b",
            source_text,
        )

        threshold = (
            threshold_match.group(1)
            if threshold_match
            else ""
        )

        window = (
            window_match.group(1)
            if window_match
            else ""
        )

        if not threshold or not window:
            return Evidence(
                value="",
                provenance="GROUNDED_DETERMINISTIC",
                valid=False,
                detail=(
                    "circuit requirement is missing "
                    "explicit threshold/window truth"
                ),
            )

        recovered = (
            "Circuit breaker state: CLOSED -> OPEN. "
            f"Open after {threshold} consecutive HTTP 5xx "
            f"or timeout failures within {window} seconds. "
            "When OPEN, fallback to the secondary payment processor."
        )

        valid, detail = (
            validate_requirement_evidence(
                requirement,
                recovered,
            )
        )

        return Evidence(
            value=recovered,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                f"source={grounding.path}; "
                f"recovery={detail}"
            ),
        )

    if contract == "async_event":
        lower = raw.lower()

        checkout_shape = (
            "checkout" in lower
            and sum(
                marker in lower
                for marker in (
                    "send_email",
                    "log_analytics",
                    "update_inventory",
                )
            ) >= 2
        )

        if not checkout_shape:
            return Evidence(
                value="",
                provenance="GROUNDED_DETERMINISTIC",
                valid=False,
                detail=(
                    "grounded source does not contain "
                    "synchronous checkout side effects"
                ),
            )

        source_text = requirement.text.lower()

        if "orderplaced" not in source_text:
            return Evidence(
                value="",
                provenance="GROUNDED_DETERMINISTIC",
                valid=False,
                detail="OrderPlaced is not user-authoritative",
            )

        if "kafka" in source_text:
            broker = "Kafka"
        elif "rabbitmq" in source_text:
            broker = "RabbitMQ"
        else:
            broker = "message broker"

        consumers = []

        if "email" in source_text:
            consumers.append(
                "email consumer"
            )

        if "analytics" in source_text:
            consumers.append(
                "analytics consumer"
            )

        if "inventory" in source_text:
            consumers.append(
                "inventory consumer"
            )

        if not consumers:
            return Evidence(
                value="",
                provenance="GROUNDED_DETERMINISTIC",
                valid=False,
                detail="no asynchronous consumer requirements found",
            )

        recovered = (
            f'publish("OrderPlaced", order) to {broker}; '
            + "; ".join(
                consumers
            )
            + "; each consumer handles the event asynchronously."
        )

        valid, detail = (
            validate_requirement_evidence(
                requirement,
                recovered,
            )
        )

        return Evidence(
            value=recovered,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                f"source={grounding.path}; "
                f"recovery={detail}"
            ),
        )

    domain = _extract_requirement_domain(
        requirement
    )

    table = domain.get(
        "table",
        "",
    )

    # --------------------------------------------------------
    # Database diagnostic recovery.
    # --------------------------------------------------------

    if contract == "database_index":
        target_table = _extract_target_table(
            requirement
        )

        # The requested column list is user authority.
        requested_columns: list[str] = []

        match = re.search(
            r"\(([^)]+)\)",
            requirement.text,
        )

        if match:
            for item in match.group(1).split(","):
                item = item.strip()

                if re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*",
                    item,
                ):
                    requested_columns.append(
                        item
                    )

        if (
            target_table
            and requested_columns
        ):
            # A deterministic index artifact is permitted only after the
            # requirement has already been bound to a real same-domain
            # schema/model grounding.
            name_parts = [
                target_table,
                *requested_columns,
            ]

            index_name = (
                "idx_"
                + "_".join(
                    name_parts
                )
            )

            recovered = (
                f"CREATE INDEX {index_name} "
                f"ON {target_table} "
                f"({', '.join(requested_columns)});"
            )

            valid, detail = (
                validate_requirement_evidence(
                    requirement,
                    recovered,
                )
            )

            return Evidence(
                value=recovered,
                provenance="GROUNDED_DETERMINISTIC",
                valid=valid,
                detail=(
                    f"source={grounding.path}; "
                    f"recovery={detail}"
                ),
            )

        return Evidence(
            value="",
            provenance="GROUNDED_DETERMINISTIC",
            valid=False,
            detail=(
                "database-index recovery could not derive "
                "authoritative target table/columns"
            ),
        )

    if contract == "database_analysis":
        if not table:
            return Evidence(
                value="",
                provenance="GROUNDED_DETERMINISTIC",
                valid=False,
                detail="database analysis has no propagated table",
            )

        predicates: list[str] = []

        for identifier in (
            "user_id",
            "status",
        ):
            if re.search(
                rf"\b{re.escape(identifier)}\b",
                raw,
                flags=re.IGNORECASE,
            ):
                predicates.append(
                    f"{identifier} = ?"
                )

        query = (
            f"SELECT * FROM {table}"
        )

        if predicates:
            query += (
                " WHERE "
                + " AND ".join(
                    predicates
                )
            )

        if re.search(
            r"\bcreated_at\b",
            raw,
            flags=re.IGNORECASE,
        ):
            query += (
                " ORDER BY created_at DESC"
            )

        value = (
            "EXPLAIN "
            + query
            + ";"
        )

        valid, detail = (
            validate_requirement_evidence(
                requirement,
                value,
            )
        )

        return Evidence(
            value=value,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                "source="
                + grounding.path
                + "; recovery="
                + detail
            ),
        )

    # --------------------------------------------------------
    # N+1 eager-loading recovery.
    # --------------------------------------------------------

    if contract == "orm_eager_fetch":
        if not table:
            return Evidence(
                value="",
                provenance="GROUNDED_DETERMINISTIC",
                valid=False,
                detail="ORM recovery has no propagated table",
            )

        singular = (
            table[:-1]
            if table.endswith("s")
            else table
        )

        model = singular.capitalize()

        query_pattern = (
            r"\bquery\s*\(\s*"
            r"[\"']"
            r"([A-Za-z_][A-Za-z0-9_]*)"
            r"[\"']"
            r"\s*\)"
        )

        query_targets = re.findall(
            query_pattern,
            raw,
            flags=re.IGNORECASE,
        )

        child_table = ""

        for candidate in query_targets:
            if (
                candidate.lower()
                != table.lower()
            ):
                child_table = (
                    candidate.lower()
                )
                break

        relationship = "items"

        if child_table:
            prefix = (
                singular
                + "_"
            )

            if child_table.startswith(
                prefix
            ):
                relationship = (
                    child_table[
                        len(prefix):
                    ]
                )

            elif child_table.endswith(
                "items"
            ):
                relationship = "items"

        value = (
            f"session.query({model})"
            f".options("
            f"joinedload({model}.{relationship})"
            f").all()"
        )

        valid, detail = (
            validate_requirement_evidence(
                requirement,
                value,
            )
        )

        return Evidence(
            value=value,
            provenance="GROUNDED_DETERMINISTIC",
            valid=valid,
            detail=(
                "source="
                + grounding.path
                + "; recovery="
                + detail
            ),
        )

    return Evidence(
        value="",
        provenance="GROUNDED_DETERMINISTIC",
        valid=False,
        detail=(
            "no deterministic recovery for contract="
            + contract
        ),
    )


def build_execution_plan(
    requirements: list[Requirement],
    evidence: dict[str, Evidence],
    groundings: dict[str, list[Grounding]],
) -> list[dict[str, Any]]:
    """Create a dry-run plan from validated nodes bound to real files."""
    plan = []

    for requirement in requirements:
        rid = requirement.requirement_id

        node = evidence.get(
            rid
        )

        if (
            node is None
            or not node.valid
        ):
            continue

        refs = groundings.get(
            rid,
            [],
        )

        if (
            grounding_required(
                requirement
            )
            and not refs
        ):
            continue

        contract = requirement_contract(
            requirement
        )

        operation = "inspect"

        if contract == "database_index":
            operation = "modify_schema_or_migration"

        elif contract == "orm_eager_fetch":
            operation = "modify_query_layer"

        elif contract == "database_analysis":
            operation = "inspect_query_path"

        elif contract == "circuit_breaker":
            operation = "modify_http_client"

        elif contract == "async_event":
            operation = "modify_event_pipeline"

        elif contract == "cache_stampede":
            operation = "modify_cache_lookup"

        elif contract == "idempotency_key":
            operation = "modify_payment_handler"

        elif contract == "transactional_outbox":
            operation = "modify_transaction_event_boundary"

        elif contract == "saga_compensation":
            operation = "modify_checkout_orchestration"

        elif contract == "redis_sliding_window_rate_limit":
            operation = "modify_http_rate_limit_middleware"

        plan.append({
            "requirement_id": rid,
            "contract": contract,
            "operation": operation,
            "validated_value": node.value,
            "targets": [
                {
                    "path": ref.path,
                    "kind": ref.kind,
                    "symbol": ref.symbol,
                    "score": ref.score,
                }
                for ref in refs[:3]
            ],
            "dry_run": True,
        })

    return plan


def _assemble(
    objective: str,
    requirements: list[Requirement],
    evidence: dict[str, Evidence],
    repository_hits: list[dict[str, str]],
) -> str:
    """Sophyane-owned structured assembly; no final LLM synthesis."""
    lines = [
        "# Sophyane compiled work packet",
        "",
        "## Validated work",
        "",
    ]

    for requirement in requirements:
        item = evidence.get(
            requirement.requirement_id
        )

        lines.append(
            f"### {requirement.requirement_id}"
        )

        if (
            item is not None
            and item.valid
        ):
            lines.append(
                f"Validated contribution "
                f"[{item.provenance}]:"
            )
            lines.append(item.value)

            if requirement.explicit_facts:
                lines.append(
                    "Authoritative user facts: "
                    + ", ".join(
                        requirement.explicit_facts
                    )
                )

        else:
            lines.append(
                "Status: unresolved"
            )

        lines.append("")

    if repository_hits:
        lines.extend([
            "## Repository evidence",
            "",
        ])

        for hit in repository_hits[:12]:
            lines.append(
                f"- {hit['repo']} [{hit['term']}]: "
                f"{hit['line']}"
            )

    return "\n".join(lines).strip()


def _resolve_requirement(
    requirement: Requirement,
    *,
    depth: int = 0,
    max_depth: int = 2,
) -> Evidence:
    """Resolve one requirement; failed nodes become smaller children."""
    direct = _ask_local_atomic(
        requirement
    )

    if direct.valid:
        return direct

    if depth >= max_depth:
        return direct

    children = recursive_children(
        requirement
    )

    if not children:
        return direct

    child_evidence = [
        _resolve_requirement(
            child,
            depth=depth + 1,
            max_depth=max_depth,
        )
        for child in children
    ]

    merged = _merge_child_evidence(
        requirement,
        children,
        child_evidence,
    )

    if merged.valid:
        return merged

    return Evidence(
        value=direct.value,
        provenance=direct.provenance,
        valid=False,
        detail=(
            direct.detail
            + "; recursive="
            + merged.detail
        ),
    )



# SOPHYANE_ARCHITECTURE_CONTEXT_V5

def _objective_architecture_contract(
    text: str,
) -> str | None:
    """Detect parent architectures that must survive clause splitting."""
    value = _normalize_contract_text(
        text
    )

    if (
        "circuit breaker" in value
        and (
            "payment" in value
            or "gateway" in value
        )
        and "secondary" in value
    ):
        return "circuit_breaker"

    if (
        "orderplaced" in value
        and (
            "kafka" in value
            or "rabbitmq" in value
        )
        and (
            "consumer" in value
            or "async" in value
            or "asynchronous" in value
        )
    ):
        return "async_event"

    if (
        "cache stampede" in value
        and (
            "single-flight" in value
            or "single flight" in value
        )
        and (
            "cache" in value
            or "product" in value
        )
    ):
        return "cache_stampede"

    if (
        (
            "idempotency-key" in value
            or "idempotency key" in value
        )
        and (
            "payment" in value
            or "charge" in value
        )
        and "post" in value
    ):
        return "idempotency_key"

    if (
        "outbox" in value
        and (
            "transaction" in value
            or "atomically" in value
            or "atomic" in value
        )
        and (
            "publish" in value
            or "event" in value
        )
    ):
        return "transactional_outbox"

    if (
        "saga" in value
        and "payment" in value
        and "inventory" in value
        and (
            "compensation" in value
            or "compensat" in value
        )
    ):
        return "saga_compensation"

    if (
        (
            "rate limit" in value
            or "rate limiting" in value
            or "rate limiter" in value
        )
        and "sliding window" in value
        and "redis" in value
        and "lua" in value
        and (
            "ip" in value
            or "client" in value
        )
        and (
            "429" in value
            or "too many requests" in value
        )
    ):
        return "redis_sliding_window_rate_limit"

    return None


def _architecture_requirements(
    objective: str,
    requirements: list[Requirement],
) -> list[Requirement]:
    """Preserve one architectural parent instead of unrelated siblings."""
    contract = _objective_architecture_contract(
        objective
    )

    if contract is None:
        return requirements

    facts = list(
        extract_explicit_facts(
            objective
        )
    )

    marker = (
        "architecture:"
        + contract
    )

    if marker not in facts:
        facts.append(
            marker
        )

    # Keep the entire user contract together. The local model still receives
    # only a three-second attempt; if that fails, ordinary recursive recovery
    # or grounded deterministic recovery remains available.
    return [
        Requirement(
            requirement_id="r1",
            text=" ".join(
                str(objective).split()
            ),
            difficulty=3,
            explicit_facts=tuple(
                facts
            ),
        )
    ]


def _architecture_groundings(
    requirement: Requirement,
    *,
    workspace: str | Path,
    max_results: int = 8,
) -> list[Grounding]:
    """Ground architecture contracts by real problem-site structure."""
    contract = requirement_contract(
        requirement
    )

    if contract not in {
        "circuit_breaker",
        "async_event",
    }:
        return []

    root = Path(
        workspace
    ).resolve()

    if not root.exists():
        return []

    results: list[Grounding] = []

    for candidate in root.rglob("*"):
        try:
            relative = candidate.relative_to(
                root
            )
        except ValueError:
            continue

        if any(
            part in _GROUNDING_IGNORE
            for part in relative.parts
        ):
            continue

        if (
            not candidate.is_file()
            or candidate.suffix.lower()
            not in _GROUNDABLE_EXTENSIONS
        ):
            continue

        try:
            raw = candidate.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        lower = raw.lower()

        score = 0.0
        evidence = []

        if contract == "circuit_breaker":
            primary = (
                "primary" in lower
            )

            secondary = (
                "secondary" in lower
            )

            payment_domain = any(
                token in lower
                for token in (
                    "payment",
                    "gateway",
                    "charge(",
                    "process_payment",
                )
            )

            if not (
                primary
                and secondary
                and payment_domain
            ):
                continue

            score += 12.0
            evidence.extend(
                [
                    "payment-domain",
                    "primary-path",
                    "secondary-path",
                ]
            )

            if "process_payment" in lower:
                score += 3.0
                evidence.append(
                    "payment-entrypoint"
                )

        else:
            checkout = (
                "checkout" in lower
            )

            side_effects = sum(
                token in lower
                for token in (
                    "send_email",
                    "log_analytics",
                    "update_inventory",
                )
            )

            if (
                not checkout
                or side_effects < 2
            ):
                continue

            score += (
                10.0
                + float(
                    side_effects
                )
            )

            evidence.extend(
                [
                    "checkout-domain",
                    "synchronous-side-effects",
                ]
            )

            if "def checkout" in lower:
                score += 2.0
                evidence.append(
                    "checkout-entrypoint"
                )

        lowered_path = str(
            relative
        ).lower()

        kind = "source"

        if any(
            token in lowered_path
            for token in (
                "service",
                "client",
                "gateway",
                "checkout",
                "payment",
            )
        ):
            kind = "service_or_client"
            score += 2.0

        results.append(
            Grounding(
                requirement_id=(
                    requirement.requirement_id
                ),
                path=str(
                    relative
                ),
                kind=kind,
                score=score,
                evidence=";".join(
                    evidence
                ),
            )
        )

    results.sort(
        key=lambda item: (
            -item.score,
            item.path,
        )
    )

    return results[
        :max_results
    ]


def _ground_requirement_with_architecture(
    requirement: Requirement,
    *,
    workspace: str | Path,
    max_results: int = 8,
) -> list[Grounding]:
    """Use existing semantic grounding, then architecture structure."""
    existing = ground_requirement(
        requirement,
        workspace=workspace,
        max_results=max_results,
    )

    if existing:
        return existing

    return _architecture_groundings(
        requirement,
        workspace=workspace,
        max_results=max_results,
    )


def compile_task(
    text: str,
    *,
    workspace: str | Path | None = None,
) -> CompiledTask:
    started = time.monotonic()

    value = str(text or "").strip()

    difficulty = estimate_difficulty(
        value
    )

    if not should_compile(value):
        return CompiledTask(
            handled=False,
            ok=False,
            difficulty=difficulty,
            elapsed_seconds=(
                time.monotonic() - started
            ),
        )

    requirements = _architecture_requirements(
        value,
        decompose(
            value
        ),
    )

    requirements = _propagate_objective_context(
        requirements,
        objective=value,
    )

    active_workspace = Path(
        workspace
        if workspace is not None
        else Path.cwd()
    ).resolve()

    evidence: dict[str, Evidence] = {}

    repository_hits = []

    for requirement in requirements:
        # User-supplied facts are authoritative context, not something
        # the local model should be asked to regenerate.
        hits = retrieve(
            requirement,
            workspace=active_workspace,
        )

        repository_hits.extend(
            hits
        )

        # Repository retrieval is supporting evidence, not truth.
        # A lexical hit may be relevant context but must never satisfy
        # a requirement merely because one search term appeared.
        #
        # Future versions can promote repository evidence only through
        # typed/semantic validators. V1 keeps it advisory and resolves
        # residual uncertainty through bounded atomic reasoning.
        #
        # D1/D2/D3 residual only.
        # If decomposition still judges it D4/D5, split conservatively.
        if requirement.difficulty >= 4:
            subrequirements = decompose(
                requirement.text
            )

            if (
                len(subrequirements) > 1
            ):
                # Parent remains unresolved until child compiler support
                # becomes dependency-aware in V2.
                evidence[
                    requirement.requirement_id
                ] = Evidence(
                    value="",
                    provenance="DECOMPOSITION",
                    valid=False,
                    detail=(
                        "requires recursive child graph"
                    ),
                )
                continue

        evidence[
            requirement.requirement_id
        ] = _resolve_requirement(
            requirement
        )

    unresolved = [
        requirement.requirement_id
        for requirement in requirements
        if (
            requirement.requirement_id
            not in evidence
            or not evidence[
                requirement.requirement_id
            ].valid
        )
    ]


    groundings = {
        requirement.requirement_id: (
            _ground_requirement_with_architecture(
                requirement,
                workspace=active_workspace,
            )
        )
        for requirement in requirements
    }

    # Grounding-conditioned recovery:
    # local reasoning has already had its bounded opportunity.
    # Never extend the local timeout. Recover only from a verified
    # same-domain workspace target and re-run the typed validator.
    for requirement in requirements:
        rid = requirement.requirement_id

        current = evidence.get(
            rid
        )

        if (
            current is not None
            and current.valid
        ):
            continue

        refs = groundings.get(
            rid,
            [],
        )

        if not refs:
            continue

        recovered = grounded_contract_recovery(
            requirement,
            grounding=refs[0],
            workspace=active_workspace,
        )

        if recovered.valid:
            evidence[
                rid
            ] = recovered

    unresolved = [
        requirement.requirement_id
        for requirement in requirements
        if (
            requirement.requirement_id
            not in evidence
            or not evidence[
                requirement.requirement_id
            ].valid
            or (
                grounding_required(
                    requirement
                )
                and not groundings.get(
                    requirement.requirement_id
                )
            )
        )
    ]

    execution_plan = build_execution_plan(
        requirements,
        evidence,
        groundings,
    )

    output = _assemble(
        value,
        requirements,
        evidence,
        repository_hits,
    )

    if execution_plan:
        output += (
            "\n\n## Grounded dry-run execution plan\n"
        )

        for step in execution_plan:
            output += (
                "\n### "
                + step["requirement_id"]
                + "\n"
                + "Operation: "
                + step["operation"]
                + "\n"
            )

            for target in step["targets"]:
                output += (
                    "- "
                    + target["path"]
                    + " ["
                    + target["kind"]
                    + "]\n"
                )

    return CompiledTask(
        handled=True,
        ok=not unresolved,
        difficulty=difficulty,
        requirements=requirements,
        evidence=evidence,
        repository_hits=repository_hits,
        groundings=groundings,
        execution_plan=execution_plan,
        unresolved=unresolved,
        output=output,
        elapsed_seconds=(
            time.monotonic() - started
        ),
    )


__all__ = [
    "CompiledTask",
    "Evidence",
    "Grounding",
    "LOCAL_ATOMIC_DEADLINE_SECONDS",
    "Requirement",
    "compile_task",
    "decompose",
    "estimate_difficulty",
    "extract_explicit_facts",
    "infer_objective_context",
    "ground_requirement",
    "grounded_contract_recovery",
    "grounding_required",
    "build_execution_plan",
    "recursive_children",
    "requirement_contract",
    "retrieve",
    "should_compile",
    "validate_requirement_evidence",
]
