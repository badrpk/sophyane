from __future__ import annotations

import pytest

from sophyane.providers.base import (
    Provider,
    ProviderMetadata,
)
from sophyane.providers.fallback import (
    FallbackProvider,
)


class RecordingProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="recording",
        display_name="Recording",
        default_model="recording",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(
        self,
        *,
        max_tokens: int = 4096,
        fail: bool = False,
    ) -> None:
        super().__init__(
            api_key="",
            model="recording",
            timeout=300,
            temperature=0.0,
            max_tokens=max_tokens,
        )

        self.fail = fail
        self.seen_budgets: list[int] = []

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        self.seen_budgets.append(
            self.max_tokens
        )

        if self.fail:
            raise RuntimeError(
                "synthetic provider failure"
            )

        return "OK"


def test_budget_reaches_real_child_and_restores() -> None:
    child = RecordingProvider(
        max_tokens=4096,
    )

    provider = FallbackProvider(
        [
            (
                "recording",
                child,
            )
        ],
        primary="recording",
    )

    assert provider.max_tokens == 4096
    assert child.max_tokens == 4096

    result = provider.generate_with_budget(
        "prompt",
        "system",
        max_tokens=256,
    )

    assert result == "OK"

    assert child.seen_budgets == [
        256,
    ]

    assert provider.max_tokens == 4096
    assert child.max_tokens == 4096


def test_budget_never_expands_smaller_child() -> None:
    child = RecordingProvider(
        max_tokens=128,
    )

    provider = FallbackProvider(
        [
            (
                "recording",
                child,
            )
        ]
    )

    provider.generate_with_budget(
        "prompt",
        "system",
        max_tokens=256,
    )

    assert child.seen_budgets == [
        128,
    ]

    assert child.max_tokens == 128


def test_budget_restores_after_failure() -> None:
    child = RecordingProvider(
        max_tokens=4096,
        fail=True,
    )

    provider = FallbackProvider(
        [
            (
                "recording",
                child,
            )
        ]
    )

    with pytest.raises(
        Exception
    ):
        provider.generate_with_budget(
            "prompt",
            "system",
            max_tokens=256,
        )

    assert child.seen_budgets == [
        256,
    ]

    assert provider.max_tokens == 4096
    assert child.max_tokens == 4096


def test_budget_applies_to_fallback_children() -> None:
    first = RecordingProvider(
        max_tokens=4096,
        fail=True,
    )

    second = RecordingProvider(
        max_tokens=1024,
    )

    provider = FallbackProvider(
        [
            (
                "first",
                first,
            ),
            (
                "second",
                second,
            ),
        ]
    )

    result = provider.generate_with_budget(
        "prompt",
        "system",
        max_tokens=256,
    )

    assert result == "OK"

    assert first.seen_budgets == [
        256,
    ]

    assert second.seen_budgets == [
        256,
    ]

    assert first.max_tokens == 4096
    assert second.max_tokens == 1024
