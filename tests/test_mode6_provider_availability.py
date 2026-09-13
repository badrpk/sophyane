from __future__ import annotations

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
