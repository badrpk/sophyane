"""General scenario verification for Sophyane Research Environments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .model import (
    VerificationResult,
)
from .world import (
    ResearchEnvironment,
)


class Verifier:
    name = "verifier"

    def verify(
        self,
        environment:
            ResearchEnvironment,
    ) -> VerificationResult:
        raise NotImplementedError


@dataclass(frozen=True)
class ExactVerifier(
    Verifier
):
    key: str
    expected: Any
    name: str = "exact"

    def verify(
        self,
        environment:
            ResearchEnvironment,
    ) -> VerificationResult:
        actual = (
            environment.state.get(
                self.key
            )
        )

        ok = (
            actual
            == self.expected
        )

        return VerificationResult(
            ok=ok,
            score=1.0 if ok else 0.0,
            verifier=self.name,
            evidence=(
                f"{self.key}={actual!r}",
                f"expected={self.expected!r}",
            ),
        )


@dataclass(frozen=True)
class StateVerifier(
    Verifier
):
    predicate: Callable[
        [dict[str, Any]],
        bool,
    ]
    description: str
    name: str = "state"

    def verify(
        self,
        environment:
            ResearchEnvironment,
    ) -> VerificationResult:
        try:
            ok = bool(
                self.predicate(
                    environment.state
                )
            )

        except Exception as error:
            return VerificationResult(
                ok=False,
                score=0.0,
                verifier=self.name,
                evidence=(
                    "predicate_error="
                    + type(error).__name__
                    + ":"
                    + str(error),
                ),
            )

        return VerificationResult(
            ok=ok,
            score=1.0 if ok else 0.0,
            verifier=self.name,
            evidence=(
                self.description,
            ),
        )


@dataclass(frozen=True)
class TemporalVerifier(
    Verifier
):
    predicate: Callable[
        [dict[str, Any]],
        bool,
    ]
    deadline: float
    description: str
    name: str = "temporal"

    def verify(
        self,
        environment:
            ResearchEnvironment,
    ) -> VerificationResult:
        state_ok = bool(
            self.predicate(
                environment.state
            )
        )

        time_ok = (
            environment.clock
            <= self.deadline
        )

        ok = (
            state_ok
            and time_ok
        )

        return VerificationResult(
            ok=ok,
            score=(
                1.0
                if ok
                else (
                    0.5
                    if state_ok
                    else 0.0
                )
            ),
            verifier=self.name,
            evidence=(
                self.description,
                f"clock={environment.clock}",
                f"deadline={self.deadline}",
            ),
        )


@dataclass(frozen=True)
class ConstraintVerifier(
    Verifier
):
    constraints: tuple[
        Callable[
            [dict[str, Any]],
            bool,
        ],
        ...
    ]
    labels: tuple[str, ...] = ()
    name: str = "constraint"

    def verify(
        self,
        environment:
            ResearchEnvironment,
    ) -> VerificationResult:
        outcomes = []

        for index, constraint in enumerate(
            self.constraints
        ):
            try:
                ok = bool(
                    constraint(
                        environment.state
                    )
                )

            except Exception:
                ok = False

            label = (
                self.labels[index]
                if index
                < len(self.labels)
                else (
                    "constraint_"
                    + str(index)
                )
            )

            outcomes.append(
                (
                    label,
                    ok,
                )
            )

        passed = sum(
            1
            for _, ok in outcomes
            if ok
        )

        total = max(
            1,
            len(outcomes),
        )

        score = (
            passed
            / total
        )

        return VerificationResult(
            ok=(
                passed
                == len(outcomes)
            ),
            score=score,
            verifier=self.name,
            evidence=tuple(
                f"{label}={ok}"
                for label, ok
                in outcomes
            ),
        )


@dataclass(frozen=True)
class SafetyVerifier(
    Verifier
):
    forbidden_keys: tuple[
        str,
        ...
    ] = ()
    name: str = "safety"

    def verify(
        self,
        environment:
            ResearchEnvironment,
    ) -> VerificationResult:
        violations = [
            key
            for key
            in self.forbidden_keys
            if environment.state.get(
                key
            )
        ]

        return VerificationResult(
            ok=not violations,
            score=(
                1.0
                if not violations
                else 0.0
            ),
            verifier=self.name,
            evidence=tuple(
                "violation="
                + item
                for item in violations
            ),
        )


@dataclass(frozen=True)
class RegressionVerifier(
    Verifier
):
    baseline: float
    candidate_score: Callable[
        [dict[str, Any]],
        float,
    ]
    tolerance: float = 0.0
    name: str = "regression"

    def verify(
        self,
        environment:
            ResearchEnvironment,
    ) -> VerificationResult:
        score = float(
            self.candidate_score(
                environment.state
            )
        )

        ok = (
            score
            + self.tolerance
            >= self.baseline
        )

        return VerificationResult(
            ok=ok,
            score=max(
                0.0,
                min(
                    1.0,
                    score,
                ),
            ),
            verifier=self.name,
            evidence=(
                f"baseline={self.baseline}",
                f"candidate={score}",
                f"tolerance={self.tolerance}",
            ),
        )


class CompositeVerifier(
    Verifier
):
    name = "composite"

    def __init__(
        self,
        verifiers:
            tuple[
                Verifier,
                ...
            ],
        *,
        minimum_score:
            float = 1.0,
    ) -> None:
        self.verifiers = (
            verifiers
        )
        self.minimum_score = float(
            minimum_score
        )

    def verify(
        self,
        environment:
            ResearchEnvironment,
    ) -> VerificationResult:
        results = tuple(
            verifier.verify(
                environment
            )
            for verifier
            in self.verifiers
        )

        if not results:
            return VerificationResult(
                ok=False,
                score=0.0,
                verifier=self.name,
                evidence=(
                    "no_verifiers",
                ),
            )

        score = sum(
            result.score
            for result in results
        ) / len(results)

        hard_ok = all(
            result.ok
            for result in results
        )

        return VerificationResult(
            ok=(
                hard_ok
                and score
                >= self.minimum_score
            ),
            score=score,
            verifier=self.name,
            evidence=tuple(
                (
                    result.verifier
                    + ":"
                    + str(result.ok)
                    + ":"
                    + f"{result.score:.3f}"
                )
                for result
                in results
            ),
            details={
                "results": [
                    {
                        "verifier":
                            result.verifier,
                        "ok":
                            result.ok,
                        "score":
                            result.score,
                        "evidence":
                            list(
                                result.evidence
                            ),
                    }
                    for result
                    in results
                ]
            },
        )
