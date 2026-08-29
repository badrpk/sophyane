"""Deterministic environment trace persistence and replay."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Callable

from .model import (
    EnvironmentAction,
    Scenario,
)
from .world import (
    ResearchEnvironment,
)


def save_trace(
    environment:
        ResearchEnvironment,
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
        "scenario_id":
            environment.scenario.scenario_id,
        "seed":
            environment.scenario.seed,
        "final_clock":
            environment.clock,
        "steps":
            environment.steps,
        "final_state":
            environment.state,
        "trace": [
            asdict(
                item
            )
            for item
            in environment.trace
        ],
    }

    target.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    return target


def load_trace(
    path: Path,
) -> dict:
    return json.loads(
        Path(
            path
        ).read_text(
            encoding="utf-8",
        )
    )


def replay_actions(
    scenario: Scenario,
    actions: tuple[
        EnvironmentAction,
        ...
    ],
) -> ResearchEnvironment:
    environment = (
        ResearchEnvironment(
            scenario
        )
    )

    for action in actions:
        environment.act(
            action
        )

    return environment


def compare_versions(
    scenario: Scenario,
    runners: dict[
        str,
        Callable[
            [ResearchEnvironment],
            None,
        ],
    ],
) -> dict[str, dict]:
    output = {}

    for version, runner in (
        runners.items()
    ):
        environment = (
            ResearchEnvironment(
                scenario
            )
        )

        runner(
            environment
        )

        output[
            version
        ] = {
            "state":
                environment.state,
            "clock":
                environment.clock,
            "steps":
                environment.steps,
            "trace_digests": [
                item.state_digest
                for item
                in environment.trace
            ],
        }

    return output
