"""Deterministic asynchronous Sophyane world."""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import random
from typing import Any

from .model import (
    EnvironmentAction,
    EnvironmentEvent,
    Scenario,
    TraceEntry,
)

from .execution_state import (
    ExecutionState,
    create_execution_state,
)


def state_digest(
    state: dict[str, Any],
) -> str:
    payload = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(
        payload
    ).hexdigest()[:24]


class ResearchEnvironment:
    """A seeded stateful environment whose clock advances independently."""

    def __init__(
        self,
        scenario: Scenario,
    ) -> None:
        self.scenario = scenario
        self.state = copy.deepcopy(
            scenario.initial_state
        )

        # SOPHYANE_EXPLICIT_EXECUTION_STATE_V1
        #
        # Current execution state is authoritative for model-facing context.
        # Historical traces remain audit/replay artifacts only.
        #
        self.execution_state: ExecutionState = (
            create_execution_state(
                skill_id=scenario.scenario_id,
                objective=scenario.objective,
                initial_state=self.state,
                constraints=tuple(
                    scenario.metadata.get(
                        "constraints",
                        (),
                    )
                    or ()
                ),
                success_criteria=tuple(
                    scenario.metadata.get(
                        "success_criteria",
                        (),
                    )
                    or ()
                ),
                metadata={
                    "seed":
                        scenario.seed,
                },
            )
        )
        self.clock = 0.0
        self.steps = 0

        self._random = random.Random(
            scenario.seed
        )

        self._queue: list[
            tuple[
                float,
                int,
                EnvironmentEvent,
            ]
        ] = []

        self._sequence = 0
        self.trace: list[
            TraceEntry
        ] = []

        for event in scenario.events:
            self.schedule(
                event
            )

        self._record(
            "world_start",
            "environment",
            {
                "scenario_id":
                    scenario.scenario_id,
                "objective":
                    scenario.objective,
                "seed":
                    scenario.seed,
            },
        )

    def _record(
        self,
        kind: str,
        actor: str,
        payload: dict[str, Any],
    ) -> None:
        self._sequence += 1

        self.trace.append(
            TraceEntry(
                sequence=self._sequence,
                clock=self.clock,
                kind=kind,
                actor=actor,
                payload=copy.deepcopy(
                    payload
                ),
                state_digest=state_digest(
                    self.state
                ),
            )
        )

    def schedule(
        self,
        event: EnvironmentEvent,
    ) -> None:
        self._sequence += 1

        heapq.heappush(
            self._queue,
            (
                float(event.at),
                self._sequence,
                event,
            ),
        )

    def visible_state(
        self,
    ) -> dict[str, Any]:
        hidden = set(
            self.state.get(
                "_hidden_keys",
                [],
            )
        )

        return {
            key: copy.deepcopy(value)
            for key, value
            in self.state.items()
            if (
                not key.startswith("_")
                and key not in hidden
            )
        }

    def hidden_state(
        self,
    ) -> dict[str, Any]:
        hidden = set(
            self.state.get(
                "_hidden_keys",
                [],
            )
        )

        return {
            key: copy.deepcopy(value)
            for key, value
            in self.state.items()
            if key in hidden
        }

    def _apply_event(
        self,
        event: EnvironmentEvent,
    ) -> None:
        operation = str(
            event.payload.get(
                "operation",
                "merge",
            )
        )

        data = event.payload.get(
            "data",
            {},
        )

        if operation == "merge":
            if isinstance(
                data,
                dict,
            ):
                self.state.update(
                    copy.deepcopy(
                        data
                    )
                )

        elif operation == "increment":
            key = str(
                event.payload.get(
                    "key",
                    "",
                )
            )

            amount = float(
                event.payload.get(
                    "amount",
                    1,
                )
            )

            current = self.state.get(
                key,
                0,
            )

            self.state[key] = (
                current
                + amount
            )

        elif operation == "append":
            key = str(
                event.payload.get(
                    "key",
                    "",
                )
            )

            self.state.setdefault(
                key,
                [],
            )

            self.state[key].append(
                copy.deepcopy(
                    event.payload.get(
                        "value"
                    )
                )
            )

        elif operation == "delete":
            key = str(
                event.payload.get(
                    "key",
                    "",
                )
            )

            self.state.pop(
                key,
                None,
            )

        else:
            raise ValueError(
                "unsupported event operation: "
                + operation
            )

        self.execution_state.replace_state(
            self.state,
            reason=(
                "environment_event:"
                + event.event_id
            ),
        )

        self.execution_state.observe(
            source=event.source,
            kind=event.kind,
            payload={
                "event_id":
                    event.event_id,
                "visible_state":
                    self.visible_state(),
            },
            observed_at=self.clock,
        )

        self._record(
            "event",
            event.source,
            {
                "event_id":
                    event.event_id,
                "event_kind":
                    event.kind,
                "hidden":
                    event.hidden,
                "payload":
                    event.payload,
            },
        )

    def advance(
        self,
        delta: float,
    ) -> tuple[
        EnvironmentEvent,
        ...
    ]:
        if delta < 0:
            raise ValueError(
                "time cannot move backwards"
            )

        target = min(
            self.scenario.max_clock,
            self.clock
            + float(delta),
        )

        applied: list[
            EnvironmentEvent
        ] = []

        while (
            self._queue
            and self._queue[0][0]
            <= target
        ):
            at, _, event = (
                heapq.heappop(
                    self._queue
                )
            )

            self.clock = max(
                self.clock,
                at,
            )

            self._apply_event(
                event
            )

            applied.append(
                event
            )

        self.clock = target

        self._record(
            "clock",
            "environment",
            {
                "delta":
                    float(delta),
            },
        )

        return tuple(
            applied
        )

    def act(
        self,
        action: EnvironmentAction,
    ) -> None:
        if self.steps >= (
            self.scenario.max_steps
        ):
            raise RuntimeError(
                "scenario step budget exhausted"
            )

        self.steps += 1

        requested_at = (
            self.clock
            if action.at is None
            else float(action.at)
        )

        if requested_at > self.clock:
            self.advance(
                requested_at
                - self.clock
            )

        operation = str(
            action.payload.get(
                "operation",
                "merge",
            )
        )

        data = action.payload.get(
            "data",
            {},
        )

        if operation == "merge":
            if isinstance(
                data,
                dict,
            ):
                self.state.update(
                    copy.deepcopy(
                        data
                    )
                )

        elif operation == "set":
            self.state[
                str(
                    action.payload[
                        "key"
                    ]
                )
            ] = copy.deepcopy(
                action.payload.get(
                    "value"
                )
            )

        elif operation == "append":
            key = str(
                action.payload[
                    "key"
                ]
            )

            self.state.setdefault(
                key,
                [],
            )

            self.state[key].append(
                copy.deepcopy(
                    action.payload.get(
                        "value"
                    )
                )
            )

        elif operation == "delete":
            self.state.pop(
                str(
                    action.payload[
                        "key"
                    ]
                ),
                None,
            )

        elif operation == "noop":
            pass

        else:
            raise ValueError(
                "unsupported action operation: "
                + operation
            )

        self.execution_state.replace_state(
            self.state,
            reason=(
                "action:"
                + action.action
            ),
        )

        self.execution_state.observe(
            source=action.actor,
            kind=(
                "action_result:"
                + action.action
            ),
            payload={
                "visible_state":
                    self.visible_state(),
            },
            observed_at=self.clock,
        )

        self._record(
            "action",
            action.actor,
            {
                "action":
                    action.action,
                "payload":
                    action.payload,
            },
        )

    def finished(
        self,
    ) -> bool:
        return bool(
            self.clock
            >= self.scenario.max_clock
            or self.steps
            >= self.scenario.max_steps
        )

    def pending_events(
        self,
    ) -> int:
        return len(
            self._queue
        )
