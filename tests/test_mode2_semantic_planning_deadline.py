from __future__ import annotations

import time

import pytest

import sophyane.sli_semantic_intelligence as semantic


class Chunk:
    def __init__(self) -> None:
        self.text = "interactive form validation user input"
        self.path = "sample.js::handler"
        self.source = "test"
        self.language = "javascript"
        self.weight = 1.0
        self.meta = {"placement": "function"}
        self.chunk_id = "chunk"


class Store:
    def __init__(self) -> None:
        self.chunks = {
            str(index): Chunk()
            for index in range(200)
        }


def test_semantic_planning_deadline_is_three_seconds():
    assert (
        semantic.SEMANTIC_PLANNING_DEADLINE_SECONDS
        == 3.0
    )


def test_retrieval_refuses_expired_deadline():
    plan = semantic.build_semantic_plan(
        "build an interactive form with validation"
    )

    assert plan.capabilities

    with pytest.raises(
        TimeoutError,
        match="semantic planning exceeded",
    ):
        semantic.retrieve_for_capability(
            Store(),
            plan,
            plan.capabilities[0],
            deadline=time.monotonic() - 0.001,
        )


def test_timeout_does_not_mark_requirement_covered():
    plan = semantic.build_semantic_plan(
        "build an interactive form with validation"
    )

    requirement = plan.capabilities[0]

    assert requirement.covered is False
    assert requirement.selected_ids == []

    with pytest.raises(TimeoutError):
        semantic.retrieve_for_capability(
            Store(),
            plan,
            requirement,
            deadline=time.monotonic() - 0.001,
        )

    assert requirement.covered is False
    assert requirement.selected_ids == []
