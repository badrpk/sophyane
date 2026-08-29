"""Mode-3 Meta-RSI TXQ policy.

Purpose
-------
Improve how Sophyane extracts useful work from a weak local GGUF model.

The local model remains the candidate worker.
Sophyane remains the execution and verification authority.
NIFDU may provide supervisory recommendations.

This module deliberately has:
- no Git promotion authority;
- no shell execution authority;
- no provider creation authority;
- no cloud API authority;
- no unbounded recursive loop.

TXQ means:

T: bounded wall-time / generation effort.
D: estimated task difficulty.
Q: required verification quality.

The learned policy changes prompt/decomposition/verification guidance,
not truth. Verification remains external to this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any


STATE_VERSION = 1

DEFAULT_MAX_EPISODE_ITERATIONS = 4
HARD_MAX_EPISODE_ITERATIONS = 12

DEFAULT_STATE_PATH = (
    Path.home()
    / ".local"
    / "share"
    / "sophyane"
    / "mode3-meta-rsi"
    / "txq-state.json"
)


@dataclass(frozen=True)
class TxqPolicy:
    difficulty: int
    quality_target: float
    wall_time_budget_sec: int
    generation_budget: int
    context_budget_chars: int
    decomposition_depth: int
    verification_depth: int
    retry_budget: int
    temperature_hint: float
    rationale: tuple[str, ...] = ()


@dataclass(frozen=True)
class TxqObservation:
    identity: str
    task_family: str
    difficulty: int
    quality_target: float
    elapsed_sec: float
    verification_ok: bool
    held_out_attempted: bool
    held_out_not_regressed: bool
    nifdu_status: str
    retry_index: int
    candidate_changed: bool


@dataclass(frozen=True)
class MetaProposal:
    target: str
    hypothesis: str
    proposed_change: str
    expected_time_delta: float = 0.0
    expected_quality_delta: float = 0.0
    expected_success_delta: float = 0.0
    risk: str = "low"
    rollback_condition: str = ""


def _bounded_int(
    value: Any,
    minimum: int,
    maximum: int,
    default: int,
) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default

    return max(
        minimum,
        min(
            maximum,
            parsed,
        ),
    )


def _bounded_float(
    value: Any,
    minimum: float,
    maximum: float,
    default: float,
) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default

    return max(
        minimum,
        min(
            maximum,
            parsed,
        ),
    )


def estimate_task_family(
    objective: str,
) -> str:
    text = str(
        objective
        or ""
    ).casefold()

    families = (
        (
            "testing",
            (
                "pytest",
                "test",
                "regression",
                "failing",
                "failure",
            ),
        ),
        (
            "debugging",
            (
                "debug",
                "traceback",
                "bug",
                "repair",
                "fix",
            ),
        ),
        (
            "filesystem",
            (
                "file",
                "directory",
                "path",
                "rename",
                "create",
            ),
        ),
        (
            "web",
            (
                "html",
                "website",
                "browser",
                "javascript",
                "css",
            ),
        ),
        (
            "backend",
            (
                "api",
                "fastapi",
                "redis",
                "database",
                "sql",
                "middleware",
            ),
        ),
        (
            "python",
            (
                "python",
                ".py",
                "function",
                "class",
                "module",
            ),
        ),
    )

    for family, signals in families:
        if any(
            signal in text
            for signal in signals
        ):
            return family

    return "general"


def estimate_difficulty(
    objective: str,
    *,
    evolution_context: str = "",
    environment_profile=None,
) -> int:
    text = (
        str(
            objective
            or ""
        )
        + "\n"
        + str(
            evolution_context
            or ""
        )
    ).casefold()

    score = 1

    medium = (
        "implement",
        "repair",
        "debug",
        "multiple",
        "integration",
        "architecture",
        "repository",
        "regression",
        "async",
        "database",
        "redis",
        "api",
    )

    hard = (
        "race condition",
        "concurrency",
        "distributed",
        "transaction",
        "migration",
        "security",
        "recursive",
        "evolution",
        "held-out",
        "cross-domain",
        "idempotency",
        "saga",
    )

    score += min(
        2,
        sum(
            1
            for token in medium
            if token in text
        ),
    )

    score += min(
        2,
        sum(
            1
            for token in hard
            if token in text
        ),
    )

    if len(text) > 3000:
        score += 1

    # SOPHYANE_TXQ_ENVIRONMENT_DIFFICULTY_V1
    #
    # Environment complexity is empirical task difficulty rather than
    # additional prompt length. Import lazily so Mode-3 TXQ can still be used
    # independently of the environment subsystem.
    #
    if environment_profile is not None:
        try:
            environment_score = float(
                environment_profile.normalized_score()
            )
        except Exception:
            environment_score = 0.0

        if environment_score >= 0.75:
            score += 2
        elif environment_score >= 0.35:
            score += 1

    return max(
        1,
        min(
            5,
            score,
        ),
    )


def _empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "families": {},
        "observations": {},
        "accepted_meta_proposals": [],
    }


def load_state(
    path: Path | None = None,
) -> dict[str, Any]:
    target = (
        Path(path)
        if path is not None
        else DEFAULT_STATE_PATH
    )

    try:
        raw = json.loads(
            target.read_text(
                encoding="utf-8",
            )
        )
    except Exception:
        return _empty_state()

    if not isinstance(
        raw,
        dict,
    ):
        return _empty_state()

    if int(
        raw.get(
            "version",
            0,
        )
        or 0
    ) != STATE_VERSION:
        return _empty_state()

    raw.setdefault(
        "families",
        {},
    )

    raw.setdefault(
        "observations",
        {},
    )

    raw.setdefault(
        "accepted_meta_proposals",
        [],
    )

    return raw


def save_state(
    state: dict[str, Any],
    path: Path | None = None,
) -> Path:
    target = (
        Path(path)
        if path is not None
        else DEFAULT_STATE_PATH
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
            state,
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


def choose_txq_policy(
    objective: str,
    *,
    evolution_context: str = "",
    state: dict[str, Any] | None = None,
    environment_profile=None,
) -> TxqPolicy:
    active = (
        state
        if state is not None
        else load_state()
    )

    family = estimate_task_family(
        objective
    )

    difficulty = estimate_difficulty(
        objective,
        evolution_context=evolution_context,
        environment_profile=environment_profile,
    )

    family_state = (
        active.get(
            "families",
            {},
        )
        .get(
            family,
            {},
        )
    )

    attempts = _bounded_int(
        family_state.get(
            "attempts",
            0,
        ),
        0,
        1_000_000,
        0,
    )

    success_rate = _bounded_float(
        family_state.get(
            "success_rate",
            0.5,
        ),
        0.0,
        1.0,
        0.5,
    )

    mean_elapsed = _bounded_float(
        family_state.get(
            "mean_elapsed_sec",
            0.0,
        ),
        0.0,
        3600.0,
        0.0,
    )

    rationale: list[str] = [
        f"family={family}",
        f"difficulty={difficulty}",
    ]

    #
    # Time
    #
    wall_time = (
        45
        + (
            difficulty
            * 35
        )
    )

    if mean_elapsed > 0:
        wall_time = max(
            wall_time,
            int(
                mean_elapsed
                * 1.35
            )
            + 10,
        )

        rationale.append(
            "historical_latency"
        )

    #
    # Quality
    #
    quality_target = (
        0.70
        + (
            difficulty
            * 0.045
        )
    )

    if (
        attempts >= 3
        and success_rate < 0.60
    ):
        quality_target += 0.04

        rationale.append(
            "low_historical_success"
        )

    quality_target = min(
        0.96,
        quality_target,
    )

    #
    # Weak-model strategy:
    # difficult tasks get more decomposition/context rather
    # than one enormous monolithic generation.
    #
    decomposition_depth = (
        1
        if difficulty <= 2
        else (
            2
            if difficulty <= 4
            else 3
        )
    )

    retry_budget = (
        0
        if difficulty == 1
        else (
            1
            if difficulty <= 3
            else 2
        )
    )

    verification_depth = (
        1
        if difficulty <= 2
        else (
            2
            if difficulty <= 4
            else 3
        )
    )

    generation_budget = min(
        3072,
        700
        + (
            difficulty
            * 350
        ),
    )

    context_budget_chars = min(
        24000,
        5000
        + (
            difficulty
            * 3000
        ),
    )

    temperature_hint = (
        0.10
        if difficulty >= 4
        else 0.20
    )

    return TxqPolicy(
        difficulty=difficulty,
        quality_target=round(
            quality_target,
            3,
        ),
        wall_time_budget_sec=max(
            60,
            min(
                600,
                wall_time,
            ),
        ),
        generation_budget=generation_budget,
        context_budget_chars=context_budget_chars,
        decomposition_depth=decomposition_depth,
        verification_depth=verification_depth,
        retry_budget=retry_budget,
        temperature_hint=temperature_hint,
        rationale=tuple(
            rationale
        ),
    )


def apply_txq_to_instruction(
    instruction: str,
    *,
    objective: str,
    evolution_context: str = "",
    state: dict[str, Any] | None = None,
    environment_profile=None,
) -> tuple[str, TxqPolicy]:
    policy = choose_txq_policy(
        objective,
        evolution_context=evolution_context,
        state=state,
        environment_profile=environment_profile,
    )

    original = str(
        instruction
        or ""
    ).strip()

    txq = (
        "\n\n"
        "MODE3_TXQ_POLICY\n"
        f"difficulty={policy.difficulty}\n"
        f"quality_target={policy.quality_target:.3f}\n"
        f"wall_time_budget_sec={policy.wall_time_budget_sec}\n"
        f"generation_budget={policy.generation_budget}\n"
        f"context_budget_chars={policy.context_budget_chars}\n"
        f"decomposition_depth={policy.decomposition_depth}\n"
        f"verification_depth={policy.verification_depth}\n"
        f"retry_budget={policy.retry_budget}\n"
        f"temperature_hint={policy.temperature_hint:.2f}\n"
        "worker_policy=prefer small verifiable steps over one large guess\n"
        "truth_policy=do not claim success without deterministic evidence\n"
        "END_MODE3_TXQ_POLICY"
    )

    return (
        original
        + txq,
        policy,
    )


def observation_identity(
    *,
    objective: str,
    candidate_diff: str,
    verification_commands: tuple[str, ...],
) -> str:
    payload = {
        "objective": str(
            objective
            or ""
        ).strip(),
        "candidate_diff": str(
            candidate_diff
            or ""
        ),
        "verification_commands": [
            str(item)
            for item in verification_commands
        ],
    }

    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )
    ).hexdigest()[:24]

    return (
        "mode3-txq-"
        + digest
    )


def record_observation(
    *,
    objective: str,
    policy: TxqPolicy,
    candidate_diff: str,
    verification_commands: tuple[str, ...],
    elapsed_sec: float,
    verification_ok: bool,
    held_out_attempted: bool,
    held_out_not_regressed: bool,
    nifdu_status: str,
    retry_index: int,
    state_path: Path | None = None,
) -> tuple[TxqObservation, bool]:
    state = load_state(
        state_path
    )

    identity = observation_identity(
        objective=objective,
        candidate_diff=candidate_diff,
        verification_commands=verification_commands,
    )

    observations = state.setdefault(
        "observations",
        {},
    )

    if identity in observations:
        stored = observations[
            identity
        ]

        return (
            TxqObservation(
                identity=identity,
                task_family=str(
                    stored.get(
                        "task_family",
                        estimate_task_family(
                            objective
                        ),
                    )
                ),
                difficulty=int(
                    stored.get(
                        "difficulty",
                        policy.difficulty,
                    )
                ),
                quality_target=float(
                    stored.get(
                        "quality_target",
                        policy.quality_target,
                    )
                ),
                elapsed_sec=float(
                    stored.get(
                        "elapsed_sec",
                        elapsed_sec,
                    )
                ),
                verification_ok=bool(
                    stored.get(
                        "verification_ok",
                        False,
                    )
                ),
                held_out_attempted=bool(
                    stored.get(
                        "held_out_attempted",
                        False,
                    )
                ),
                held_out_not_regressed=bool(
                    stored.get(
                        "held_out_not_regressed",
                        True,
                    )
                ),
                nifdu_status=str(
                    stored.get(
                        "nifdu_status",
                        "",
                    )
                ),
                retry_index=int(
                    stored.get(
                        "retry_index",
                        retry_index,
                    )
                ),
                candidate_changed=False,
            ),
            False,
        )

    family = estimate_task_family(
        objective
    )

    success = bool(
        verification_ok
        and (
            not held_out_attempted
            or held_out_not_regressed
        )
    )

    observation = TxqObservation(
        identity=identity,
        task_family=family,
        difficulty=policy.difficulty,
        quality_target=policy.quality_target,
        elapsed_sec=max(
            0.0,
            float(
                elapsed_sec
            ),
        ),
        verification_ok=bool(
            verification_ok
        ),
        held_out_attempted=bool(
            held_out_attempted
        ),
        held_out_not_regressed=bool(
            held_out_not_regressed
        ),
        nifdu_status=str(
            nifdu_status
            or ""
        ).upper(),
        retry_index=max(
            0,
            int(
                retry_index
            ),
        ),
        candidate_changed=True,
    )

    observations[
        identity
    ] = asdict(
        observation
    )

    families = state.setdefault(
        "families",
        {},
    )

    item = families.setdefault(
        family,
        {
            "attempts": 0,
            "successes": 0,
            "success_rate": 0.5,
            "mean_elapsed_sec": 0.0,
        },
    )

    attempts_before = int(
        item.get(
            "attempts",
            0,
        )
    )

    successes_before = int(
        item.get(
            "successes",
            0,
        )
    )

    mean_before = float(
        item.get(
            "mean_elapsed_sec",
            0.0,
        )
    )

    attempts_after = (
        attempts_before
        + 1
    )

    successes_after = (
        successes_before
        + (
            1
            if success
            else 0
        )
    )

    mean_after = (
        (
            mean_before
            * attempts_before
        )
        + observation.elapsed_sec
    ) / attempts_after

    item.update(
        {
            "attempts": attempts_after,
            "successes": successes_after,
            "success_rate": (
                successes_after
                / attempts_after
            ),
            "mean_elapsed_sec": mean_after,
            "last_identity": identity,
        }
    )

    save_state(
        state,
        state_path,
    )

    return (
        observation,
        True,
    )


def build_nifdu_meta_context(
    *,
    objective: str,
    policy: TxqPolicy,
    elapsed_sec: float,
    verification_ok: bool,
    held_out_attempted: bool,
    held_out_not_regressed: bool,
    failure: str,
) -> str:
    payload = {
        "objective": str(
            objective
            or ""
        ),
        "txq": asdict(
            policy
        ),
        "measured": {
            "elapsed_sec": round(
                max(
                    0.0,
                    float(
                        elapsed_sec
                    ),
                ),
                3,
            ),
            "verification_ok": bool(
                verification_ok
            ),
            "held_out_attempted": bool(
                held_out_attempted
            ),
            "held_out_not_regressed": bool(
                held_out_not_regressed
            ),
            "failure": str(
                failure
                or ""
            )[:4000],
        },
    }

    return (
        "MODE3_META_RSI_SUPERVISION\n"
        "Use the deterministic evidence above as truth.\n"
        "Judge whether Sophyane's current weak-model strategy can improve.\n"
        "Do not replace deterministic verification.\n"
        "Do not request commit/push/merge/rebase.\n"
        "You may optionally append exactly one block:\n"
        "META_RSI_JSON: "
        '{"target":"prompt_policy|routing|context|validator|source",'
        '"hypothesis":"...",'
        '"proposed_change":"...",'
        '"expected_time_delta":0.0,'
        '"expected_quality_delta":0.0,'
        '"expected_success_delta":0.0,'
        '"risk":"low|medium|high",'
        '"rollback_condition":"..."}\n'
        "CURRENT_META_STATE:\n"
        + json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
        "END_MODE3_META_RSI_SUPERVISION"
    )


_META_PATTERN = re.compile(
    r"META_RSI_JSON:\s*(\{.*\})",
    flags=re.DOTALL,
)


def parse_meta_proposal(
    review_response: str,
) -> MetaProposal | None:
    text = str(
        review_response
        or ""
    )

    match = _META_PATTERN.search(
        text
    )

    if not match:
        return None

    raw = match.group(
        1
    ).strip()

    #
    # Avoid greedily consuming unrelated trailing prose.
    #
    decoder = json.JSONDecoder()

    try:
        data, _ = decoder.raw_decode(
            raw
        )
    except Exception:
        return None

    if not isinstance(
        data,
        dict,
    ):
        return None

    target = str(
        data.get(
            "target",
            "",
        )
    ).strip()

    if target not in {
        "prompt_policy",
        "routing",
        "context",
        "validator",
        "source",
    }:
        return None

    hypothesis = str(
        data.get(
            "hypothesis",
            "",
        )
    ).strip()

    proposed_change = str(
        data.get(
            "proposed_change",
            "",
        )
    ).strip()

    if (
        not hypothesis
        or not proposed_change
    ):
        return None

    risk = str(
        data.get(
            "risk",
            "low",
        )
    ).strip().lower()

    if risk not in {
        "low",
        "medium",
        "high",
    }:
        risk = "high"

    return MetaProposal(
        target=target,
        hypothesis=hypothesis,
        proposed_change=proposed_change,
        expected_time_delta=_bounded_float(
            data.get(
                "expected_time_delta",
                0.0,
            ),
            -1.0,
            1.0,
            0.0,
        ),
        expected_quality_delta=_bounded_float(
            data.get(
                "expected_quality_delta",
                0.0,
            ),
            -1.0,
            1.0,
            0.0,
        ),
        expected_success_delta=_bounded_float(
            data.get(
                "expected_success_delta",
                0.0,
            ),
            -1.0,
            1.0,
            0.0,
        ),
        risk=risk,
        rollback_condition=str(
            data.get(
                "rollback_condition",
                "",
            )
        ).strip(),
    )


def accept_meta_proposal(
    proposal: MetaProposal,
    *,
    deterministic_verification_ok: bool,
    held_out_attempted: bool,
    held_out_not_regressed: bool,
    state_path: Path | None = None,
) -> bool:
    #
    # A NIFDU suggestion is advice only.
    #
    # It can enter the learned-advice ledger only after the actual candidate
    # has passed deterministic verification and any attempted held-out replay.
    #
    if not deterministic_verification_ok:
        return False

    if (
        held_out_attempted
        and not held_out_not_regressed
    ):
        return False

    state = load_state(
        state_path
    )

    ledger = state.setdefault(
        "accepted_meta_proposals",
        [],
    )

    fingerprint = hashlib.sha256(
        json.dumps(
            asdict(
                proposal
            ),
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )
    ).hexdigest()[:24]

    if any(
        str(
            item.get(
                "fingerprint",
                "",
            )
        )
        == fingerprint
        for item in ledger
        if isinstance(
            item,
            dict,
        )
    ):
        return False

    ledger.append(
        {
            "fingerprint": fingerprint,
            "accepted_at_unix": int(
                time.time()
            ),
            **asdict(
                proposal
            ),
        }
    )

    #
    # Keep persistent advisory history bounded.
    #
    if len(
        ledger
    ) > 200:
        del ledger[:-200]

    save_state(
        state,
        state_path,
    )

    return True


def bounded_episode_limit(
    requested: int | None = None,
) -> int:
    if requested is None:
        requested = (
            DEFAULT_MAX_EPISODE_ITERATIONS
        )

    return _bounded_int(
        requested,
        1,
        HARD_MAX_EPISODE_ITERATIONS,
        DEFAULT_MAX_EPISODE_ITERATIONS,
    )


__all__ = [
    "DEFAULT_STATE_PATH",
    "MetaProposal",
    "TxqObservation",
    "TxqPolicy",
    "accept_meta_proposal",
    "apply_txq_to_instruction",
    "bounded_episode_limit",
    "build_nifdu_meta_context",
    "choose_txq_policy",
    "estimate_difficulty",
    "estimate_task_family",
    "load_state",
    "observation_identity",
    "parse_meta_proposal",
    "record_observation",
    "save_state",
]
