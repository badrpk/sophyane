from __future__ import annotations

import time

import pytest

import sophyane.race_orchestrator as race

from sophyane.race_orchestrator import (
    _generate_provider_for_race,
)


class SlowLocalProvider:
    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        time.sleep(30.0)
        return "LATE LOCAL RESULT MUST NEVER ESCAPE"


class FastLocalProvider:
    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        return "fast-local"


class CloudProvider:
    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        return "cloud"


def test_race_local_result_is_rejected_at_hard_deadline(
    monkeypatch,
):
    # This test verifies the 10-second contract specifically.
    # Do not depend on a mutable module-global value left by another test.
    monkeypatch.setattr(
        race,
        "_LOCAL_RACE_APPLICATION_DEADLINE_SECONDS",
        10.0,
    )

    started = time.monotonic()

    with pytest.raises(
        TimeoutError,
        match=r"exceeded 10s.*discarded",
    ):
        _generate_provider_for_race(
            provider=SlowLocalProvider(),
            provider_id="local_gguf",
            prompt="test",
            system_prompt="test",
        )

    elapsed = time.monotonic() - started

    # Allow modest scheduler overhead on mobile Termux, but never the
    # provider's simulated 30-second completion.
    assert 9.5 <= elapsed < 11.5


def test_race_fast_local_result_remains_eligible():
    result = _generate_provider_for_race(
        provider=FastLocalProvider(),
        provider_id="local_gguf",
        prompt="test",
        system_prompt="test",
    )

    assert result == "fast-local"


def test_race_cloud_generation_is_not_given_local_deadline():
    result = _generate_provider_for_race(
        provider=CloudProvider(),
        provider_id="gemini",
        prompt="test",
        system_prompt="test",
    )

    assert result == "cloud"
