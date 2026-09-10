from sophyane.harness import (
    AgentHarness,
    ContextManager,
    ModelRegistry,
    VerificationResult,
)


def test_legacy_equal_priority_context_remains_fifo():
    context = ContextManager(
        max_chars=20,
    )

    context.add(
        "user",
        "1234567890",
    )
    context.add(
        "assistant",
        "abcdefghij",
    )

    rendered = context.render()

    assert "1234567890" not in rendered
    assert "abcdefghij" in rendered


def test_pinned_context_survives_budget_pressure():
    context = ContextManager(
        max_chars=30,
    )

    context.add(
        "goal",
        "IMMUTABLE_GOAL",
        priority=100,
        pinned=True,
    )

    context.add(
        "old",
        "x" * 20,
        priority=10,
    )

    context.add(
        "new",
        "y" * 20,
        priority=20,
    )

    rendered = context.render()

    assert "IMMUTABLE_GOAL" in rendered


def test_lowest_priority_is_evicted_before_higher_priority():
    # HIGH_VALUE + CURRENT_FAILURE fit together (42 chars by the
    # ContextManager accounting rule), while adding LOW_VALUE exceeds
    # the budget. This isolates priority eviction rather than testing
    # an impossible combination.
    context = ContextManager(
        max_chars=45,
    )

    context.add(
        "important",
        "HIGH_VALUE",
        priority=90,
    )

    context.add(
        "noise",
        "LOW_VALUE_" + ("x" * 20),
        priority=1,
    )

    context.add(
        "evidence",
        "CURRENT_FAILURE",
        priority=80,
    )

    rendered = context.render()

    assert "HIGH_VALUE" in rendered
    assert "CURRENT_FAILURE" in rendered
    assert "LOW_VALUE_" not in rendered


def test_pinned_context_can_exceed_soft_budget_instead_of_being_lost():
    goal = "G" * 100

    context = ContextManager(
        max_chars=10,
    )

    context.add(
        "goal",
        goal,
        priority=100,
        pinned=True,
    )

    assert goal in context.render()


def test_directly_populated_legacy_items_gain_default_policy():
    context = ContextManager(
        max_chars=100,
        items=[
            ("user", "legacy"),
        ],
    )

    assert "legacy" in context.render()

    context.add(
        "assistant",
        "new",
    )

    assert "legacy" in context.render()
    assert "new" in context.render()


def test_harness_keeps_original_goal_during_repair_turn():
    prompts: list[str] = []
    calls = {"count": 0}

    def backend(
        prompt: str,
        system: str,
    ) -> str:
        prompts.append(prompt)
        calls["count"] += 1

        if calls["count"] == 1:
            return "wrong"

        return "answer=42"

    models = ModelRegistry()
    models.register(
        "test-model",
        backend,
    )

    context = ContextManager(
        max_chars=120,
    )

    harness = AgentHarness(
        models,
        context=context,
        max_iterations=2,
    )

    result = harness.run(
        "ORIGINAL_IMMUTABLE_GOAL",
        lambda output: VerificationResult(
            "answer=42" in output,
            "must produce answer=42",
        ),
    )

    assert result.verified is True
    assert len(prompts) == 2

    assert "ORIGINAL_IMMUTABLE_GOAL" in prompts[0]
    assert "ORIGINAL_IMMUTABLE_GOAL" in prompts[1]
    assert "must produce answer=42" in prompts[1]
