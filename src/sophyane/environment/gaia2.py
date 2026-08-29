"""Gaia2/ARE compatibility boundary.

This module intentionally does not import Meta ARE directly.

It converts ordinary dictionary-shaped scenario records into Sophyane's
environment abstraction. An external ARE installation can call these
conversion functions without giving this module package-install or network
authority.
"""

from __future__ import annotations

from typing import Any

from .model import (
    EnvironmentEvent,
    EnvironmentProfile,
    Scenario,
)


def scenario_from_gaia2_record(
    record: dict[str, Any],
) -> Scenario:
    scenario_id = str(
        record.get(
            "scenario_id",
            record.get(
                "id",
                "",
            ),
        )
    ).strip()

    if not scenario_id:
        raise ValueError(
            "Gaia2 scenario has no id"
        )

    objective = str(
        record.get(
            "objective",
            record.get(
                "task",
                record.get(
                    "prompt",
                    "",
                ),
            ),
        )
    ).strip()

    if not objective:
        raise ValueError(
            "Gaia2 scenario has no objective"
        )

    events = []

    for index, raw in enumerate(
        record.get(
            "events",
            [],
        )
        or []
    ):
        if not isinstance(
            raw,
            dict,
        ):
            continue

        events.append(
            EnvironmentEvent(
                event_id=str(
                    raw.get(
                        "event_id",
                        raw.get(
                            "id",
                            f"event-{index}",
                        ),
                    )
                ),
                at=float(
                    raw.get(
                        "at",
                        raw.get(
                            "time",
                            0.0,
                        ),
                    )
                ),
                kind=str(
                    raw.get(
                        "kind",
                        raw.get(
                            "type",
                            "event",
                        ),
                    )
                ),
                payload=dict(
                    raw.get(
                        "payload",
                        {},
                    )
                    or {}
                ),
                hidden=bool(
                    raw.get(
                        "hidden",
                        False,
                    )
                ),
                source=str(
                    raw.get(
                        "source",
                        "gaia2",
                    )
                ),
            )
        )

    dimensions = dict(
        record.get(
            "dimensions",
            {},
        )
        or {}
    )

    profile = (
        EnvironmentProfile(
            action_depth=int(
                dimensions.get(
                    "action_depth",
                    1,
                )
            ),
            event_rate=float(
                dimensions.get(
                    "event_rate",
                    len(events),
                )
            ),
            ambiguity=float(
                dimensions.get(
                    "ambiguity",
                    0.0,
                )
            ),
            noise=float(
                dimensions.get(
                    "noise",
                    0.0,
                )
            ),
            app_count=int(
                dimensions.get(
                    "app_count",
                    len(
                        record.get(
                            "apps",
                            [],
                        )
                        or []
                    )
                    or 1,
                )
            ),
            temporal_pressure=float(
                dimensions.get(
                    "temporal_pressure",
                    0.0,
                )
            ),
            actor_count=int(
                dimensions.get(
                    "actor_count",
                    len(
                        record.get(
                            "actors",
                            [],
                        )
                        or []
                    )
                    or 1,
                )
            ),
            hidden_state=float(
                dimensions.get(
                    "hidden_state",
                    0.0,
                )
            ),
        )
    )

    return Scenario(
        scenario_id=scenario_id,
        objective=objective,
        initial_state=dict(
            record.get(
                "initial_state",
                {},
            )
            or {}
        ),
        events=tuple(
            events
        ),
        profile=profile,
        metadata={
            "source":
                "gaia2",
            "raw_metadata":
                dict(
                    record.get(
                        "metadata",
                        {},
                    )
                    or {}
                ),
        },
        seed=int(
            record.get(
                "seed",
                0,
            )
        ),
        max_clock=float(
            record.get(
                "max_clock",
                record.get(
                    "timeout",
                    300.0,
                ),
            )
        ),
        max_steps=int(
            record.get(
                "max_steps",
                32,
            )
        ),
    )


def gaia2_result_record(
    *,
    scenario_id: str,
    success: bool,
    score: float,
    evidence: list[str],
    cost: float = 0.0,
) -> dict[str, Any]:
    return {
        "scenario_id":
            scenario_id,
        "scenario_result":
            bool(success),
        "score":
            float(score),
        "scenario_cost":
            max(
                0.0,
                float(
                    cost
                ),
            ),
        "evidence":
            list(
                evidence
            ),
        "runner":
            "sophyane",
    }
