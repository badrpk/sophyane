from __future__ import annotations

import json
import pytest

from datetime import datetime, timedelta, timezone

from sophyane.providers.base import ProviderError


def test_quota_reset_time_is_parsed_and_provider_is_blocked(tmp_path, monkeypatch):
    from sophyane.providers import provider_availability as pa

    state = tmp_path / "availability.json"
    monkeypatch.setenv("SOPHYANE_PROVIDER_AVAILABILITY_FILE", str(state))

    now = datetime(2026, 9, 12, 18, 43, tzinfo=timezone(timedelta(hours=5)))

    pa.record_availability_failure(
        "codex_cli",
        ProviderError(
            "You've hit your usage limit. "
            "Please try again at 10:32 PM."
        ),
        now=now,
    )

    info = pa.provider_block_info(
        "codex_cli",
        now=now,
    )

    assert info is not None
    assert info["failure_class"] == "quota"
    assert info["retry_at"] == "2026-09-12T22:32:00+05:00"
    assert pa.provider_available("codex_cli", now=now) is False


def test_provider_becomes_available_after_retry_time(tmp_path, monkeypatch):
    from sophyane.providers import provider_availability as pa

    state = tmp_path / "availability.json"
    monkeypatch.setenv("SOPHYANE_PROVIDER_AVAILABILITY_FILE", str(state))

    tz = timezone(timedelta(hours=5))
    now = datetime(2026, 9, 12, 18, 43, tzinfo=tz)

    pa.record_availability_failure(
        "codex_cli",
        RuntimeError(
            "You've hit your usage limit. try again at 10:32 PM."
        ),
        now=now,
    )

    assert pa.provider_available(
        "codex_cli",
        now=datetime(2026, 9, 12, 22, 31, tzinfo=tz),
    ) is False

    assert pa.provider_available(
        "codex_cli",
        now=datetime(2026, 9, 12, 22, 32, tzinfo=tz),
    ) is True


def test_provider_cooldowns_are_independent(tmp_path, monkeypatch):
    from sophyane.providers import provider_availability as pa

    state = tmp_path / "availability.json"
    monkeypatch.setenv("SOPHYANE_PROVIDER_AVAILABILITY_FILE", str(state))

    tz = timezone(timedelta(hours=5))
    now = datetime(2026, 9, 12, 18, 43, tzinfo=tz)

    pa.record_availability_failure(
        "codex_cli",
        RuntimeError(
            "You've hit your usage limit. try again at 10:32 PM."
        ),
        now=now,
    )

    assert pa.provider_available("codex_cli", now=now) is False
    assert pa.provider_available("nifdu_browser", now=now) is True


def test_success_clears_previous_cooldown(tmp_path, monkeypatch):
    from sophyane.providers import provider_availability as pa

    state = tmp_path / "availability.json"
    monkeypatch.setenv("SOPHYANE_PROVIDER_AVAILABILITY_FILE", str(state))

    tz = timezone(timedelta(hours=5))
    now = datetime(2026, 9, 12, 18, 43, tzinfo=tz)

    pa.record_availability_failure(
        "nifdu_browser",
        RuntimeError(
            "ChatGPT usage limit reached; "
            "wait for your usage to reset at 10:32 PM."
        ),
        now=now,
    )

    assert pa.provider_available("nifdu_browser", now=now) is False

    pa.record_provider_success("nifdu_browser")

    assert pa.provider_available("nifdu_browser", now=now) is True


def test_mode6_skips_known_blocked_external_providers(
    tmp_path,
    monkeypatch,
):
    from sophyane.providers import provider_availability as pa
    from sophyane.providers.human_conversation import HumanConversationProvider

    state = tmp_path / "availability.json"
    monkeypatch.setenv("SOPHYANE_PROVIDER_AVAILABILITY_FILE", str(state))

    now = datetime.now().astimezone()

    pa.record_availability_failure(
        "codex_cli",
        RuntimeError(
            "You've hit your usage limit. "
            "try again at 11:59 PM."
        ),
        now=now,
    )

    pa.record_availability_failure(
        "nifdu_browser",
        RuntimeError(
            "ChatGPT usage limit reached; "
            "wait for your usage to reset at 11:59 PM."
        ),
        now=now,
    )

    attempted = []

    class Fake:
        def __init__(self, provider_id):
            self.provider_id = provider_id

    provider = HumanConversationProvider()

    monkeypatch.setattr(
        provider,
        "_create",
        lambda name: (
            attempted.append(name)
            or Fake(name)
        ),
    )

    result = provider.run_request(
        lambda candidate: candidate.provider_id
    )

    assert result == "local_gguf"
    assert attempted == ["local_gguf"]
    assert provider.last_provider == "local_gguf"


def test_mutation_nifdu_stale_quota_gets_one_bounded_live_revalidation(
    tmp_path,
    monkeypatch,
):
    """A stale browser quota must not suppress NIFDU forever until retry_at.

    Codex keeps its hard known-quota block.

    NIFDU is browser/session backed, so after the bounded revalidation
    interval a live probe must be allowed. If that probe discovers a
    different availability failure, that newer live state replaces the
    stale quota observation and prevents an immediate retry storm.
    """
    from datetime import datetime, timedelta, timezone

    from sophyane.providers.base import ProviderError
    from sophyane.providers.human_conversation import HumanConversationProvider
    from sophyane.rsi.authority import Operation
    from sophyane.rsi.availability import AvailabilityStore

    tz = timezone(timedelta(hours=5))

    class Clock:
        def __init__(self):
            self.value = datetime(2026, 9, 14, 13, 0, tzinfo=tz)

        def __call__(self):
            return self.value

    clock = Clock()
    state = tmp_path / "provider_availability.json"
    store = AvailabilityStore(state, clock=clock)

    # Both coding providers initially report a known quota window.
    store.failure(
        "codex_cli",
        RuntimeError(
            "You've hit your usage limit. try again at 4:28 PM."
        ),
    )
    store.failure(
        "nifdu_browser",
        RuntimeError(
            "ChatGPT usage limit reached; try again at 4:28 PM."
        ),
    )

    assert store.blocked("codex_cli") is True
    assert store.blocked("nifdu_browser") is True

    # The cached browser observation is now old enough for one bounded
    # live revalidation, even though the advertised reset is later.
    clock.value += timedelta(minutes=20)

    attempted: list[str] = []

    class FakeProvider:
        def __init__(self, provider_id: str):
            self.provider_id = provider_id

    provider = HumanConversationProvider()
    provider._mutation_availability = store

    def fake_create(name: str):
        attempted.append(name)
        return FakeProvider(name)

    monkeypatch.setattr(provider, "_create", fake_create)

    def request(candidate):
        if candidate.provider_id == "nifdu_browser":
            raise RuntimeError(
                "ChatGPT is blocked by a browser verification challenge; "
                "NIFDU CDP transport is ready but ChatGPT is not interactive."
            )
        raise AssertionError(
            f"blocked provider unexpectedly executed: {candidate.provider_id}"
        )

    with pytest.raises(
        ProviderError,
        match="DEFERRED_NO_CODING_PROVIDER",
    ):
        provider.run_request(
            request,
            operation=Operation.SOPHYANE_SOURCE_MUTATION,
        )

    # Codex remains hard-blocked by its known quota.
    # NIFDU must receive exactly one live revalidation attempt.
    assert attempted == ["nifdu_browser"]

    # The live challenge is not quota. It becomes the newer bounded
    # availability observation.
    payload = json.loads(state.read_text(encoding="utf-8"))
    nifdu = payload["providers"]["nifdu_browser"]

    assert nifdu["failure_class"] == "availability"
    assert nifdu["retry_at"] is None
    assert nifdu["probe_after"] is not None

    attempted.clear()

    # An immediate second request must respect the new short availability
    # cooldown rather than probing NIFDU repeatedly.
    with pytest.raises(
        ProviderError,
        match="DEFERRED_NO_CODING_PROVIDER",
    ):
        provider.run_request(
            request,
            operation=Operation.SOPHYANE_SOURCE_MUTATION,
        )

    assert attempted == []
