"""Explicit mutable execution state for long-horizon Sophyane skills.

This implements the architectural principle that the model should reason
from:

1. an immutable skill specification;
2. the current structured execution state;
3. the latest observation;

rather than an ever-growing conversational transcript.

Historical trace data may still be persisted externally for audit/replay,
but it is not automatically injected into the model context.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import copy
import hashlib
import json
from pathlib import Path
import time
from typing import Any


STATE_SCHEMA_VERSION = 1
MAX_RECENT_EVENTS = 8
MAX_STATE_BYTES = 128 * 1024


def _canonical_json(
    value: Any,
) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _digest(
    value: Any,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            value
        ).encode(
            "utf-8"
        )
    ).hexdigest()[:24]


@dataclass(frozen=True)
class SkillSpecification:
    skill_id: str
    objective: str
    constraints: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def fingerprint(
        self,
    ) -> str:
        return _digest(
            asdict(
                self
            )
        )


@dataclass(frozen=True)
class Observation:
    sequence: int
    observed_at: float
    source: str
    kind: str
    payload: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class StateUpdate:
    sequence: int
    previous_digest: str
    current_digest: str
    changed_keys: tuple[str, ...]
    reason: str
    updated_at: float


@dataclass
class ExecutionState:
    skill: SkillSpecification
    state: dict[str, Any] = field(
        default_factory=dict
    )
    latest_observation: Observation | None = None
    recent_events: list[dict[str, Any]] = field(
        default_factory=list
    )
    sequence: int = 0
    created_at: float = field(
        default_factory=time.time
    )
    updated_at: float = field(
        default_factory=time.time
    )

    def __post_init__(
        self,
    ) -> None:
        self.state = copy.deepcopy(
            self.state
        )

        self.recent_events = [
            copy.deepcopy(item)
            for item in self.recent_events[
                -MAX_RECENT_EVENTS:
            ]
        ]

        self._assert_bounded()

    @property
    def state_digest(
        self,
    ) -> str:
        return _digest(
            self.state
        )

    def _assert_bounded(
        self,
    ) -> None:
        payload = _canonical_json(
            self.state
        ).encode(
            "utf-8"
        )

        if len(payload) > MAX_STATE_BYTES:
            raise ValueError(
                "execution state exceeds bounded state budget"
            )

        if len(
            self.recent_events
        ) > MAX_RECENT_EVENTS:
            raise ValueError(
                "recent event window exceeds bound"
            )

    def observe(
        self,
        *,
        source: str,
        kind: str,
        payload: dict[str, Any],
        observed_at: float | None = None,
    ) -> Observation:
        self.sequence += 1

        observation = Observation(
            sequence=self.sequence,
            observed_at=(
                time.time()
                if observed_at is None
                else float(
                    observed_at
                )
            ),
            source=str(
                source
                or "environment"
            ),
            kind=str(
                kind
                or "observation"
            ),
            payload=copy.deepcopy(
                payload
            ),
        )

        self.latest_observation = (
            observation
        )

        self.recent_events.append(
            {
                "sequence":
                    observation.sequence,
                "source":
                    observation.source,
                "kind":
                    observation.kind,
                "payload_digest":
                    _digest(
                        observation.payload
                    ),
            }
        )

        if len(
            self.recent_events
        ) > MAX_RECENT_EVENTS:
            del self.recent_events[
                :-MAX_RECENT_EVENTS
            ]

        self.updated_at = time.time()

        self._assert_bounded()

        return observation

    def replace_state(
        self,
        new_state: dict[str, Any],
        *,
        reason: str,
    ) -> StateUpdate:
        if not isinstance(
            new_state,
            dict,
        ):
            raise TypeError(
                "execution state must be a dictionary"
            )

        previous = copy.deepcopy(
            self.state
        )

        previous_digest = (
            self.state_digest
        )

        candidate = copy.deepcopy(
            new_state
        )

        changed = tuple(
            sorted(
                key
                for key in (
                    set(previous)
                    | set(candidate)
                )
                if (
                    previous.get(key)
                    != candidate.get(key)
                )
            )
        )

        self.state = candidate
        self.updated_at = time.time()

        self._assert_bounded()

        return StateUpdate(
            sequence=self.sequence,
            previous_digest=(
                previous_digest
            ),
            current_digest=(
                self.state_digest
            ),
            changed_keys=changed,
            reason=str(
                reason
                or ""
            ),
            updated_at=self.updated_at,
        )

    def merge_state(
        self,
        patch: dict[str, Any],
        *,
        reason: str,
    ) -> StateUpdate:
        candidate = copy.deepcopy(
            self.state
        )

        for key, value in (
            patch.items()
        ):
            candidate[
                str(key)
            ] = copy.deepcopy(
                value
            )

        return self.replace_state(
            candidate,
            reason=reason,
        )

    def delete_keys(
        self,
        keys: tuple[str, ...],
        *,
        reason: str,
    ) -> StateUpdate:
        candidate = copy.deepcopy(
            self.state
        )

        for key in keys:
            candidate.pop(
                key,
                None,
            )

        return self.replace_state(
            candidate,
            reason=reason,
        )

    def model_context(
        self,
    ) -> dict[str, Any]:
        """
        Return only current operational context.

        Deliberately excludes historical reasoning transcripts.
        """

        return {
            "schema_version":
                STATE_SCHEMA_VERSION,
            "skill": {
                "skill_id":
                    self.skill.skill_id,
                "objective":
                    self.skill.objective,
                "constraints":
                    list(
                        self.skill.constraints
                    ),
                "success_criteria":
                    list(
                        self.skill.success_criteria
                    ),
                "fingerprint":
                    self.skill.fingerprint,
            },
            "current_state":
                copy.deepcopy(
                    self.state
                ),
            "latest_observation": (
                asdict(
                    self.latest_observation
                )
                if self.latest_observation
                is not None
                else None
            ),
            "recent_event_digests":
                copy.deepcopy(
                    self.recent_events
                ),
            "state_digest":
                self.state_digest,
            "sequence":
                self.sequence,
        }

    def model_context_json(
        self,
    ) -> str:
        return _canonical_json(
            self.model_context()
        )

    def checkpoint(
        self,
        path: Path,
    ) -> Path:
        target = Path(
            path
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "schema_version":
                STATE_SCHEMA_VERSION,
            "skill":
                asdict(
                    self.skill
                ),
            "state":
                self.state,
            "latest_observation": (
                asdict(
                    self.latest_observation
                )
                if self.latest_observation
                is not None
                else None
            ),
            "recent_events":
                self.recent_events,
            "sequence":
                self.sequence,
            "created_at":
                self.created_at,
            "updated_at":
                self.updated_at,
        }

        temporary = target.with_suffix(
            target.suffix
            + ".tmp"
        )

        temporary.write_text(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(
            target
        )

        return target

    @classmethod
    def restore(
        cls,
        path: Path,
    ) -> "ExecutionState":
        raw = json.loads(
            Path(
                path
            ).read_text(
                encoding="utf-8",
            )
        )

        if int(
            raw.get(
                "schema_version",
                0,
            )
        ) != STATE_SCHEMA_VERSION:
            raise ValueError(
                "unsupported execution-state schema"
            )

        skill_raw = raw[
            "skill"
        ]

        skill = SkillSpecification(
            skill_id=str(
                skill_raw[
                    "skill_id"
                ]
            ),
            objective=str(
                skill_raw[
                    "objective"
                ]
            ),
            constraints=tuple(
                skill_raw.get(
                    "constraints",
                    (),
                )
            ),
            success_criteria=tuple(
                skill_raw.get(
                    "success_criteria",
                    (),
                )
            ),
            metadata=dict(
                skill_raw.get(
                    "metadata",
                    {},
                )
            ),
        )

        observation_raw = raw.get(
            "latest_observation"
        )

        observation = None

        if isinstance(
            observation_raw,
            dict,
        ):
            observation = Observation(
                sequence=int(
                    observation_raw[
                        "sequence"
                    ]
                ),
                observed_at=float(
                    observation_raw[
                        "observed_at"
                    ]
                ),
                source=str(
                    observation_raw[
                        "source"
                    ]
                ),
                kind=str(
                    observation_raw[
                        "kind"
                    ]
                ),
                payload=dict(
                    observation_raw.get(
                        "payload",
                        {},
                    )
                ),
            )

        return cls(
            skill=skill,
            state=dict(
                raw.get(
                    "state",
                    {},
                )
            ),
            latest_observation=(
                observation
            ),
            recent_events=list(
                raw.get(
                    "recent_events",
                    [],
                )
            ),
            sequence=int(
                raw.get(
                    "sequence",
                    0,
                )
            ),
            created_at=float(
                raw.get(
                    "created_at",
                    time.time(),
                )
            ),
            updated_at=float(
                raw.get(
                    "updated_at",
                    time.time(),
                )
            ),
        )


def create_execution_state(
    *,
    skill_id: str,
    objective: str,
    initial_state: dict[str, Any] | None = None,
    constraints: tuple[str, ...] = (),
    success_criteria: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> ExecutionState:
    return ExecutionState(
        skill=SkillSpecification(
            skill_id=str(
                skill_id
            ),
            objective=str(
                objective
            ),
            constraints=tuple(
                constraints
            ),
            success_criteria=tuple(
                success_criteria
            ),
            metadata=dict(
                metadata
                or {}
            ),
        ),
        state=dict(
            initial_state
            or {}
        ),
    )


__all__ = [
    "ExecutionState",
    "MAX_RECENT_EVENTS",
    "MAX_STATE_BYTES",
    "Observation",
    "STATE_SCHEMA_VERSION",
    "SkillSpecification",
    "StateUpdate",
    "create_execution_state",
]
