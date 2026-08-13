from __future__ import annotations

from dataclasses import dataclass

from sophyane.race_orchestrator import (
    _state_value,
)


@dataclass
class State:
    route: str = "harness_execution"
    success: bool = True


def test_mapping_state():
    state = {
        "route": "harness_execution",
        "success": True,
    }

    assert (
        _state_value(
            state,
            "route",
        )
        == "harness_execution"
    )


def test_object_state():
    state = State()

    assert (
        _state_value(
            state,
            "route",
        )
        == "harness_execution"
    )
