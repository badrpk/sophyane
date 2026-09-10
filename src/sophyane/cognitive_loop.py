"""Bounded continuous cognitive control loop for Sophyane.

SOPHYANE_CONTINUOUS_COGNITIVE_LOOP_V1

Pipeline:

    observe
      -> activate sparse memories
      -> form thought
      -> reason
      -> choose bounded task
      -> act
      -> measure reality
      -> verify
      -> record exact episode
      -> consolidate sparse memory
      -> occasionally dream
      -> turn promising dreams into hypotheses
      -> test again

Critical invariants:

1. Session intelligence authority is never changed by this module.
2. Thoughts are context, never authority.
3. Dreams are hypotheses, never evidence.
4. Actions require explicit registered capability handlers.
5. Physical / financial / destructive / replication / self-modification
   actions are blocked unless a separate explicit policy authorizes them.
6. Verification, not model confidence, determines accepted success.
7. Every cycle has bounded work, time and action budgets.
8. Raw cycle evidence is append-only and separate from sparse memory.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import threading
import time
import uuid

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


# ---------------------------------------------------------------------------
# Constants / policy
# ---------------------------------------------------------------------------

LOOP_MARKER = "SOPHYANE_CONTINUOUS_COGNITIVE_LOOP_V1"

SAFE_RISK_CLASSES = {
    "read_only",
    "analysis",
    "simulation",
    "local_test",
    "bounded_software",
}

BLOCKED_RISK_CLASSES = {
    "financial",
    "physical",
    "chemical",
    "biological",
    "weapon",
    "credential",
    "destructive",
    "replication",
    "self_modification",
    "external_publish",
    "external_message",
}

DEFAULT_MAX_CYCLES = 8
DEFAULT_MAX_ACTIONS_PER_CYCLE = 1
DEFAULT_MAX_RUNTIME_SECONDS = 900.0
DEFAULT_DREAM_INTERVAL = 4
DEFAULT_IDLE_SLEEP_SECONDS = 0.0

_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)

_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CognitiveLoopConfig:
    max_cycles: int = DEFAULT_MAX_CYCLES
    max_actions_per_cycle: int = DEFAULT_MAX_ACTIONS_PER_CYCLE
    max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS
    dream_interval: int = DEFAULT_DREAM_INTERVAL
    idle_sleep_seconds: float = DEFAULT_IDLE_SLEEP_SECONDS
    stop_file: str | None = None
    allow_risk_classes: tuple[str, ...] = tuple(
        sorted(SAFE_RISK_CLASSES)
    )


@dataclass
class CognitiveTask:
    task_id: str
    objective: str
    action_kind: str
    payload: dict[str, Any] = field(
        default_factory=dict
    )
    risk_class: str = "analysis"
    rationale: str = ""
    source: str = "reasoning"
    source_dream_id: str | None = None
    bounded: bool = True
    requires_confirmation: bool = False


@dataclass
class ActionResult:
    ok: bool
    status: str
    observation: Any = None
    evidence: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class VerificationResult:
    verified: bool
    accepted: bool
    evidence: Any
    score: float = 0.0
    reason: str = ""


@dataclass
class CognitiveCycleResult:
    cycle_id: str
    objective: str
    observation: Any
    thought: dict[str, Any]
    reasoning: Any
    task: CognitiveTask | None
    action: ActionResult | None
    verification: VerificationResult
    episode: dict[str, Any]
    persistence: dict[str, Any]
    dream: dict[str, Any] | None
    next_hypothesis: dict[str, Any] | None


Observer = Callable[
    [str, Mapping[str, Any]],
    Any,
]

Reasoner = Callable[
    [str, Mapping[str, Any]],
    Any,
]

ActionHandler = Callable[
    [CognitiveTask, Mapping[str, Any]],
    ActionResult | Mapping[str, Any] | Any,
]

Measurer = Callable[
    [
        CognitiveTask,
        ActionResult,
        Mapping[str, Any],
    ],
    Any,
]

Verifier = Callable[
    [
        CognitiveTask,
        ActionResult,
        Any,
        Mapping[str, Any],
    ],
    VerificationResult
    | Mapping[str, Any]
    | bool,
]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _xerus_root() -> Path:
    configured = str(
        os.environ.get(
            "XERUS_HOME",
            "",
        )
        or ""
    ).strip()

    if configured:
        return Path(
            configured
        ).expanduser()

    return (
        Path.home()
        / ".local"
        / "share"
        / "xerus"
    )


def _cycle_journal() -> Path:
    return (
        _xerus_root()
        / "cognitive-cycles.jsonl"
    )


def _canonical_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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


def _append_exact_cycle(
    episode: Mapping[str, Any],
) -> str:
    path = _cycle_journal()

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with _LOCK:
        with path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                _canonical_json(
                    dict(episode)
                )
                + "\n"
            )

    return str(path)


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------

class CognitiveActionRegistry:
    """Explicit capability registry.

    No handler means no execution.

    This intentionally prevents the reasoning model from inventing
    executable authority merely by returning an action name.
    """

    def __init__(self) -> None:
        self._handlers: dict[
            str,
            ActionHandler,
        ] = {}

    def register(
        self,
        action_kind: str,
        handler: ActionHandler,
    ) -> None:
        key = str(
            action_kind
            or ""
        ).strip()

        if not key:
            raise ValueError(
                "action_kind is required"
            )

        if not callable(handler):
            raise TypeError(
                "handler must be callable"
            )

        self._handlers[
            key
        ] = handler

    def supports(
        self,
        action_kind: str,
    ) -> bool:
        return (
            str(
                action_kind
                or ""
            ).strip()
            in self._handlers
        )

    def execute(
        self,
        task: CognitiveTask,
        context: Mapping[str, Any],
    ) -> ActionResult:
        handler = self._handlers.get(
            task.action_kind
        )

        if handler is None:
            return ActionResult(
                ok=False,
                status="capability_unavailable",
                error=(
                    "No explicit action handler registered "
                    f"for {task.action_kind!r}"
                ),
                metadata={
                    "action_kind": task.action_kind,
                    "authority_invented": False,
                },
            )

        try:
            raw = handler(
                task,
                context,
            )

        except Exception as exc:
            return ActionResult(
                ok=False,
                status="action_exception",
                error=(
                    type(exc).__name__
                    + ": "
                    + str(exc)
                ),
            )

        return _coerce_action_result(
            raw
        )


_GLOBAL_ACTIONS = CognitiveActionRegistry()

# SOPHYANE_COGNITIVE_BUILTIN_AUTO_INSTALL_V1
_BUILTIN_ACTIONS_INSTALL_ATTEMPTED = False
_BUILTIN_ACTIONS_INSTALL_ERROR: str | None = None


def _ensure_builtin_actions() -> None:
    """Lazily install Sophyane's safe builtin cognitive actions.

    This is intentionally lazy to avoid import cycles:
    cognitive_actions imports the public registration API from this
    module and registers only explicitly safe handlers.
    """
    global _BUILTIN_ACTIONS_INSTALL_ATTEMPTED
    global _BUILTIN_ACTIONS_INSTALL_ERROR

    if _BUILTIN_ACTIONS_INSTALL_ATTEMPTED:
        return

    _BUILTIN_ACTIONS_INSTALL_ATTEMPTED = True

    try:
        import importlib

        importlib.import_module(
            "sophyane.cognitive_actions"
        )

    except Exception as exc:
        _BUILTIN_ACTIONS_INSTALL_ERROR = (
            type(exc).__name__
            + ": "
            + str(exc)
        )


def register_cognitive_action(
    action_kind: str,
    handler: ActionHandler,
) -> None:
    _GLOBAL_ACTIONS.register(
        action_kind,
        handler,
    )


def cognitive_action_registry() -> CognitiveActionRegistry:
    _ensure_builtin_actions()
    return _GLOBAL_ACTIONS


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _clean_json_text(
    raw: str,
) -> str:
    value = str(
        raw
        or ""
    ).strip()

    match = _JSON_FENCE_RE.match(
        value
    )

    if match:
        value = match.group(1).strip()

    return value


def _parse_jsonish(
    raw: Any,
) -> Any:
    if isinstance(
        raw,
        (
            dict,
            list,
        ),
    ):
        return raw

    if not isinstance(
        raw,
        str,
    ):
        return raw

    value = _clean_json_text(
        raw
    )

    try:
        return json.loads(
            value
        )

    except Exception:
        return raw


def _coerce_action_result(
    raw: Any,
) -> ActionResult:
    if isinstance(
        raw,
        ActionResult,
    ):
        return raw

    if isinstance(
        raw,
        Mapping,
    ):
        return ActionResult(
            ok=bool(
                raw.get(
                    "ok",
                    False,
                )
            ),
            status=str(
                raw.get(
                    "status",
                    "completed",
                )
                or "completed"
            ),
            observation=raw.get(
                "observation"
            ),
            evidence=raw.get(
                "evidence"
            ),
            error=(
                str(
                    raw.get(
                        "error"
                    )
                )
                if raw.get(
                    "error"
                )
                is not None
                else None
            ),
            metadata=dict(
                raw.get(
                    "metadata",
                    {},
                )
                or {}
            ),
        )

    return ActionResult(
        ok=True,
        status="completed",
        observation=raw,
    )


def _coerce_verification(
    raw: Any,
) -> VerificationResult:
    if isinstance(
        raw,
        VerificationResult,
    ):
        return raw

    if isinstance(
        raw,
        bool,
    ):
        return VerificationResult(
            verified=raw,
            accepted=raw,
            evidence={
                "boolean_verifier": raw,
            },
            score=(
                1.0
                if raw
                else 0.0
            ),
            reason=(
                "verified"
                if raw
                else "verification_failed"
            ),
        )

    if isinstance(
        raw,
        Mapping,
    ):
        verified = bool(
            raw.get(
                "verified",
                False,
            )
        )

        accepted = bool(
            raw.get(
                "accepted",
                verified,
            )
        )

        return VerificationResult(
            verified=verified,
            accepted=accepted,
            evidence=raw.get(
                "evidence",
                dict(raw),
            ),
            score=float(
                raw.get(
                    "score",
                    1.0 if verified else 0.0,
                )
                or 0.0
            ),
            reason=str(
                raw.get(
                    "reason",
                    "",
                )
                or ""
            ),
        )

    return VerificationResult(
        verified=False,
        accepted=False,
        evidence={
            "invalid_verifier_result": repr(
                raw
            ),
        },
        score=0.0,
        reason="invalid_verifier_result",
    )


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------

def _authority_snapshot() -> dict[str, Any]:
    try:
        from sophyane.intelligence_authority import (
            current_intelligence_authority,
        )

        authority = (
            current_intelligence_authority()
        )

        if hasattr(
            authority,
            "__dict__",
        ):
            return dict(
                vars(authority)
            )

        return {
            "session_mode": getattr(
                authority,
                "session_mode",
                None,
            ),
            "session_provider": getattr(
                authority,
                "session_provider",
                None,
            ),
            "session_model": getattr(
                authority,
                "session_model",
                None,
            ),
            "local_reasoning_allowed": getattr(
                authority,
                "local_reasoning_allowed",
                None,
            ),
            "provider_switching_allowed": getattr(
                authority,
                "provider_switching_allowed",
                None,
            ),
            "llm_allowed": getattr(
                authority,
                "llm_allowed",
                None,
            ),
        }

    except Exception as exc:
        return {
            "authority_error": (
                type(exc).__name__
                + ": "
                + str(exc)
            ),
            "session_mode": os.environ.get(
                "SOPHYANE_SESSION_MODE"
            ),
            "session_provider": os.environ.get(
                "SOPHYANE_SESSION_PROVIDER"
            ),
            "session_model": os.environ.get(
                "SOPHYANE_SESSION_MODEL"
            ),
        }


# ---------------------------------------------------------------------------
# Cognitive stages
# ---------------------------------------------------------------------------

def observe(
    objective: str,
    *,
    observer: Observer | None,
    context: Mapping[str, Any],
) -> Any:
    """Observe reality through an explicit observer.

    If none is supplied, observation is intentionally minimal and
    deterministic rather than pretending sensors were used.
    """

    if observer is None:
        return {
            "kind": "internal_observation",
            "objective": objective,
            "time": time.time(),
            "external_sensor_used": False,
        }

    return observer(
        objective,
        context,
    )


def activate_and_think(
    objective: str,
) -> dict[str, Any]:
    from sophyane.cognitive_memory import (
        form_thought,
    )

    return form_thought(
        objective,
        limit=5,
    )


def _default_reasoner(
    objective: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Reason through the currently selected fixed session provider.

    This uses the already-proven SessionProviderReasoner authority
    rather than selecting another LLM.

    The operation deliberately asks for hypotheses only. A model
    hypothesis still does not create execution authority.
    """

    try:
        from sophyane.discovery_provider_reasoner import (
            SessionProviderReasoner,
        )

        reasoner = SessionProviderReasoner()

        raw = reasoner(
            "generate_hypotheses",
            {
                "objective": objective,
                "knowledge": [
                    {
                        "source": "cognitive_workspace",
                        "kind": "current_state",
                        "content": _canonical_json(
                            {
                                "observation": context.get(
                                    "observation"
                                ),
                                "thought": context.get(
                                    "thought"
                                ),
                            }
                        ),
                        "metadata": {
                            "instruction_authority": False,
                        },
                    }
                ],
                "requirements": {
                    "maximum": 2,
                    "bounded": True,
                    "do_not_change_provider": True,
                },
                "return_schema": {
                    "hypotheses": [
                        {
                            "statement": "string",
                            "rationale": "string",
                            "predictions": [
                                "string"
                            ],
                            "assumptions": [
                                "string"
                            ],
                        }
                    ]
                },
            },
        )

        return {
            "ok": True,
            "raw": raw,
            "parsed": _parse_jsonish(
                raw
            ),
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": (
                type(exc).__name__
                + ": "
                + str(exc)
            ),
        }


def reason(
    objective: str,
    *,
    reasoner: Reasoner | None,
    context: Mapping[str, Any],
) -> Any:
    if reasoner is not None:
        return reasoner(
            objective,
            context,
        )

    return _default_reasoner(
        objective,
        context,
    )


def choose_bounded_task(
    objective: str,
    reasoning: Any,
    *,
    source_dream_id: str | None = None,
) -> CognitiveTask | None:
    """Translate reasoning into a bounded task request.

    Explicit structured task output is accepted only when it contains
    action_kind + objective. Otherwise a hypothesis becomes a
    non-executing `hypothesis_only` task.

    `hypothesis_only` has no default action handler.
    """

    parsed = reasoning

    if isinstance(
        reasoning,
        Mapping,
    ) and "parsed" in reasoning:
        parsed = reasoning.get(
            "parsed"
        )

    if isinstance(
        parsed,
        Mapping,
    ):
        explicit = parsed.get(
            "task"
        )

        if isinstance(
            explicit,
            Mapping,
        ):
            action_kind = str(
                explicit.get(
                    "action_kind",
                    "",
                )
                or ""
            ).strip()

            task_objective = str(
                explicit.get(
                    "objective",
                    objective,
                )
                or objective
            ).strip()

            if action_kind:
                return CognitiveTask(
                    task_id=(
                        "task:"
                        + uuid.uuid4().hex
                    ),
                    objective=task_objective,
                    action_kind=action_kind,
                    payload=dict(
                        explicit.get(
                            "payload",
                            {},
                        )
                        or {}
                    ),
                    risk_class=str(
                        explicit.get(
                            "risk_class",
                            "analysis",
                        )
                        or "analysis"
                    ),
                    rationale=str(
                        explicit.get(
                            "rationale",
                            "",
                        )
                        or ""
                    ),
                    source="reasoning",
                    source_dream_id=source_dream_id,
                    bounded=bool(
                        explicit.get(
                            "bounded",
                            True,
                        )
                    ),
                    requires_confirmation=bool(
                        explicit.get(
                            "requires_confirmation",
                            False,
                        )
                    ),
                )

        hypotheses = parsed.get(
            "hypotheses"
        )

        if (
            isinstance(
                hypotheses,
                list,
            )
            and hypotheses
            and isinstance(
                hypotheses[0],
                Mapping,
            )
        ):
            first = hypotheses[0]

            return CognitiveTask(
                task_id=(
                    "task:"
                    + uuid.uuid4().hex
                ),
                objective=str(
                    first.get(
                        "statement",
                        objective,
                    )
                    or objective
                ),
                action_kind="hypothesis_only",
                payload={
                    "hypothesis": dict(
                        first
                    ),
                },
                risk_class="analysis",
                rationale=str(
                    first.get(
                        "rationale",
                        "",
                    )
                    or ""
                ),
                source=(
                    "dream_hypothesis"
                    if source_dream_id
                    else "reasoning"
                ),
                source_dream_id=source_dream_id,
                bounded=True,
                requires_confirmation=False,
            )

    return CognitiveTask(
        task_id=(
            "task:"
            + uuid.uuid4().hex
        ),
        objective=objective,
        action_kind="hypothesis_only",
        payload={
            "reasoning": parsed,
        },
        risk_class="analysis",
        rationale=(
            "No executable capability was explicitly proposed."
        ),
        source=(
            "dream_hypothesis"
            if source_dream_id
            else "reasoning"
        ),
        source_dream_id=source_dream_id,
        bounded=True,
        requires_confirmation=False,
    )


def _task_policy_check(
    task: CognitiveTask,
    config: CognitiveLoopConfig,
) -> tuple[bool, str]:
    if not task.bounded:
        return (
            False,
            "unbounded_task",
        )

    risk = str(
        task.risk_class
        or ""
    ).strip()

    if risk in BLOCKED_RISK_CLASSES:
        return (
            False,
            "risk_class_blocked",
        )

    if risk not in set(
        config.allow_risk_classes
    ):
        return (
            False,
            "risk_class_not_allowed",
        )

    if task.requires_confirmation:
        return (
            False,
            "human_confirmation_required",
        )

    return (
        True,
        "allowed",
    )


def act(
    task: CognitiveTask,
    *,
    registry: CognitiveActionRegistry,
    config: CognitiveLoopConfig,
    context: Mapping[str, Any],
) -> ActionResult:
    allowed, reason_text = (
        _task_policy_check(
            task,
            config,
        )
    )

    if not allowed:
        return ActionResult(
            ok=False,
            status="policy_blocked",
            error=reason_text,
            metadata={
                "risk_class": task.risk_class,
                "action_kind": task.action_kind,
            },
        )

    return registry.execute(
        task,
        context,
    )


def measure(
    task: CognitiveTask,
    action_result: ActionResult,
    *,
    measurer: Measurer | None,
    context: Mapping[str, Any],
) -> Any:
    if measurer is not None:
        return measurer(
            task,
            action_result,
            context,
        )

    return {
        "action_ok": action_result.ok,
        "status": action_result.status,
        "observation": action_result.observation,
        "evidence": action_result.evidence,
        "error": action_result.error,
    }


def verify(
    task: CognitiveTask,
    action_result: ActionResult,
    measurement: Any,
    *,
    verifier: Verifier | None,
    context: Mapping[str, Any],
) -> VerificationResult:
    """Never infer verification from model confidence.

    With no verifier there is no verified success.
    """

    if verifier is None:
        return VerificationResult(
            verified=False,
            accepted=False,
            evidence={
                "reason": (
                    "No external/deterministic verifier "
                    "was supplied."
                ),
                "measurement": measurement,
            },
            score=0.0,
            reason="verifier_unavailable",
        )

    try:
        raw = verifier(
            task,
            action_result,
            measurement,
            context,
        )

    except Exception as exc:
        return VerificationResult(
            verified=False,
            accepted=False,
            evidence={
                "verifier_exception": (
                    type(exc).__name__
                    + ": "
                    + str(exc)
                )
            },
            score=0.0,
            reason="verifier_exception",
        )

    return _coerce_verification(
        raw
    )


# ---------------------------------------------------------------------------
# Episode recording / consolidation
# ---------------------------------------------------------------------------

def _episode_from_cycle(
    *,
    cycle_id: str,
    objective: str,
    observation: Any,
    thought: Mapping[str, Any],
    reasoning: Any,
    task: CognitiveTask | None,
    action_result: ActionResult | None,
    measurement: Any,
    verification: VerificationResult,
    authority: Mapping[str, Any],
    source_dream_id: str | None,
) -> dict[str, Any]:
    now = time.time()

    accepted = bool(
        verification.verified
        and verification.accepted
    )

    status = (
        "succeeded"
        if accepted
        else "not_verified"
    )

    task_dict = (
        {
            "task_id": task.task_id,
            "objective": task.objective,
            "action_kind": task.action_kind,
            "payload": task.payload,
            "risk_class": task.risk_class,
            "rationale": task.rationale,
            "source": task.source,
            "source_dream_id": task.source_dream_id,
            "bounded": task.bounded,
            "requires_confirmation": (
                task.requires_confirmation
            ),
        }
        if task is not None
        else None
    )

    action_dict = (
        {
            "ok": action_result.ok,
            "status": action_result.status,
            "observation": action_result.observation,
            "evidence": action_result.evidence,
            "error": action_result.error,
            "metadata": action_result.metadata,
        }
        if action_result is not None
        else None
    )

    episode = {
        "trace_id": cycle_id,
        "event_key": cycle_id,
        "episode_kind": "cognitive_cycle",
        "original_objective": objective,
        "observation": observation,
        "thought": dict(
            thought
        ),
        "reasoning": reasoning,
        "task": task_dict,
        "action": action_dict,
        "measurement": measurement,
        "verification_state": (
            "verified"
            if verification.verified
            else "unverified"
        ),
        "verification_evidence": (
            verification.evidence
        ),
        "verification_reason": (
            verification.reason
        ),
        "verification_score": (
            verification.score
        ),
        "accepted": accepted,
        "status": status,
        "reward": (
            float(
                verification.score
            )
            if accepted
            else 0.0
        ),
        "provider_identity": (
            authority.get(
                "session_provider"
            )
        ),
        "model_identity": (
            authority.get(
                "session_model"
            )
        ),
        "session_mode": (
            authority.get(
                "session_mode"
            )
        ),
        "intelligence_authority": dict(
            authority
        ),
        "capability_class": (
            task.action_kind
            if task is not None
            else "no_task"
        ),
        "source_dream_id": source_dream_id,
        "instruction_authority": False,
        "created_at": now,
    }

    episode[
        "exact_cycle_hash"
    ] = _digest(
        episode
    )

    return episode


def record_episode(
    episode: Mapping[str, Any],
) -> dict[str, Any]:
    """Always preserve exact cycle evidence.

    Trusted verified success additionally flows through the Phase 7
    episodic writer, which derives sparse memory.

    Failed/unverified cycles remain exact history but do not become
    trusted sparse memory.
    """

    exact_path = _append_exact_cycle(
        episode
    )

    result: dict[str, Any] = {
        "ok": True,
        "exact_cycle_path": exact_path,
        "exact_recorded": True,
        "trusted_episode_recorded": False,
        "sparse_memory_created": False,
    }

    if not (
        episode.get(
            "accepted"
        ) is True
        and episode.get(
            "verification_state"
        )
        == "verified"
        and episode.get(
            "status"
        )
        == "succeeded"
    ):
        return result

    try:
        from sophyane.episodic_memory import (
            persist_execution_episode,
        )

        persisted = (
            persist_execution_episode(
                dict(episode)
            )
        )

        result[
            "episodic_result"
        ] = persisted

        if isinstance(
            persisted,
            Mapping,
        ):
            result[
                "trusted_episode_recorded"
            ] = bool(
                persisted.get(
                    "ok"
                )
            )

            cognitive = persisted.get(
                "cognitive_memory"
            )

            if isinstance(
                cognitive,
                Mapping,
            ):
                result[
                    "sparse_memory_created"
                ] = bool(
                    cognitive.get(
                        "ok"
                    )
                )

    except Exception as exc:
        result[
            "episodic_error"
        ] = (
            type(exc).__name__
            + ": "
            + str(exc)
        )

    return result


# ---------------------------------------------------------------------------
# Dreaming
# ---------------------------------------------------------------------------

def maybe_dream(
    cycle_number: int,
    *,
    objective: str,
    config: CognitiveLoopConfig,
) -> dict[str, Any] | None:
    interval = int(
        config.dream_interval
    )

    if interval <= 0:
        return None

    if (
        cycle_number
        % interval
        != 0
    ):
        return None

    try:
        from sophyane.cognitive_memory import (
            dream_cycle,
        )

        return dream_cycle(
            seed=objective,
            limit=6,
        )

    except Exception as exc:
        return {
            "ok": False,
            "reason": (
                type(exc).__name__
                + ": "
                + str(exc)
            ),
        }


def dream_to_hypothesis(
    dream_result: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Convert dream material into an explicitly unverified hypothesis."""

    if not isinstance(
        dream_result,
        Mapping,
    ):
        return None

    if dream_result.get(
        "ok"
    ) is not True:
        return None

    dream = dream_result.get(
        "dream"
    )

    if not isinstance(
        dream,
        Mapping,
    ):
        return None

    dream_id = str(
        dream.get(
            "dream_id",
            "",
        )
        or ""
    ).strip()

    pattern = str(
        dream.get(
            "possible_pattern",
            "",
        )
        or ""
    ).strip()

    if not pattern:
        return None

    return {
        "kind": "dream_hypothesis",
        "dream_id": dream_id,
        "statement": pattern,
        "source_memory_ids": list(
            dream.get(
                "source_memory_ids",
                [],
            )
            or []
        ),
        "verified": False,
        "trusted": False,
        "accepted": False,
        "instruction_authority": False,
        "requires_external_verification": True,
    }


# ---------------------------------------------------------------------------
# Single cycle
# ---------------------------------------------------------------------------

def run_cognitive_cycle(
    objective: str,
    *,
    cycle_number: int = 1,
    observer: Observer | None = None,
    reasoner: Reasoner | None = None,
    registry: CognitiveActionRegistry | None = None,
    measurer: Measurer | None = None,
    verifier: Verifier | None = None,
    config: CognitiveLoopConfig | None = None,
    source_dream_id: str | None = None,
) -> CognitiveCycleResult:
    config = (
        config
        or CognitiveLoopConfig()
    )

    if registry is None:
        _ensure_builtin_actions()
        registry = _GLOBAL_ACTIONS

    cycle_id = (
        "cognitive:"
        + uuid.uuid4().hex
    )

    authority = (
        _authority_snapshot()
    )

    base_context: dict[str, Any] = {
        "cycle_id": cycle_id,
        "cycle_number": cycle_number,
        "objective": objective,
        "authority": authority,
        "source_dream_id": source_dream_id,
    }

    observation = observe(
        objective,
        observer=observer,
        context=base_context,
    )

    thought = activate_and_think(
        objective
    )

    reasoning_context = {
        **base_context,
        "observation": observation,
        "thought": thought,
    }

    reasoning = reason(
        objective,
        reasoner=reasoner,
        context=reasoning_context,
    )

    task = choose_bounded_task(
        objective,
        reasoning,
        source_dream_id=source_dream_id,
    )

    if task is None:
        action_result = None

        measurement = {
            "task_selected": False,
        }

        verification_result = VerificationResult(
            verified=False,
            accepted=False,
            evidence={
                "reason": "no_task_selected",
            },
            score=0.0,
            reason="no_task_selected",
        )

    else:
        action_context = {
            **reasoning_context,
            "reasoning": reasoning,
            "task": task,
        }

        action_result = act(
            task,
            registry=registry,
            config=config,
            context=action_context,
        )

        measurement = measure(
            task,
            action_result,
            measurer=measurer,
            context=action_context,
        )

        verification_result = verify(
            task,
            action_result,
            measurement,
            verifier=verifier,
            context=action_context,
        )

    episode = _episode_from_cycle(
        cycle_id=cycle_id,
        objective=objective,
        observation=observation,
        thought=thought,
        reasoning=reasoning,
        task=task,
        action_result=action_result,
        measurement=measurement,
        verification=verification_result,
        authority=authority,
        source_dream_id=source_dream_id,
    )

    persistence = record_episode(
        episode
    )

    dream = maybe_dream(
        cycle_number,
        objective=objective,
        config=config,
    )

    next_hypothesis = (
        dream_to_hypothesis(
            dream
        )
    )

    return CognitiveCycleResult(
        cycle_id=cycle_id,
        objective=objective,
        observation=observation,
        thought=thought,
        reasoning=reasoning,
        task=task,
        action=action_result,
        verification=verification_result,
        episode=episode,
        persistence=persistence,
        dream=dream,
        next_hypothesis=next_hypothesis,
    )


# ---------------------------------------------------------------------------
# Multi-cycle bounded scheduler
# ---------------------------------------------------------------------------

def _stop_requested(
    config: CognitiveLoopConfig,
) -> bool:
    if not config.stop_file:
        return False

    try:
        return Path(
            config.stop_file
        ).expanduser().exists()

    except Exception:
        return False


def run_cognitive_loop(
    objective: str,
    *,
    observer: Observer | None = None,
    reasoner: Reasoner | None = None,
    registry: CognitiveActionRegistry | None = None,
    measurer: Measurer | None = None,
    verifier: Verifier | None = None,
    config: CognitiveLoopConfig | None = None,
) -> list[CognitiveCycleResult]:
    """Run a finite, resource-bounded cognitive loop.

    This function does NOT daemonize itself.
    24-hour scheduling should be a separate supervisor responsibility.
    """

    config = (
        config
        or CognitiveLoopConfig()
    )

    started = time.monotonic()

    results: list[
        CognitiveCycleResult
    ] = []

    current_objective = str(
        objective
        or ""
    ).strip()

    source_dream_id: str | None = None

    for cycle_number in range(
        1,
        max(
            1,
            int(
                config.max_cycles
            ),
        )
        + 1,
    ):
        if _stop_requested(
            config
        ):
            break

        elapsed = (
            time.monotonic()
            - started
        )

        if (
            elapsed
            >= float(
                config.max_runtime_seconds
            )
        ):
            break

        result = run_cognitive_cycle(
            current_objective,
            cycle_number=cycle_number,
            observer=observer,
            reasoner=reasoner,
            registry=registry,
            measurer=measurer,
            verifier=verifier,
            config=config,
            source_dream_id=source_dream_id,
        )

        results.append(
            result
        )

        hypothesis = (
            result.next_hypothesis
        )

        if isinstance(
            hypothesis,
            Mapping,
        ):
            statement = str(
                hypothesis.get(
                    "statement",
                    "",
                )
                or ""
            ).strip()

            if statement:
                current_objective = (
                    "Test this unverified dream hypothesis "
                    "against reality using bounded execution "
                    "and objective verification: "
                    + statement
                )

                source_dream_id = str(
                    hypothesis.get(
                        "dream_id",
                        "",
                    )
                    or ""
                ) or None

        if (
            config.idle_sleep_seconds
            > 0
        ):
            time.sleep(
                float(
                    config.idle_sleep_seconds
                )
            )

    return results


def cognitive_loop_status() -> dict[str, Any]:
    _ensure_builtin_actions()

    return {
        "marker": LOOP_MARKER,
        "exact_cycle_path": str(
            _cycle_journal()
        ),
        "safe_risk_classes": sorted(
            SAFE_RISK_CLASSES
        ),
        "blocked_risk_classes": sorted(
            BLOCKED_RISK_CLASSES
        ),
        "registered_actions": sorted(
            _GLOBAL_ACTIONS._handlers
        ),
        "builtin_action_install_error": (
            _BUILTIN_ACTIONS_INSTALL_ERROR
        ),
        "session_authority": (
            _authority_snapshot()
        ),
        "thought_authority": False,
        "dream_authority": False,
        "dreams_require_verification": True,
        "unregistered_actions_execute": False,
        "daemonizes_itself": False,
    }


__all__ = [
    "ActionResult",
    "CognitiveActionRegistry",
    "CognitiveCycleResult",
    "CognitiveLoopConfig",
    "CognitiveTask",
    "VerificationResult",
    "cognitive_action_registry",
    "cognitive_loop_status",
    "dream_to_hypothesis",
    "register_cognitive_action",
    "run_cognitive_cycle",
    "run_cognitive_loop",
]
