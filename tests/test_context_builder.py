from sophyane.context_builder import (
    ContextBuilder,
    ContextPacket,
)
from sophyane.providers.base import ProviderCapabilities


def test_browser_managed_context_preserves_complete_packet():
    packet = ContextPacket()
    packet.add(
        "goal",
        "BEGIN_GOAL_" + ("A" * 20000) + "_END_GOAL",
        priority=100,
        pinned=True,
    )
    packet.add(
        "artifact",
        "BEGIN_ARTIFACT_" + ("B" * 30000) + "_END_ARTIFACT",
        priority=80,
    )

    builder = ContextBuilder(
        ProviderCapabilities(
            provider_managed_context=True,
            provider_managed_output=True,
        )
    )

    result = builder.build(packet)

    assert result.max_input_chars is None
    assert result.omitted == ()
    assert "BEGIN_GOAL_" in result.text
    assert "_END_GOAL" in result.text
    assert "BEGIN_ARTIFACT_" in result.text
    assert "_END_ARTIFACT" in result.text


def test_unknown_capacity_does_not_invent_fixed_context_ceiling():
    packet = ContextPacket()
    packet.add(
        "request",
        "X" * 50000,
        pinned=True,
        priority=100,
    )

    result = ContextBuilder(
        ProviderCapabilities()
    ).build(packet)

    assert result.max_input_chars is None
    assert len(result.included) == 1
    assert result.omitted == ()
    assert "X" * 50000 in result.text


def test_numeric_provider_gets_calculated_input_budget():
    builder = ContextBuilder(
        ProviderCapabilities(
            context_window_tokens=2048,
            max_output_tokens=1024,
        ),
        chars_per_token=3,
        safety_ratio=0.08,
    )

    limit = builder.max_input_chars()

    assert limit is not None
    assert 3000 < limit < 5000


def test_numeric_budget_evicts_lowest_priority_first():
    packet = ContextPacket()
    packet.add(
        "goal",
        "IMMUTABLE_GOAL",
        priority=100,
        pinned=True,
    )
    packet.add(
        "important",
        "HIGH_PRIORITY_" + ("H" * 900),
        priority=80,
    )
    packet.add(
        "noise",
        "LOW_PRIORITY_" + ("L" * 2500),
        priority=1,
    )

    builder = ContextBuilder(
        ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        ),
        chars_per_token=3,
        safety_ratio=0.08,
    )

    result = builder.build(packet)

    assert "IMMUTABLE_GOAL" in result.text
    assert "HIGH_PRIORITY_" in result.text
    assert "LOW_PRIORITY_" not in result.text

    assert any(
        item.label == "noise"
        for item in result.omitted
    )


def test_pinned_goal_survives_even_when_it_exceeds_numeric_budget():
    packet = ContextPacket()
    packet.add(
        "goal",
        "G" * 10000,
        priority=100,
        pinned=True,
    )

    result = ContextBuilder(
        ProviderCapabilities(
            context_window_tokens=512,
            max_output_tokens=256,
        )
    ).build(packet)

    assert "G" * 10000 in result.text
    assert result.omitted == ()


def test_equal_priority_eviction_is_oldest_first():
    packet = ContextPacket()
    packet.add(
        "goal",
        "GOAL",
        priority=100,
        pinned=True,
    )
    packet.add(
        "old",
        "OLD_" + ("A" * 1500),
        priority=10,
    )
    packet.add(
        "new",
        "NEW_" + ("B" * 1500),
        priority=10,
    )

    result = ContextBuilder(
        ProviderCapabilities(
            context_window_tokens=768,
            max_output_tokens=256,
        )
    ).build(packet)

    assert result.omitted
    assert result.omitted[0].label == "old"


def test_render_keeps_original_order_after_admission():
    packet = ContextPacket()
    packet.add(
        "goal",
        "GOAL",
        priority=100,
        pinned=True,
    )
    packet.add(
        "middle",
        "MIDDLE",
        priority=80,
    )
    packet.add(
        "end",
        "END",
        priority=90,
    )

    result = ContextBuilder(
        ProviderCapabilities(
            provider_managed_context=True,
        )
    ).build(packet)

    assert result.text.index("[goal]") < result.text.index("[middle]")
    assert result.text.index("[middle]") < result.text.index("[end]")
