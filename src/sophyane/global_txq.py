"""Global T/Q resource governor for all five Sophyane modes.

This module does not acquire execution, mutation, provider, verification,
promotion, or source-selection authority.

Authority contract
------------------
Mode 1
    Autonomous routing/execution under its existing authority.

Mode 2
    SLI Graph authority. No LLM authority is introduced.

Mode 3
    Local bounded operations worker. Existing ``mode3_meta_rsi`` remains
    authoritative for learned Mode-3 TXQ policy.

Mode 4
    External intelligence / NIFDU authority for bounded RSI change selection
    and final review. Global TXQ may bound latency and context, but never
    converts Mode 4 into an execution worker.

Mode 5
    Learning authority remains with the existing learning subsystem.

The global governor coordinates resources. It never establishes truth:
deterministic verification, held-out evaluation, and existing acceptance
gates remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ModeId = Literal[1, 2, 3, 4, 5]


@dataclass(frozen=True)
class VerifiedHistoryEvidence:
    checked: bool = False
    verified_history_count: int = 0
    verified_success_count: int = 0
    matching_capability_successes: int = 0
    matching_provider_successes: int = 0
    matching_repository_successes: int = 0
    recent_verified_reward: float = 0.0
    historical_confidence: float = 0.0
    influenced: bool = False


@dataclass(frozen=True)
class GlobalTxqPolicy:
    mode: ModeId
    family: str
    difficulty: int
    wall_time_budget_sec: int
    context_budget_chars: int
    max_parallel_readonly: int
    max_speculative_loops: int
    speculative_timeout_sec: int
    speculative_max_tokens: int
    quality_target: float
    allow_llm: bool
    allow_speculative_readonly: bool
    allow_speculative_mutation: bool
    rationale: tuple[str, ...]
    verified_history: VerifiedHistoryEvidence = field(default_factory=VerifiedHistoryEvidence)


def _clamp_int(
    value: int,
    low: int,
    high: int,
) -> int:
    return max(
        low,
        min(
            high,
            int(value),
        ),
    )


def _clamp_float(
    value: float,
    low: float,
    high: float,
) -> float:
    return max(
        low,
        min(
            high,
            float(value),
        ),
    )


def _base_difficulty(
    objective: str,
) -> int:
    text = str(
        objective
        or ""
    ).casefold()

    score = 1

    medium = (
        "test",
        "repair",
        "debug",
        "browser",
        "provider",
        "repository",
        "api",
        "multiple",
    )

    hard = (
        "architecture",
        "recursive",
        "evolution",
        "migration",
        "concurrency",
        "race",
        "distributed",
        "held-out",
        "held_out",
    )

    score += min(
        2,
        sum(
            token in text
            for token in medium
        ),
    )

    score += min(
        2,
        sum(
            token in text
            for token in hard
        ),
    )

    return _clamp_int(
        score,
        1,
        5,
    )


# SOPHYANE_GLOBAL_TXQ_ADAPTIVE_SPECULATION_V4
def adaptive_speculative_timeout_sec(
    predicted_mode4_latency_sec: float = 0.0,
) -> int:
    """Return a short speculative deadline that cannot dominate Mode 4.

    A cold run assumes approximately four seconds for canonical browser
    Mode-4.  Speculation receives only 75 percent of that estimate and
    remains strictly clamped to a 3-8 second envelope.
    """

    predicted = float(
        predicted_mode4_latency_sec
        or 0.0
    )

    if predicted <= 0.0:
        predicted = 4.0

    proposed = int(
        round(
            predicted
            * 0.75
        )
    )

    return _clamp_int(
        proposed,
        3,
        8,
    )


def _verified_history_evidence(
    *,
    objective: str,
    objective_hash: str | None,
    repository_identity: str | None,
    capability_class: str | None,
    provider_identity: str | None,
    limit: int,
) -> VerifiedHistoryEvidence:
    try:
        from sophyane.sli_learner import read_verified_history

        records = read_verified_history(
            request=objective,
            objective_hash=objective_hash,
            repository_identity=repository_identity,
            capability_class=capability_class,
            provider_identity=provider_identity,
            limit=limit,
        )
    except Exception:
        return VerifiedHistoryEvidence()

    repository = str(repository_identity or "").casefold()
    capability = str(capability_class or "").casefold()
    provider = str(provider_identity or "").casefold()
    repo_matches = sum(
        bool(repository)
        and str(item.get("repository_identity") or "").casefold() == repository
        for item in records
    )
    capability_matches = sum(
        bool(capability)
        and str(item.get("capability_class") or "").casefold() == capability
        for item in records
    )
    provider_matches = sum(
        bool(provider)
        and str(item.get("provider_identity") or "").casefold() == provider
        for item in records
    )
    rewards = [float(item.get("reward") or 0.0) for item in records]
    influenced = bool(records)
    confidence = min(1.0, (len(records) / max(1, limit)) * 0.5)
    if influenced:
        confidence = min(1.0, confidence + 0.25)
    return VerifiedHistoryEvidence(
        checked=True,
        verified_history_count=len(records),
        verified_success_count=len(records),
        matching_capability_successes=capability_matches,
        matching_provider_successes=provider_matches,
        matching_repository_successes=repo_matches,
        recent_verified_reward=(sum(rewards) / len(rewards)) if rewards else 0.0,
        historical_confidence=confidence,
        influenced=influenced,
    )


def choose_global_txq_policy(
    mode: int,
    objective: str,
    *,
    observed_latency_sec: float = 0.0,
    objective_hash: str | None = None,
    repository_identity: str | None = None,
    capability_class: str | None = None,
    provider_identity: str | None = None,
    history_limit: int = 8,
) -> GlobalTxqPolicy:
    """Return one resource policy without changing mode authority."""

    if int(mode) not in {
        1,
        2,
        3,
        4,
        5,
    }:
        raise ValueError(
            "Sophyane mode must be between 1 and 5"
        )

    selected: ModeId = int(mode)  # type: ignore[assignment]

    history = _verified_history_evidence(
        objective=objective,
        objective_hash=objective_hash,
        repository_identity=repository_identity,
        capability_class=capability_class,
        provider_identity=provider_identity,
        limit=history_limit,
    )

    difficulty = _base_difficulty(
        objective
    )

    latency = max(
        0.0,
        float(
            observed_latency_sec
            or 0.0
        ),
    )

    rationale = [
        f"mode={selected}",
        f"difficulty={difficulty}",
    ]

    #
    # Global defaults are deliberately conservative.
    #
    wall_time = (
        30
        + difficulty * 20
    )

    context = (
        5000
        + difficulty * 1800
    )

    parallel = 1
    speculative_loops = 0

    speculative_timeout = adaptive_speculative_timeout_sec(
        observed_latency_sec
    )

    speculative_max_tokens = 256
    quality = (
        0.72
        + difficulty * 0.045
    )

    allow_llm = selected in {
        1,
        3,
        4,
    }

    allow_readonly = False

    #
    # Mode 1: autonomous/race runtime.
    #
    if selected == 1:
        wall_time += 20
        parallel = 3
        rationale.append(
            "mode1_race"
        )

    #
    # Mode 2: deterministic SLI Graph.
    #
    elif selected == 2:
        allow_llm = False
        wall_time = min(
            wall_time,
            60,
        )
        context = min(
            context,
            9000,
        )
        parallel = 2
        rationale.append(
            "mode2_sli_no_llm"
        )

    #
    # Mode 3 delegates learned policy to mode3_meta_rsi.
    #
    elif selected == 3:
        try:
            from sophyane.mode3_meta_rsi import (
                choose_txq_policy,
            )

            child = choose_txq_policy(
                objective
            )

            difficulty = int(
                child.difficulty
            )

            wall_time = int(
                child.wall_time_budget_sec
            )

            context = int(
                child.context_budget_chars
            )

            quality = float(
                child.quality_target
            )

            rationale.append(
                "mode3_existing_txq"
            )

        except Exception as error:
            rationale.append(
                "mode3_txq_fallback="
                + type(error).__name__
            )

        #
        # Mode 3 may prepare while another authority is waiting,
        # but preparation is explicitly read-only.
        #
        allow_readonly = True
        parallel = 2
        # SOPHYANE_GLOBAL_TXQ_MODE4_SPECULATION_LOOP_V4
        #
        # One short inference is enough to overlap the remote wait.
        # Multiple serial speculative calls can outlive a fast Mode-4 turn
        # and therefore extend the critical path.
        speculative_loops = 1

    #
    # Mode 4: expensive remote/API/browser intelligence.
    #
    elif selected == 4:
        #
        # Spend context to reduce extra round trips, but keep prompts bounded.
        #
        context = _clamp_int(
            7000
            + difficulty * 2600,
            7000,
            18000,
        )

        #
        # Browser/API latency justifies a larger deadline, not unbounded wait.
        #
        wall_time = _clamp_int(
            45
            + difficulty * 30
            + int(
                latency * 1.35
            ),
            60,
            240,
        )

        quality = max(
            quality,
            0.88,
        )

        allow_readonly = True
        parallel = 2

        # SOPHYANE_GLOBAL_TXQ_MODE4_SPECULATION_LOOP_V4
        #
        # Canonical Mode-4 browser review commonly returns within only
        # a few seconds. Multiple serial speculative generations can
        # therefore extend the critical path after Mode 4 has returned.
        #
        # Permit exactly one bounded read-only speculative generation.
        # Global TXQ separately controls its adaptive deadline and token
        # budget. This does not change Mode-4 source-selection authority.
        speculative_loops = 1


        # SOPHYANE_GLOBAL_TXQ_SPECULATIVE_EVIDENCE_TOKENS_V5
        #
        # Speculation returns only a compact repository observation.
        # It does not materialize a candidate file and therefore does not
        # need the authorized coding completion envelope.
        speculative_max_tokens = 96

        rationale.extend(
            (
                "mode4_remote_latency",
                "mode4_context_roundtrip_reduction",
            )
        )

    #
    # Mode 5: learning can do more read-side work but cannot inherit
    # source promotion authority through TXQ.
    #
    elif selected == 5:
        allow_llm = False
        allow_readonly = True
        wall_time += 45
        parallel = 2
        speculative_loops = _clamp_int(
            difficulty,
            1,
            3,
        )
        rationale.append(
            "mode5_learning"
        )

    if history.checked:
        rationale.append(
            "verified_history_checked"
            + f"={history.verified_history_count}"
        )
        if history.influenced:
            rationale.append("verified_history_influenced")
            quality = min(0.99, quality + 0.02 * history.historical_confidence)

    return GlobalTxqPolicy(
        mode=selected,
        family=(
            "sophyane-mode-"
            + str(selected)
        ),
        difficulty=_clamp_int(
            difficulty,
            1,
            5,
        ),
        wall_time_budget_sec=_clamp_int(
            wall_time,
            10,
            300,
        ),
        context_budget_chars=_clamp_int(
            context,
            2000,
            24000,
        ),
        max_parallel_readonly=_clamp_int(
            parallel,
            1,
            4,
        ),
        max_speculative_loops=_clamp_int(
            speculative_loops,
            0,
            6,
        ),
        speculative_timeout_sec=_clamp_int(
            speculative_timeout,
            3,
            8,
        ),
        speculative_max_tokens=_clamp_int(
            speculative_max_tokens,
            64,
            256,
        ),
        quality_target=_clamp_float(
            quality,
            0.50,
            0.99,
        ),
        allow_llm=bool(
            allow_llm
        ),
        allow_speculative_readonly=bool(
            allow_readonly
        ),
        #
        # Core authority invariant:
        #
        # speculative preparation must NEVER mutate source.
        #
        allow_speculative_mutation=False,
        rationale=tuple(
            rationale
        ),
        verified_history=history,
    )


def render_global_txq_context(
    policy: GlobalTxqPolicy,
) -> str:
    return "\n".join(
        (
            "SOPHYANE_GLOBAL_TXQ",
            f"mode={policy.mode}",
            f"difficulty={policy.difficulty}",
            (
                "wall_time_budget_sec="
                f"{policy.wall_time_budget_sec}"
            ),
            (
                "context_budget_chars="
                f"{policy.context_budget_chars}"
            ),
            (
                "max_parallel_readonly="
                f"{policy.max_parallel_readonly}"
            ),
            (
                "max_speculative_loops="
                f"{policy.max_speculative_loops}"
            ),
            (
                "speculative_timeout_sec="
                f"{policy.speculative_timeout_sec}"
            ),
            (
                "speculative_max_tokens="
                f"{policy.speculative_max_tokens}"
            ),
            (
                "quality_target="
                f"{policy.quality_target:.3f}"
            ),
            (
                "allow_speculative_readonly="
                f"{int(policy.allow_speculative_readonly)}"
            ),
            "allow_speculative_mutation=0",
            (
                "verified_history_checked="
                + str(int(policy.verified_history.checked))
            ),
            (
                "verified_history_hits="
                + str(policy.verified_history.verified_history_count)
            ),
            (
                "verified_history_influenced="
                + str(int(policy.verified_history.influenced))
            ),
            "END_SOPHYANE_GLOBAL_TXQ",
        )
    )


def mode4_txq_context(
    objective: str,
    *,
    observed_latency_sec: float = 0.0,
) -> tuple[GlobalTxqPolicy, str]:
    policy = choose_global_txq_policy(
        4,
        objective,
        observed_latency_sec=(
            observed_latency_sec
        ),
    )

    return (
        policy,
        render_global_txq_context(
            policy
        ),
    )


def readonly_speculation_contract(
    objective: str,
    *,
    maximum_items: int = 8,
) -> str:
    """Return the only legal pre-Mode-4 speculative worker contract."""

    limit = _clamp_int(
        maximum_items,
        1,
        16,
    )

    return (
        "MODE3_READ_ONLY_SPECULATIVE_PREPARATION\n"
        "Mode 4 has NOT selected a source change yet.\n"
        "Do not choose an implementation.\n"
        "Do not write, edit, append, delete, rename or patch files.\n"
        "Do not execute mutation commands.\n"
        "Do not stage, commit, push, merge, rebase or reset.\n"
        "You may only identify repository evidence useful after "
        "Mode 4 issues its bounded instruction:\n"
        "- relevant files/symbols\n"
        "- existing tests\n"
        "- deterministic verification commands\n"
        "- failure evidence\n"
        "- reusable context summaries\n"
        f"Return at most {limit} concise evidence items.\n"
        "OBJECTIVE:\n"
        + str(
            objective
        ).strip()
        + "\n"
        "END_MODE3_READ_ONLY_SPECULATIVE_PREPARATION"
    )


__all__ = [
    "adaptive_speculative_timeout_sec",
    "GlobalTxqPolicy",
    "VerifiedHistoryEvidence",
    "choose_global_txq_policy",
    "mode4_txq_context",
    "readonly_speculation_contract",
    "render_global_txq_context",
]
