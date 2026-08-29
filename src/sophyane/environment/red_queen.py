"""Red Queen mutations for dynamic Sophyane environments."""

from __future__ import annotations

from dataclasses import replace
import random

from .model import (
    EnvironmentEvent,
    EnvironmentProfile,
    Scenario,
)


class EnvironmentRedQueen:
    def __init__(
        self,
        *,
        seed: int = 0,
    ) -> None:
        self.random = (
            random.Random(
                seed
            )
        )

    def mutate(
        self,
        scenario: Scenario,
        *,
        generation: int,
    ) -> Scenario:
        generation = max(
            1,
            int(
                generation
            ),
        )

        profile = (
            scenario.profile
        )

        pressure = min(
            1.0,
            (
                profile.temporal_pressure
                + 0.08
                * generation
            ),
        )

        ambiguity = min(
            1.0,
            (
                profile.ambiguity
                + 0.05
                * generation
            ),
        )

        noise = min(
            1.0,
            (
                profile.noise
                + 0.04
                * generation
            ),
        )

        hidden = min(
            1.0,
            (
                profile.hidden_state
                + 0.03
                * generation
            ),
        )

        event_time = min(
            scenario.max_clock
            * 0.8,
            max(
                1.0,
                scenario.max_clock
                * (
                    0.25
                    + self.random.random()
                    * 0.35
                ),
            ),
        )

        adversarial_event = (
            EnvironmentEvent(
                event_id=(
                    "red-queen-"
                    + str(
                        generation
                    )
                ),
                at=event_time,
                kind=(
                    "adversarial_change"
                ),
                payload={
                    "operation":
                        "increment",
                    "key":
                        "environment_pressure",
                    "amount":
                        generation,
                },
                hidden=bool(
                    hidden
                    >= 0.5
                ),
                source="red_queen",
            )
        )

        return replace(
            scenario,
            scenario_id=(
                scenario.scenario_id
                + "-rq"
                + str(
                    generation
                )
            ),
            events=(
                tuple(
                    scenario.events
                )
                + (
                    adversarial_event,
                )
            ),
            profile=(
                EnvironmentProfile(
                    action_depth=min(
                        5,
                        profile.action_depth
                        + (
                            1
                            if generation >= 2
                            else 0
                        ),
                    ),
                    event_rate=min(
                        10.0,
                        profile.event_rate
                        + 0.5
                        * generation,
                    ),
                    ambiguity=ambiguity,
                    noise=noise,
                    app_count=min(
                        8,
                        profile.app_count
                        + (
                            1
                            if generation >= 3
                            else 0
                        ),
                    ),
                    temporal_pressure=(
                        pressure
                    ),
                    actor_count=min(
                        8,
                        profile.actor_count
                        + (
                            1
                            if generation >= 2
                            else 0
                        ),
                    ),
                    hidden_state=hidden,
                )
            ),
            seed=(
                scenario.seed
                + generation
            ),
        )
