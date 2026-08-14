from __future__ import annotations

# SOPHYANE_ADAPTIVE_RACE_ADAPTERS_V1

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Generic, TypeVar

from sophyane.race_runtime import (
    AdaptiveRace,
    RaceCandidate,
    RaceResult,
    RaceStatus,
)


T = TypeVar("T")


@dataclass(frozen=True)
class ProgressProposal(Generic[T]):
    """Validated speculative work from one intelligence source."""

    engine: str
    payload: T
    kind: str
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    requires_write: bool = False


class WorkspaceWriteLease:
    """Allow only one race participant to mutate the real workspace."""

    def __init__(
        self,
        workspace: str | Path,
    ) -> None:
        self.workspace = (
            Path(workspace)
            .expanduser()
            .resolve()
        )

        self._lock = Lock()
        self._owner: str | None = None
        self._generation = 0

    @property
    def owner(self) -> str | None:
        with self._lock:
            return self._owner

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def acquire(
        self,
        engine: str,
    ) -> bool:
        engine = str(
            engine
        ).strip()

        if not engine:
            return False

        with self._lock:
            if self._owner is None:
                self._owner = engine
                self._generation += 1
                return True

            return self._owner == engine

    def release(
        self,
        engine: str,
    ) -> bool:
        with self._lock:
            if self._owner != engine:
                return False

            self._owner = None
            return True

    def transfer(
        self,
        current: str,
        replacement: str,
    ) -> bool:
        replacement = str(
            replacement
        ).strip()

        if not replacement:
            return False

        with self._lock:
            if self._owner != current:
                return False

            self._owner = replacement
            self._generation += 1
            return True

    def assert_owner(
        self,
        engine: str,
    ) -> None:
        with self._lock:
            owner = self._owner

        if owner != engine:
            raise PermissionError(
                "Workspace mutation denied: "
                f"owner={owner!r}; "
                f"requester={engine!r}"
            )


def validate_progress_proposal(
    engine: str,
    proposal: ProgressProposal[Any],
) -> tuple[
    bool,
    float,
    tuple[str, ...],
]:
    if not isinstance(
        proposal,
        ProgressProposal,
    ):
        return (
            False,
            0.0,
            (
                "not a ProgressProposal",
            ),
        )

    if (
        proposal.engine
        and proposal.engine != engine
    ):
        return (
            False,
            0.0,
            (
                "engine identity mismatch",
            ),
        )

    kind = str(
        proposal.kind
    ).strip().lower()

    allowed = {
        "acquisition",
        "plan",
        "action",
        "patch",
        "verification",
        "answer",
    }

    if kind not in allowed:
        return (
            False,
            0.0,
            (
                f"unsupported proposal kind: {kind}",
            ),
        )

    if proposal.payload is None:
        return (
            False,
            0.0,
            (
                "empty payload",
            ),
        )

    score = max(
        0.0,
        min(
            1.0,
            float(
                proposal.confidence
            ),
        ),
    )

    evidence = tuple(
        str(item)
        for item in proposal.evidence
        if str(item).strip()
    )

    valid = bool(
        evidence
        or score >= 0.55
    )

    return (
        valid,
        score,
        evidence,
    )


class CooperativeRace(Generic[T]):
    """Race proposals and award mutation authority to the winner."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        minimum_score: float = 0.55,
        winner_grace_seconds: float = 0.20,
    ) -> None:
        self.workspace = (
            Path(workspace)
            .expanduser()
            .resolve()
        )

        self.lease = WorkspaceWriteLease(
            self.workspace
        )

        self.race = AdaptiveRace[
            ProgressProposal[T]
        ](
            validator=(
                validate_progress_proposal
            ),
            minimum_score=minimum_score,
            winner_grace_seconds=(
                winner_grace_seconds
            ),
        )

    def run(
        self,
        workers,
        *,
        timeout: float | None = None,
    ) -> RaceResult[
        ProgressProposal[T]
    ]:
        result = self.race.run(
            workers,
            timeout=timeout,
        )

        winner = result.winner

        if (
            winner is not None
            and winner.value.requires_write
        ):
            self.lease.acquire(
                winner.worker
            )

        return result

    def promote(
        self,
        candidate: RaceCandidate[
            ProgressProposal[T]
        ],
    ) -> bool:
        current = self.lease.owner

        if current is None:
            return self.lease.acquire(
                candidate.worker
            )

        return self.lease.transfer(
            current,
            candidate.worker,
        )


def proposal_worker(
    engine: str,
    producer: Callable[
        [],
        ProgressProposal[T],
    ],
):
    """Adapt a synchronous intelligence source to AdaptiveRace."""

    def worker(
        stop,
        report,
    ):
        if stop.is_set():
            raise RuntimeError(
                "race cancelled before start"
            )

        report(
            RaceStatus.PROGRESS,
            f"{engine}: speculative work started",
        )

        proposal = producer()

        if stop.is_set():
            report(
                RaceStatus.CANCELLED,
                f"{engine}: completed after winner",
            )
        else:
            report(
                RaceStatus.PROGRESS,
                f"{engine}: proposal ready",
            )

        return proposal

    return worker
