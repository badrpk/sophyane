"""Bounded Red Queen evaluator lifecycle for Sophyane evolution.

This module deliberately separates:

1. agent candidate fitness;
2. evaluator/challenger fitness;
3. trusted held-out anchor authority;
4. evaluator promotion;
5. epoch activation;
6. utility provenance;
7. selective invalidation.

The trusted anchor never self-promotes and is not replaceable by an
evolving evaluator. This prevents agent and evaluator drift from
manufacturing apparent progress together.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping, Sequence


STATUS_ACTIVE = "active"
STATUS_CHALLENGER = "challenger"
STATUS_RETIRED = "retired"
STATUS_REJECTED = "rejected"
STATUS_INVALIDATED = "invalidated"


@dataclass(frozen=True)
class EvaluatorSpec:
    evaluator_id: str
    version: int
    objective: str
    tests: tuple[str, ...]
    parent_id: str = ""
    generation: int = 0
    status: str = STATUS_CHALLENGER
    adversarial: bool = False
    created_at: float = field(
        default_factory=time.time
    )

    def identity(self) -> str:
        payload = {
            "evaluator_id": self.evaluator_id,
            "version": self.version,
            "objective": self.objective,
            "tests": self.tests,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "adversarial": self.adversarial,
        }

        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(
            encoded
        ).hexdigest()


@dataclass(frozen=True)
class EvaluationOutcome:
    candidate_id: str
    evaluator_id: str
    evaluator_version: int
    evaluator_identity: str
    epoch: int
    score: float
    passed: bool
    evidence: tuple[str, ...] = ()
    created_at: float = field(
        default_factory=time.time
    )


@dataclass(frozen=True)
class EvaluatorMatch:
    incumbent_id: str
    challenger_id: str
    incumbent_detection_score: float
    challenger_detection_score: float
    anchor_score: float
    challenger_wins: bool
    reason: str


@dataclass(frozen=True)
class PromotionDecision:
    accepted: bool
    evaluator_id: str
    previous_active_id: str
    epoch: int
    reason: str


@dataclass
class UtilityLedger:
    """Utility records with evaluator-version provenance."""

    records: list[EvaluationOutcome] = field(
        default_factory=list
    )
    invalidated_identities: set[str] = field(
        default_factory=set
    )

    def record(
        self,
        outcome: EvaluationOutcome,
    ) -> None:
        self.records.append(
            outcome
        )

    def invalidate_evaluator(
        self,
        evaluator_identity: str,
    ) -> int:
        self.invalidated_identities.add(
            evaluator_identity
        )

        return sum(
            1
            for item in self.records
            if item.evaluator_identity
            == evaluator_identity
        )

    def valid_records(
        self,
    ) -> tuple[EvaluationOutcome, ...]:
        return tuple(
            item
            for item in self.records
            if item.evaluator_identity
            not in self.invalidated_identities
        )

    def utility_for(
        self,
        candidate_id: str,
    ) -> float | None:
        scores = [
            item.score
            for item in self.valid_records()
            if item.candidate_id
            == candidate_id
        ]

        if not scores:
            return None

        return sum(scores) / len(scores)


@dataclass
class RedQueenState:
    """State machine for bounded evaluator co-evolution."""

    epoch: int
    trusted_anchor_id: str
    active: EvaluatorSpec
    challengers: dict[str, EvaluatorSpec] = field(
        default_factory=dict
    )
    retired: dict[str, EvaluatorSpec] = field(
        default_factory=dict
    )
    rejected: dict[str, EvaluatorSpec] = field(
        default_factory=dict
    )
    ledger: UtilityLedger = field(
        default_factory=UtilityLedger
    )

    def register_challenger(
        self,
        evaluator: EvaluatorSpec,
    ) -> None:
        if (
            evaluator.evaluator_id
            == self.trusted_anchor_id
        ):
            raise ValueError(
                "trusted anchor cannot be registered "
                "as an evolving challenger"
            )

        if (
            evaluator.evaluator_id
            == self.active.evaluator_id
        ):
            raise ValueError(
                "challenger must differ from active evaluator"
            )

        self.challengers[
            evaluator.evaluator_id
        ] = evaluator

    def record_outcome(
        self,
        *,
        candidate_id: str,
        evaluator: EvaluatorSpec,
        score: float,
        passed: bool,
        evidence: Sequence[str] = (),
    ) -> EvaluationOutcome:
        outcome = EvaluationOutcome(
            candidate_id=candidate_id,
            evaluator_id=evaluator.evaluator_id,
            evaluator_version=evaluator.version,
            evaluator_identity=evaluator.identity(),
            epoch=self.epoch,
            score=float(score),
            passed=bool(passed),
            evidence=tuple(evidence),
        )

        self.ledger.record(
            outcome
        )

        return outcome


def build_adversarial_challenger(
    *,
    incumbent: EvaluatorSpec,
    observed_failures: Sequence[str],
    evaluator_id: str,
) -> EvaluatorSpec:
    """Create a challenger aimed specifically at incumbent blind spots."""

    failures = tuple(
        item.strip()
        for item in observed_failures
        if item.strip()
    )

    if not failures:
        raise ValueError(
            "adversarial challenger requires observed failures"
        )

    objective = (
        "Adversarially detect failures missed by "
        f"{incumbent.evaluator_id}: "
        + "; ".join(failures)
    )

    generated_tests = tuple(
        "challenge::"
        + hashlib.sha256(
            failure.encode("utf-8")
        ).hexdigest()[:16]
        for failure in failures
    )

    return EvaluatorSpec(
        evaluator_id=evaluator_id,
        version=incumbent.version + 1,
        objective=objective,
        tests=generated_tests,
        parent_id=incumbent.evaluator_id,
        generation=incumbent.generation + 1,
        status=STATUS_CHALLENGER,
        adversarial=True,
    )


def compare_evaluators(
    *,
    incumbent: EvaluatorSpec,
    challenger: EvaluatorSpec,
    incumbent_detection_score: float,
    challenger_detection_score: float,
    trusted_anchor_score: float,
    minimum_anchor_score: float = 0.90,
    minimum_margin: float = 0.01,
) -> EvaluatorMatch:
    """Judge-vs-judge competition with non-evolving anchor authority."""

    if not 0.0 <= trusted_anchor_score <= 1.0:
        raise ValueError(
            "trusted anchor score must be in [0, 1]"
        )

    if trusted_anchor_score < minimum_anchor_score:
        return EvaluatorMatch(
            incumbent_id=incumbent.evaluator_id,
            challenger_id=challenger.evaluator_id,
            incumbent_detection_score=float(
                incumbent_detection_score
            ),
            challenger_detection_score=float(
                challenger_detection_score
            ),
            anchor_score=float(
                trusted_anchor_score
            ),
            challenger_wins=False,
            reason="held-out anchor gate failed",
        )

    margin = (
        float(challenger_detection_score)
        - float(incumbent_detection_score)
    )

    wins = margin >= minimum_margin

    return EvaluatorMatch(
        incumbent_id=incumbent.evaluator_id,
        challenger_id=challenger.evaluator_id,
        incumbent_detection_score=float(
            incumbent_detection_score
        ),
        challenger_detection_score=float(
            challenger_detection_score
        ),
        anchor_score=float(
            trusted_anchor_score
        ),
        challenger_wins=wins,
        reason=(
            "challenger beats incumbent and passes anchor"
            if wins
            else "challenger did not beat incumbent margin"
        ),
    )


def promote_at_epoch_boundary(
    state: RedQueenState,
    *,
    challenger_id: str,
    match: EvaluatorMatch,
) -> PromotionDecision:
    """Activate a winning challenger only when starting a new epoch."""

    challenger = state.challengers.get(
        challenger_id
    )

    if challenger is None:
        return PromotionDecision(
            accepted=False,
            evaluator_id=challenger_id,
            previous_active_id=state.active.evaluator_id,
            epoch=state.epoch,
            reason="unknown challenger",
        )

    if not match.challenger_wins:
        state.rejected[
            challenger_id
        ] = EvaluatorSpec(
            **{
                **asdict(challenger),
                "status": STATUS_REJECTED,
            }
        )

        state.challengers.pop(
            challenger_id,
            None,
        )

        return PromotionDecision(
            accepted=False,
            evaluator_id=challenger_id,
            previous_active_id=state.active.evaluator_id,
            epoch=state.epoch,
            reason=match.reason,
        )

    previous = state.active

    state.retired[
        previous.evaluator_id
    ] = EvaluatorSpec(
        **{
            **asdict(previous),
            "status": STATUS_RETIRED,
        }
    )

    state.epoch += 1

    state.active = EvaluatorSpec(
        **{
            **asdict(challenger),
            "status": STATUS_ACTIVE,
        }
    )

    state.challengers.pop(
        challenger_id,
        None,
    )

    return PromotionDecision(
        accepted=True,
        evaluator_id=state.active.evaluator_id,
        previous_active_id=previous.evaluator_id,
        epoch=state.epoch,
        reason="promoted at epoch boundary",
    )


def selectively_invalidate_utility(
    state: RedQueenState,
    *,
    evaluator_identity: str,
) -> int:
    """Invalidate only utility derived from a superseded/bad evaluator."""

    return state.ledger.invalidate_evaluator(
        evaluator_identity
    )


def coevolution_round(
    state: RedQueenState,
    *,
    candidate_id: str,
    observed_failures: Sequence[str],
    challenger_id: str,
    incumbent_detection_score: float,
    challenger_detection_score: float,
    trusted_anchor_score: float,
) -> PromotionDecision:
    """One bounded agent/evaluator co-evolution round."""

    challenger = build_adversarial_challenger(
        incumbent=state.active,
        observed_failures=observed_failures,
        evaluator_id=challenger_id,
    )

    state.register_challenger(
        challenger
    )

    state.record_outcome(
        candidate_id=candidate_id,
        evaluator=state.active,
        score=incumbent_detection_score,
        passed=incumbent_detection_score >= 0.5,
        evidence=(
            "incumbent evaluator assessment",
        ),
    )

    state.record_outcome(
        candidate_id=candidate_id,
        evaluator=challenger,
        score=challenger_detection_score,
        passed=challenger_detection_score >= 0.5,
        evidence=(
            "challenger evaluator assessment",
        ),
    )

    match = compare_evaluators(
        incumbent=state.active,
        challenger=challenger,
        incumbent_detection_score=incumbent_detection_score,
        challenger_detection_score=challenger_detection_score,
        trusted_anchor_score=trusted_anchor_score,
    )

    previous_identity = (
        state.active.identity()
    )

    decision = promote_at_epoch_boundary(
        state,
        challenger_id=challenger_id,
        match=match,
    )

    if decision.accepted:
        selectively_invalidate_utility(
            state,
            evaluator_identity=previous_identity,
        )

    return decision


def run_bounded_red_queen(
    state: RedQueenState,
    *,
    candidate_id: str,
    failure_batches: Iterable[Sequence[str]],
    scores: Iterable[
        tuple[float, float, float]
    ],
    max_epochs: int = 8,
) -> tuple[PromotionDecision, ...]:
    """Repeated bounded Red Queen rounds.

    Deliberately bounded. Sophyane may schedule another bounded run later,
    but no single invocation is allowed to recurse forever.
    """

    decisions: list[
        PromotionDecision
    ] = []

    for index, (
        failures,
        score_triplet,
    ) in enumerate(
        zip(
            failure_batches,
            scores,
        ),
        start=1,
    ):
        if index > max_epochs:
            break

        incumbent_score, challenger_score, anchor_score = (
            score_triplet
        )

        challenger_id = (
            f"{state.active.evaluator_id}"
            f"-challenger-e{state.epoch + 1}"
        )

        decisions.append(
            coevolution_round(
                state,
                candidate_id=candidate_id,
                observed_failures=failures,
                challenger_id=challenger_id,
                incumbent_detection_score=incumbent_score,
                challenger_detection_score=challenger_score,
                trusted_anchor_score=anchor_score,
            )
        )

    return tuple(
        decisions
    )
