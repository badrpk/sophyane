"""Persistent memory for successful Sophyane repairs."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

from .goal_execution import ExecutionEvent


_WHITESPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"\b\d+\b")
_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\|/)[^\s:'\"]+",
    flags=re.UNICODE,
)


def normalize_failure(text: str) -> str:
    """Normalize unstable error details while preserving useful meaning."""
    value = str(text or "").strip().lower()
    value = _PATH_RE.sub("<path>", value)
    value = _NUMBER_RE.sub("<n>", value)
    value = _WHITESPACE_RE.sub(" ", value)
    return value.strip()


def failure_fingerprint(text: str) -> str:
    """Return a deterministic fingerprint for normalized failure text."""
    normalized = normalize_failure(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RepairMemory:
    fingerprint: str
    normalized_error: str
    original_error: str
    repair_summary: str
    goal: str
    provider: str
    confidence: float
    timestamp: float
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RepairMemory":
        return cls(
            fingerprint=str(payload["fingerprint"]),
            normalized_error=str(payload["normalized_error"]),
            original_error=str(payload["original_error"]),
            repair_summary=str(payload["repair_summary"]),
            goal=str(payload.get("goal", "")),
            provider=str(payload.get("provider", "")),
            confidence=float(payload.get("confidence", 0.0)),
            timestamp=float(payload.get("timestamp", 0.0)),
            metadata=payload.get("metadata"),
        )


@dataclass(frozen=True)
class RepairMatch:
    memory: RepairMemory
    similarity: float


class FailureMemory:
    """Thread-safe JSONL store containing only successful repairs."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def entries(self) -> tuple[RepairMemory, ...]:
        if not self.path.is_file():
            return ()

        memories: list[RepairMemory] = []

        with self._lock:
            for line in self.path.read_text(
                encoding="utf-8",
            ).splitlines():
                if not line.strip():
                    continue

                try:
                    payload = json.loads(line)
                    memories.append(RepairMemory.from_dict(payload))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    # One damaged record must not disable all memory.
                    continue

        return tuple(memories)

    def remember_success(
        self,
        *,
        error: str,
        repair_summary: str,
        goal: str = "",
        provider: str = "",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> RepairMemory:
        """Store a repair after validation has confirmed success."""
        normalized = normalize_failure(error)

        if not normalized:
            raise ValueError("error must not be empty")

        if not repair_summary.strip():
            raise ValueError("repair_summary must not be empty")

        memory = RepairMemory(
            fingerprint=failure_fingerprint(error),
            normalized_error=normalized,
            original_error=error.strip(),
            repair_summary=repair_summary.strip(),
            goal=goal.strip(),
            provider=provider.strip(),
            confidence=max(0.0, min(1.0, float(confidence))),
            timestamp=time.time(),
            metadata=dict(metadata) if metadata else None,
        )

        with self._lock:
            existing = self.entries()

            duplicate = any(
                item.fingerprint == memory.fingerprint
                and normalize_failure(item.repair_summary)
                == normalize_failure(memory.repair_summary)
                and item.goal == memory.goal
                for item in existing
            )

            if not duplicate:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            memory.to_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )

        return memory

    def lookup(
        self,
        error: str,
        *,
        goal: str = "",
        minimum_similarity: float = 0.72,
        limit: int = 3,
    ) -> tuple[RepairMatch, ...]:
        """Find proven repairs for an exact or similar failure."""
        if limit < 1:
            return ()

        query = normalize_failure(error)
        if not query:
            return ()

        matches: list[RepairMatch] = []

        for memory in self.entries():
            if goal and memory.goal and memory.goal != goal:
                continue

            if memory.normalized_error == query:
                similarity = 1.0
            else:
                similarity = SequenceMatcher(
                    None,
                    query,
                    memory.normalized_error,
                ).ratio()

            if similarity >= minimum_similarity:
                matches.append(
                    RepairMatch(
                        memory=memory,
                        similarity=similarity,
                    )
                )

        matches.sort(
            key=lambda match: (
                match.similarity,
                match.memory.confidence,
                match.memory.timestamp,
            ),
            reverse=True,
        )

        return tuple(matches[:limit])

    def best_repair(
        self,
        error: str,
        *,
        goal: str = "",
        minimum_similarity: float = 0.72,
    ) -> RepairMatch | None:
        matches = self.lookup(
            error,
            goal=goal,
            minimum_similarity=minimum_similarity,
            limit=1,
        )
        return matches[0] if matches else None


class SuccessfulRepairObserver:
    """Record repairs only when a later validation event passes."""

    def __init__(
        self,
        memory: FailureMemory,
        *,
        provider: str = "",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.memory = memory
        self.provider = provider
        self.confidence = confidence
        self.metadata = dict(metadata or {})
        self._failures: dict[str, str] = {}
        self._repairs: dict[str, str] = {}
        self._lock = threading.Lock()

    def __call__(self, event: ExecutionEvent) -> None:
        with self._lock:
            if event.event == "validation_failed":
                error = "; ".join(event.errors) or event.summary
                if error.strip():
                    self._failures[event.goal] = error.strip()
                return

            if event.event == "action_started":
                if event.goal in self._failures:
                    self._repairs[event.goal] = event.summary.strip()
                return

            if event.event == "validation_passed":
                error = self._failures.pop(event.goal, "")
                repair = self._repairs.pop(event.goal, "")

                if error and repair:
                    self.memory.remember_success(
                        error=error,
                        repair_summary=repair,
                        goal=event.goal,
                        provider=self.provider,
                        confidence=self.confidence,
                        metadata=self.metadata,
                    )
                return

            if event.event in {
                "goal_failed",
                "goal_exhausted",
                "execution_stopped",
            }:
                self._failures.pop(event.goal, None)
                self._repairs.pop(event.goal, None)


class CompositeEventSink:
    """Send one execution event to several independent observers."""

    def __init__(
        self,
        *sinks: Callable[[ExecutionEvent], None],
    ) -> None:
        self.sinks = tuple(sinks)

    def __call__(self, event: ExecutionEvent) -> None:
        for sink in self.sinks:
            try:
                sink(event)
            except Exception:
                # Telemetry and memory must never stop execution.
                continue


def suggested_repair_context(
    memory: FailureMemory,
    error: str,
    *,
    goal: str = "",
    minimum_similarity: float = 0.72,
) -> str:
    """Render a proven prior repair for inclusion in a repair prompt."""
    match = memory.best_repair(
        error,
        goal=goal,
        minimum_similarity=minimum_similarity,
    )

    if match is None:
        return ""

    item = match.memory

    return (
        "A similar failure was repaired successfully before.\n"
        f"Similarity: {match.similarity:.2f}\n"
        f"Previous failure: {item.original_error}\n"
        f"Successful repair: {item.repair_summary}\n"
        "Use this only as evidence; still validate the current artifact."
    )
