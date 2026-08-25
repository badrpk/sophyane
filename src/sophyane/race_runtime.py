from __future__ import annotations

# SOPHYANE_ADAPTIVE_RACE_CORE_V1

from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass, field
from enum import Enum
from threading import Event, Lock
from time import monotonic
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


class RaceStatus(str, Enum):
    STARTED = "started"
    PROGRESS = "progress"
    VALID = "valid"
    INVALID = "invalid"
    FAILED = "failed"
    STALLED = "stalled"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RaceCandidate(Generic[T]):
    worker: str
    value: T
    score: float = 0.0
    evidence: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class RaceEvent:
    worker: str
    status: RaceStatus
    message: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class RaceResult(Generic[T]):
    winner: RaceCandidate[T] | None
    candidates: list[RaceCandidate[T]] = field(
        default_factory=list
    )
    events: list[RaceEvent] = field(
        default_factory=list
    )
    errors: dict[str, str] = field(
        default_factory=dict
    )

    @property
    def ok(self) -> bool:
        return self.winner is not None


Worker = Callable[
    [
        Event,
        Callable[
            [RaceStatus, str],
            None,
        ],
    ],
    T,
]

Validator = Callable[
    [
        str,
        T,
    ],
    tuple[
        bool,
        float,
        tuple[str, ...],
    ],
]


class AdaptiveRace(Generic[T]):
    """Run independent workers concurrently.

    Workers may inspect, plan, acquire, or generate candidate results.

    They MUST NOT directly mutate the authoritative project workspace.
    Only the selected winner may later receive a write lease.
    """

    def __init__(
        self,
        *,
        validator: Validator[T],
        minimum_score: float = 0.0,
        winner_grace_seconds: float = 0.35,
    ) -> None:
        self.validator = validator
        self.minimum_score = float(
            minimum_score
        )
        self.winner_grace_seconds = max(
            0.0,
            float(
                winner_grace_seconds
            ),
        )

    def run(
        self,
        workers: dict[
            str,
            Worker[T],
        ],
        *,
        timeout: float | None = None,
    ) -> RaceResult[T]:
        if not workers:
            return RaceResult(
                winner=None
            )

        stop = Event()

        events: list[RaceEvent] = []
        candidates: list[
            RaceCandidate[T]
        ] = []
        errors: dict[str, str] = {}

        lock = Lock()

        started = monotonic()

        def elapsed() -> float:
            return (
                monotonic()
                - started
            )

        def reporter(
            worker: str,
        ):
            def report(
                status: RaceStatus,
                message: str = "",
            ) -> None:
                with lock:
                    events.append(
                        RaceEvent(
                            worker=worker,
                            status=status,
                            message=str(
                                message
                                or ""
                            ),
                            elapsed_seconds=elapsed(),
                        )
                    )

            return report

        def invoke(
            worker: str,
            callback: Worker[T],
        ):
            report = reporter(
                worker
            )

            report(
                RaceStatus.STARTED
            )

            try:
                value = callback(
                    stop,
                    report,
                )

                return (
                    worker,
                    value,
                    None,
                )

            except SystemExit as exc:
                # A worker-local SystemExit is a worker failure,
                # not authority to terminate the race host.
                return (
                    worker,
                    None,
                    exc,
                )

            except Exception as exc:
                return (
                    worker,
                    None,
                    exc,
                )

        executor = ThreadPoolExecutor(
            max_workers=len(
                workers
            ),
            thread_name_prefix=(
                "sophyane-race"
            ),
        )

        futures: dict[
            Future,
            str,
        ] = {}

        for worker, callback in (
            workers.items()
        ):
            future = executor.submit(
                invoke,
                worker,
                callback,
            )

            futures[
                future
            ] = worker

        pending = set(
            futures
        )

        deadline = (
            None
            if timeout is None
            else started
            + max(
                0.0,
                float(timeout),
            )
        )

        winner: (
            RaceCandidate[T]
            | None
        ) = None

        try:
            while pending:
                remaining = None

                if deadline is not None:
                    remaining = (
                        deadline
                        - monotonic()
                    )

                    if remaining <= 0:
                        break

                done, pending = wait(
                    pending,
                    timeout=remaining,
                    return_when=(
                        FIRST_COMPLETED
                    ),
                )

                if not done:
                    break

                new_valid: list[
                    RaceCandidate[T]
                ] = []

                for future in done:
                    worker = (
                        futures[
                            future
                        ]
                    )

                    try:
                        (
                            _worker,
                            value,
                            error,
                        ) = future.result()

                    except Exception as exc:
                        error = exc
                        value = None

                    if error is not None:
                        errors[
                            worker
                        ] = (
                            f"{type(error).__name__}: "
                            f"{error}"
                        )

                        events.append(
                            RaceEvent(
                                worker=worker,
                                status=(
                                    RaceStatus.FAILED
                                ),
                                message=(
                                    errors[
                                        worker
                                    ]
                                ),
                                elapsed_seconds=elapsed(),
                            )
                        )

                        continue

                    valid = False
                    score = 0.0
                    evidence: tuple[
                        str,
                        ...,
                    ] = ()

                    try:
                        (
                            valid,
                            score,
                            evidence,
                        ) = self.validator(
                            worker,
                            value,
                        )

                    except Exception as exc:
                        errors[
                            worker
                        ] = (
                            "validator: "
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        )

                        events.append(
                            RaceEvent(
                                worker=worker,
                                status=(
                                    RaceStatus.FAILED
                                ),
                                message=(
                                    errors[
                                        worker
                                    ]
                                ),
                                elapsed_seconds=elapsed(),
                            )
                        )

                        continue

                    candidate = (
                        RaceCandidate(
                            worker=worker,
                            value=value,
                            score=float(
                                score
                            ),
                            evidence=tuple(
                                evidence
                            ),
                            elapsed_seconds=elapsed(),
                        )
                    )

                    candidates.append(
                        candidate
                    )

                    if (
                        valid
                        and candidate.score
                        >= self.minimum_score
                    ):
                        new_valid.append(
                            candidate
                        )

                        events.append(
                            RaceEvent(
                                worker=worker,
                                status=(
                                    RaceStatus.VALID
                                ),
                                message=(
                                    f"score={candidate.score:.3f}"
                                ),
                                elapsed_seconds=elapsed(),
                            )
                        )

                    else:
                        events.append(
                            RaceEvent(
                                worker=worker,
                                status=(
                                    RaceStatus.INVALID
                                ),
                                message=(
                                    f"score={candidate.score:.3f}"
                                ),
                                elapsed_seconds=elapsed(),
                            )
                        )

                if new_valid:
                    # First validated completion establishes the front-runner.
                    # If multiple workers complete in the same scheduling
                    # window, prefer stronger evidence.
                    winner = max(
                        new_valid,
                        key=lambda item: (
                            item.score,
                            -item.elapsed_seconds,
                        ),
                    )

                    # Brief grace period allows an effectively simultaneous
                    # stronger candidate to finish without turning this into
                    # sequential fallback.
                    if (
                        pending
                        and self.winner_grace_seconds
                        > 0
                    ):
                        grace_done, still_pending = wait(
                            pending,
                            timeout=(
                                self.winner_grace_seconds
                            ),
                        )

                        pending = (
                            still_pending
                        )

                        for future in (
                            grace_done
                        ):
                            worker = (
                                futures[
                                    future
                                ]
                            )

                            try:
                                (
                                    _,
                                    value,
                                    error,
                                ) = future.result()

                            except Exception as exc:
                                error = exc
                                value = None

                            if error is not None:
                                errors[
                                    worker
                                ] = (
                                    f"{type(error).__name__}: "
                                    f"{error}"
                                )

                                continue

                            try:
                                (
                                    valid,
                                    score,
                                    evidence,
                                ) = self.validator(
                                    worker,
                                    value,
                                )

                            except Exception as exc:
                                errors[
                                    worker
                                ] = (
                                    "validator: "
                                    f"{type(exc).__name__}: "
                                    f"{exc}"
                                )

                                continue

                            candidate = (
                                RaceCandidate(
                                    worker=worker,
                                    value=value,
                                    score=float(
                                        score
                                    ),
                                    evidence=tuple(
                                        evidence
                                    ),
                                    elapsed_seconds=elapsed(),
                                )
                            )

                            candidates.append(
                                candidate
                            )

                            if (
                                valid
                                and candidate.score
                                >= self.minimum_score
                                and candidate.score
                                > winner.score
                            ):
                                winner = (
                                    candidate
                                )

                    stop.set()

                    break

        finally:
            stop.set()

            for future in pending:
                future.cancel()

            executor.shutdown(
                wait=False,
                cancel_futures=True,
            )

        candidates.sort(
            key=lambda item: (
                item.elapsed_seconds,
                -item.score,
            )
        )

        return RaceResult(
            winner=winner,
            candidates=candidates,
            events=events,
            errors=errors,
        )
