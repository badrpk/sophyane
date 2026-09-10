"""Persistent wake/rest/dream supervisor for Sophyane.

SOPHYANE_PERSISTENT_COGNITIVE_SUPERVISOR_V1

Lifecycle:

    WAKE
      observe -> recall -> think -> reason -> bounded action
      -> measure -> verify -> learn

    REST
      no external actions
      recover resource budget
      preserve exact state

    DREAM
      recombine sparse memories
      produce explicitly unverified hypotheses
      queue promising hypotheses for later WAKE testing

Critical properties:

* survives process restarts through disk-first Xerus state;
* never changes session intelligence authority;
* does not daemonize itself;
* every invocation remains bounded;
* stop file is checked between supervisor steps;
* heartbeat/state are durable and inspectable;
* REST and DREAM cannot invoke action handlers;
* dream hypotheses remain untrusted until a WAKE cycle verifies them.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


SUPERVISOR_MARKER = (
    "SOPHYANE_PERSISTENT_COGNITIVE_SUPERVISOR_V1"
)

PHASE_WAKE = "wake"
PHASE_REST = "rest"
PHASE_DREAM = "dream"

VALID_PHASES = {
    PHASE_WAKE,
    PHASE_REST,
    PHASE_DREAM,
}


@dataclass(frozen=True)
class SupervisorConfig:
    wake_cycles_before_rest: int = 4
    rest_steps: int = 1
    dream_steps: int = 1

    max_energy: float = 1.0
    wake_energy_cost: float = 0.20
    rest_energy_recovery: float = 0.55

    max_pending_hypotheses: int = 16
    max_supervisor_steps: int = 12
    max_runtime_seconds: float = 1800.0

    stop_file: str | None = None
    heartbeat_file: str | None = None
    state_file: str | None = None


@dataclass
class SupervisorState:
    supervisor_id: str

    phase: str = PHASE_WAKE

    supervisor_step: int = 0
    wake_cycles_total: int = 0
    rest_steps_total: int = 0
    dream_steps_total: int = 0

    wake_cycles_since_rest: int = 0
    rest_steps_in_phase: int = 0
    dream_steps_in_phase: int = 0

    energy: float = 1.0

    base_objective: str = ""
    active_objective: str = ""

    pending_hypotheses: list[dict[str, Any]] = field(
        default_factory=list
    )

    current_hypothesis: dict[str, Any] | None = None

    authority_fingerprint: dict[str, Any] = field(
        default_factory=dict
    )

    last_cycle_id: str | None = None
    last_verification_state: str | None = None

    last_transition_reason: str = "initialization"

    created_at: float = field(
        default_factory=time.time
    )

    updated_at: float = field(
        default_factory=time.time
    )


def _xerus_root() -> Path:
    value = str(
        os.environ.get(
            "XERUS_HOME",
            "",
        )
        or ""
    ).strip()

    if value:
        return Path(
            value
        ).expanduser()

    return (
        Path.home()
        / ".local"
        / "share"
        / "xerus"
    )


def default_state_path() -> Path:
    return (
        _xerus_root()
        / "cognitive-supervisor-state.json"
    )


def default_heartbeat_path() -> Path:
    return (
        _xerus_root()
        / "cognitive-supervisor-heartbeat.json"
    )


def default_stop_path() -> Path:
    return (
        _xerus_root()
        / "cognitive-supervisor.stop"
    )


def _resolved_state_path(
    config: SupervisorConfig,
) -> Path:
    if config.state_file:
        return Path(
            config.state_file
        ).expanduser()

    return default_state_path()


def _resolved_heartbeat_path(
    config: SupervisorConfig,
) -> Path:
    if config.heartbeat_file:
        return Path(
            config.heartbeat_file
        ).expanduser()

    return default_heartbeat_path()


def _resolved_stop_path(
    config: SupervisorConfig,
) -> Path:
    if config.stop_file:
        return Path(
            config.stop_file
        ).expanduser()

    return default_stop_path()


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


def _atomic_json_write(
    path: Path,
    value: object,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n"
    )

    fd, temporary = tempfile.mkstemp(
        prefix=(
            "."
            + path.name
            + "."
        ),
        suffix=".tmp",
        dir=str(
            path.parent
        ),
    )

    temporary_path = Path(
        temporary
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(
                payload
            )

            handle.flush()

            os.fsync(
                handle.fileno()
            )

        os.replace(
            temporary_path,
            path,
        )

    finally:
        try:
            temporary_path.unlink(
                missing_ok=True
            )

        except Exception:
            pass


def _authority_snapshot() -> dict[str, Any]:
    try:
        from sophyane.intelligence_authority import (
            current_intelligence_authority,
        )

        authority = (
            current_intelligence_authority()
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
            "session_mode": os.environ.get(
                "SOPHYANE_SESSION_MODE"
            ),
            "session_provider": os.environ.get(
                "SOPHYANE_SESSION_PROVIDER"
            ),
            "session_model": os.environ.get(
                "SOPHYANE_SESSION_MODEL"
            ),
            "authority_error": (
                type(exc).__name__
                + ": "
                + str(exc)
            ),
        }


def _authority_identity(
    authority: Mapping[str, Any],
) -> tuple[Any, Any, Any]:
    return (
        authority.get(
            "session_mode"
        ),
        authority.get(
            "session_provider"
        ),
        authority.get(
            "session_model"
        ),
    )


def _assert_authority_unchanged(
    state: SupervisorState,
) -> None:
    current = (
        _authority_snapshot()
    )

    expected_identity = (
        _authority_identity(
            state.authority_fingerprint
        )
    )

    current_identity = (
        _authority_identity(
            current
        )
    )

    if (
        current_identity
        != expected_identity
    ):
        raise RuntimeError(
            "COGNITIVE_SUPERVISOR_AUTHORITY_DRIFT: "
            f"expected={expected_identity!r} "
            f"current={current_identity!r}"
        )


def _state_from_dict(
    payload: Mapping[str, Any],
) -> SupervisorState:
    allowed = {
        field_name
        for field_name
        in SupervisorState.__dataclass_fields__
    }

    cleaned = {
        key: value
        for key, value
        in dict(
            payload
        ).items()
        if key in allowed
    }

    state = SupervisorState(
        **cleaned
    )

    if state.phase not in VALID_PHASES:
        state.phase = PHASE_WAKE

    state.energy = max(
        0.0,
        min(
            1.0,
            float(
                state.energy
            ),
        ),
    )

    return state


def load_supervisor_state(
    objective: str,
    *,
    config: SupervisorConfig | None = None,
) -> SupervisorState:
    config = (
        config
        or SupervisorConfig()
    )

    path = (
        _resolved_state_path(
            config
        )
    )

    if path.exists():
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            payload,
            dict,
        ):
            raise RuntimeError(
                "invalid supervisor state payload"
            )

        state = _state_from_dict(
            payload
        )

        #
        # A restart may provide the same high-level objective.
        # Preserve the already-active dream test if one exists.
        #
        if (
            not state.base_objective
            and objective
        ):
            state.base_objective = str(
                objective
            )

        if (
            not state.active_objective
            and objective
        ):
            state.active_objective = str(
                objective
            )

        return state

    authority = (
        _authority_snapshot()
    )

    return SupervisorState(
        supervisor_id=(
            "supervisor:"
            + uuid.uuid4().hex
        ),
        phase=PHASE_WAKE,
        energy=max(
            0.0,
            min(
                1.0,
                float(
                    config.max_energy
                ),
            ),
        ),
        base_objective=str(
            objective
            or ""
        ).strip(),
        active_objective=str(
            objective
            or ""
        ).strip(),
        authority_fingerprint=authority,
        created_at=time.time(),
        updated_at=time.time(),
    )


def save_supervisor_state(
    state: SupervisorState,
    *,
    config: SupervisorConfig | None = None,
) -> Path:
    config = (
        config
        or SupervisorConfig()
    )

    state.updated_at = (
        time.time()
    )

    path = (
        _resolved_state_path(
            config
        )
    )

    _atomic_json_write(
        path,
        asdict(
            state
        ),
    )

    return path


def write_heartbeat(
    state: SupervisorState,
    *,
    config: SupervisorConfig | None = None,
    event: str = "alive",
) -> Path:
    config = (
        config
        or SupervisorConfig()
    )

    path = (
        _resolved_heartbeat_path(
            config
        )
    )

    payload = {
        "marker": (
            SUPERVISOR_MARKER
        ),
        "supervisor_id": (
            state.supervisor_id
        ),
        "event": event,
        "phase": state.phase,
        "supervisor_step": (
            state.supervisor_step
        ),
        "energy": state.energy,
        "active_objective": (
            state.active_objective
        ),
        "pending_hypotheses": len(
            state.pending_hypotheses
        ),
        "last_cycle_id": (
            state.last_cycle_id
        ),
        "updated_at": time.time(),
        "pid": os.getpid(),
        "authority": (
            state.authority_fingerprint
        ),
    }

    _atomic_json_write(
        path,
        payload,
    )

    return path


def stop_requested(
    *,
    config: SupervisorConfig | None = None,
) -> bool:
    config = (
        config
        or SupervisorConfig()
    )

    return (
        _resolved_stop_path(
            config
        ).exists()
    )


def request_supervisor_stop(
    *,
    config: SupervisorConfig | None = None,
) -> Path:
    config = (
        config
        or SupervisorConfig()
    )

    path = (
        _resolved_stop_path(
            config
        )
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        "stop\n",
        encoding="utf-8",
    )

    return path


def clear_supervisor_stop(
    *,
    config: SupervisorConfig | None = None,
) -> None:
    config = (
        config
        or SupervisorConfig()
    )

    _resolved_stop_path(
        config
    ).unlink(
        missing_ok=True
    )


def _queue_hypothesis(
    state: SupervisorState,
    hypothesis: Mapping[str, Any],
    *,
    config: SupervisorConfig,
) -> None:
    item = dict(
        hypothesis
    )

    item[
        "verified"
    ] = False

    item[
        "trusted"
    ] = False

    item[
        "accepted"
    ] = False

    item[
        "instruction_authority"
    ] = False

    item[
        "requires_external_verification"
    ] = True

    dream_id = str(
        item.get(
            "dream_id",
            "",
        )
        or ""
    ).strip()

    statement = str(
        item.get(
            "statement",
            "",
        )
        or ""
    ).strip()

    for existing in (
        state.pending_hypotheses
    ):
        if (
            dream_id
            and existing.get(
                "dream_id"
            )
            == dream_id
        ):
            return

        if (
            statement
            and existing.get(
                "statement"
            )
            == statement
        ):
            return

    state.pending_hypotheses.append(
        item
    )

    max_pending = max(
        1,
        int(
            config.max_pending_hypotheses
        ),
    )

    if (
        len(
            state.pending_hypotheses
        )
        > max_pending
    ):
        state.pending_hypotheses = (
            state.pending_hypotheses[
                -max_pending:
            ]
        )


def _select_pending_hypothesis(
    state: SupervisorState,
) -> dict[str, Any] | None:
    if not state.pending_hypotheses:
        return None

    selected = dict(
        state.pending_hypotheses.pop(
            0
        )
    )

    #
    # Enforce epistemic state on dequeue too.
    #
    selected[
        "verified"
    ] = False

    selected[
        "trusted"
    ] = False

    selected[
        "accepted"
    ] = False

    selected[
        "instruction_authority"
    ] = False

    selected[
        "requires_external_verification"
    ] = True

    return selected


def _objective_for_hypothesis(
    hypothesis: Mapping[str, Any],
) -> str:
    statement = str(
        hypothesis.get(
            "statement",
            "",
        )
        or ""
    ).strip()

    return (
        "Test this unverified dream hypothesis "
        "against reality using only bounded "
        "registered capabilities and objective "
        "verification. Do not treat the hypothesis "
        "as true unless verification succeeds: "
        + statement
    )


def _wake_step(
    state: SupervisorState,
    *,
    config: SupervisorConfig,
    observer: Callable[..., Any] | None,
    reasoner: Callable[..., Any] | None,
    registry: Any,
    measurer: Callable[..., Any] | None,
    verifier: Callable[..., Any] | None,
) -> dict[str, Any]:
    from sophyane.cognitive_loop import (
        CognitiveLoopConfig,
        run_cognitive_cycle,
    )

    _assert_authority_unchanged(
        state
    )

    if (
        state.current_hypothesis
        is None
        and state.pending_hypotheses
    ):
        state.current_hypothesis = (
            _select_pending_hypothesis(
                state
            )
        )

        if (
            state.current_hypothesis
            is not None
        ):
            state.active_objective = (
                _objective_for_hypothesis(
                    state.current_hypothesis
                )
            )

    if not state.active_objective:
        state.active_objective = (
            state.base_objective
        )

    source_dream_id = None

    if state.current_hypothesis:
        source_dream_id = str(
            state.current_hypothesis.get(
                "dream_id",
                "",
            )
            or ""
        ) or None

    result = run_cognitive_cycle(
        state.active_objective,
        cycle_number=(
            state.wake_cycles_total
            + 1
        ),
        observer=observer,
        reasoner=reasoner,
        registry=registry,
        measurer=measurer,
        verifier=verifier,
        config=CognitiveLoopConfig(
            max_cycles=1,
            max_actions_per_cycle=1,
            max_runtime_seconds=(
                config.max_runtime_seconds
            ),
            dream_interval=0,
            idle_sleep_seconds=0.0,
        ),
        source_dream_id=source_dream_id,
    )

    state.wake_cycles_total += 1

    state.wake_cycles_since_rest += 1

    state.energy = max(
        0.0,
        state.energy
        - float(
            config.wake_energy_cost
        ),
    )

    state.last_cycle_id = (
        result.cycle_id
    )

    state.last_verification_state = (
        result.episode.get(
            "verification_state"
        )
    )

    tested_hypothesis = (
        state.current_hypothesis
    )

    if tested_hypothesis is not None:
        #
        # The dream itself never becomes true.
        # A successful WAKE cycle creates a separate
        # verified execution episode via Phase 8.
        #
        state.current_hypothesis = None

        state.active_objective = (
            state.base_objective
        )

    should_rest = (
        state.energy
        <= 0.000001
        or state.wake_cycles_since_rest
        >= max(
            1,
            int(
                config.wake_cycles_before_rest
            ),
        )
    )

    if should_rest:
        state.phase = PHASE_REST
        state.rest_steps_in_phase = 0
        state.last_transition_reason = (
            "wake_budget_exhausted"
        )

    return {
        "kind": "wake",
        "cycle_id": (
            result.cycle_id
        ),
        "verified": (
            result.verification.verified
        ),
        "accepted": (
            result.verification.accepted
        ),
        "exact_recorded": (
            result.persistence.get(
                "exact_recorded"
            )
        ),
        "sparse_memory_created": (
            result.persistence.get(
                "sparse_memory_created"
            )
        ),
        "tested_dream_id": (
            source_dream_id
        ),
        "energy": state.energy,
        "next_phase": state.phase,
    }


def _rest_step(
    state: SupervisorState,
    *,
    config: SupervisorConfig,
) -> dict[str, Any]:
    """REST deliberately performs no action execution."""

    state.rest_steps_total += 1
    state.rest_steps_in_phase += 1

    before = state.energy

    state.energy = min(
        float(
            config.max_energy
        ),
        state.energy
        + float(
            config.rest_energy_recovery
        ),
    )

    completed = (
        state.rest_steps_in_phase
        >= max(
            1,
            int(
                config.rest_steps
            ),
        )
    )

    if completed:
        state.phase = PHASE_DREAM
        state.dream_steps_in_phase = 0
        state.last_transition_reason = (
            "rest_complete"
        )

    return {
        "kind": "rest",
        "external_action": False,
        "energy_before": before,
        "energy_after": (
            state.energy
        ),
        "next_phase": (
            state.phase
        ),
    }


def _dream_step(
    state: SupervisorState,
    *,
    config: SupervisorConfig,
) -> dict[str, Any]:
    """DREAM may create hypotheses, never action execution."""

    from sophyane.cognitive_loop import (
        dream_to_hypothesis,
    )

    from sophyane.cognitive_memory import (
        dream_cycle,
    )

    state.dream_steps_total += 1
    state.dream_steps_in_phase += 1

    result = dream_cycle(
        seed=(
            state.base_objective
        ),
        limit=6,
    )

    hypothesis = (
        dream_to_hypothesis(
            result
        )
    )

    if hypothesis:
        _queue_hypothesis(
            state,
            hypothesis,
            config=config,
        )

    completed = (
        state.dream_steps_in_phase
        >= max(
            1,
            int(
                config.dream_steps
            ),
        )
    )

    if completed:
        state.phase = PHASE_WAKE
        state.wake_cycles_since_rest = 0
        state.rest_steps_in_phase = 0
        state.dream_steps_in_phase = 0
        state.last_transition_reason = (
            "dream_complete"
        )

        if (
            state.current_hypothesis
            is None
            and state.pending_hypotheses
        ):
            state.current_hypothesis = (
                _select_pending_hypothesis(
                    state
                )
            )

            if (
                state.current_hypothesis
                is not None
            ):
                state.active_objective = (
                    _objective_for_hypothesis(
                        state.current_hypothesis
                    )
                )

    return {
        "kind": "dream",
        "external_action": False,
        "dream_ok": bool(
            isinstance(
                result,
                Mapping,
            )
            and result.get(
                "ok"
            )
            is True
        ),
        "hypothesis_created": (
            hypothesis is not None
        ),
        "pending_hypotheses": len(
            state.pending_hypotheses
        )
        + (
            1
            if state.current_hypothesis
            else 0
        ),
        "next_phase": (
            state.phase
        ),
    }


def run_supervisor_step(
    state: SupervisorState,
    *,
    config: SupervisorConfig | None = None,
    observer: Callable[..., Any] | None = None,
    reasoner: Callable[..., Any] | None = None,
    registry: Any = None,
    measurer: Callable[..., Any] | None = None,
    verifier: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    config = (
        config
        or SupervisorConfig()
    )

    if stop_requested(
        config=config
    ):
        write_heartbeat(
            state,
            config=config,
            event="stop_requested",
        )

        return {
            "ok": False,
            "stopped": True,
            "reason": "stop_requested",
        }

    _assert_authority_unchanged(
        state
    )

    phase_before = state.phase

    if state.phase == PHASE_WAKE:
        event = _wake_step(
            state,
            config=config,
            observer=observer,
            reasoner=reasoner,
            registry=registry,
            measurer=measurer,
            verifier=verifier,
        )

    elif state.phase == PHASE_REST:
        event = _rest_step(
            state,
            config=config,
        )

    elif state.phase == PHASE_DREAM:
        event = _dream_step(
            state,
            config=config,
        )

    else:
        raise RuntimeError(
            "invalid supervisor phase: "
            + repr(
                state.phase
            )
        )

    state.supervisor_step += 1
    state.updated_at = time.time()

    save_supervisor_state(
        state,
        config=config,
    )

    write_heartbeat(
        state,
        config=config,
        event=(
            phase_before
            + "_step_complete"
        ),
    )

    return {
        "ok": True,
        "stopped": False,
        "phase_before": phase_before,
        "phase_after": state.phase,
        "supervisor_step": (
            state.supervisor_step
        ),
        "event": event,
    }


def run_supervisor(
    objective: str,
    *,
    config: SupervisorConfig | None = None,
    observer: Callable[..., Any] | None = None,
    reasoner: Callable[..., Any] | None = None,
    registry: Any = None,
    measurer: Callable[..., Any] | None = None,
    verifier: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run a bounded supervisor invocation.

    Re-running this function later resumes the persisted state.

    It intentionally does NOT fork, background itself or become an
    infinite daemon.
    """

    config = (
        config
        or SupervisorConfig()
    )

    state = load_supervisor_state(
        objective,
        config=config,
    )

    _assert_authority_unchanged(
        state
    )

    started = time.monotonic()

    events: list[
        dict[str, Any]
    ] = []

    max_steps = max(
        1,
        int(
            config.max_supervisor_steps
        ),
    )

    for _ in range(
        max_steps
    ):
        if (
            time.monotonic()
            - started
            >= float(
                config.max_runtime_seconds
            )
        ):
            break

        result = run_supervisor_step(
            state,
            config=config,
            observer=observer,
            reasoner=reasoner,
            registry=registry,
            measurer=measurer,
            verifier=verifier,
        )

        events.append(
            result
        )

        if result.get(
            "stopped"
        ):
            break

    save_supervisor_state(
        state,
        config=config,
    )

    write_heartbeat(
        state,
        config=config,
        event="bounded_run_complete",
    )

    return {
        "ok": True,
        "marker": (
            SUPERVISOR_MARKER
        ),
        "state": asdict(
            state
        ),
        "events": events,
        "state_path": str(
            _resolved_state_path(
                config
            )
        ),
        "heartbeat_path": str(
            _resolved_heartbeat_path(
                config
            )
        ),
        "stop_path": str(
            _resolved_stop_path(
                config
            )
        ),
        "daemonized": False,
    }


def supervisor_status(
    *,
    config: SupervisorConfig | None = None,
) -> dict[str, Any]:
    config = (
        config
        or SupervisorConfig()
    )

    state_path = (
        _resolved_state_path(
            config
        )
    )

    heartbeat_path = (
        _resolved_heartbeat_path(
            config
        )
    )

    stop_path = (
        _resolved_stop_path(
            config
        )
    )

    state = None

    if state_path.exists():
        try:
            state = json.loads(
                state_path.read_text(
                    encoding="utf-8"
                )
            )

        except Exception:
            state = None

    heartbeat = None

    if heartbeat_path.exists():
        try:
            heartbeat = json.loads(
                heartbeat_path.read_text(
                    encoding="utf-8"
                )
            )

        except Exception:
            heartbeat = None

    return {
        "marker": SUPERVISOR_MARKER,
        "state_path": str(
            state_path
        ),
        "heartbeat_path": str(
            heartbeat_path
        ),
        "stop_path": str(
            stop_path
        ),
        "stop_requested": (
            stop_path.exists()
        ),
        "state": state,
        "heartbeat": heartbeat,
        "daemonizes_itself": False,
        "wake_executes_bounded_cycles": True,
        "rest_external_action": False,
        "dream_external_action": False,
        "dream_hypotheses_trusted": False,
        "authority_mutation_allowed": False,
    }


__all__ = [
    "PHASE_DREAM",
    "PHASE_REST",
    "PHASE_WAKE",
    "SUPERVISOR_MARKER",
    "SupervisorConfig",
    "SupervisorState",
    "clear_supervisor_stop",
    "default_heartbeat_path",
    "default_state_path",
    "default_stop_path",
    "load_supervisor_state",
    "request_supervisor_stop",
    "run_supervisor",
    "run_supervisor_step",
    "save_supervisor_state",
    "stop_requested",
    "supervisor_status",
    "write_heartbeat",
]
