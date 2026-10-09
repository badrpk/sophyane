import pytest

import sophyane.intelligence_authority as authority
import sophyane.race_orchestrator as race
import sophyane.task_compiler as task_compiler
import sophyane.unified_execution_kernel as kernel


@pytest.mark.parametrize(
    "message",
    [
        "hello",
        "Hello!",
        "hi",
        "hey",
        "good morning",
        "good afternoon",
        "good evening!",
    ],
)
def test_plain_greeting_falls_through_without_local_model(
    monkeypatch,
    tmp_path,
    message,
):
    calls = []

    # Make the direct-local branch deterministic and explicitly admissible.
    monkeypatch.setattr(
        authority,
        "local_reasoning_allowed",
        lambda: True,
    )
    monkeypatch.setattr(
        task_compiler,
        "estimate_difficulty",
        lambda _text: 1,
    )
    monkeypatch.setattr(
        task_compiler,
        "should_compile",
        lambda _text: False,
    )

    monkeypatch.setattr(
        race,
        "_single_provider",
        lambda **_kwargs: object(),
    )

    def fake_generate_provider_for_race(**kwargs):
        calls.append(kwargs)
        return "LOCAL_MODEL_SHOULD_NOT_BE_CALLED"

    monkeypatch.setattr(
        race,
        "_generate_provider_for_race",
        fake_generate_provider_for_race,
    )

    result = kernel.execute_text(
        message,
        workspace=tmp_path,
    )

    assert result is None
    assert calls == []


@pytest.mark.parametrize(
    "message",
    [
        "CURRENT_REQUEST",
        "ordinary chat request",
        "compare TCP and UDP",
        "IMMUTABLE_REQUEST_" + ("R" * 900) + "_END_REQUEST",
    ],
)
def test_unowned_low_difficulty_text_falls_through_without_local_model(
    monkeypatch,
    tmp_path,
    message,
):
    calls = []

    monkeypatch.setattr(
        authority,
        "local_reasoning_allowed",
        lambda: True,
    )
    monkeypatch.setattr(
        task_compiler,
        "estimate_difficulty",
        lambda _text: 1,
    )
    monkeypatch.setattr(
        task_compiler,
        "should_compile",
        lambda _text: False,
    )

    monkeypatch.setattr(
        race,
        "_single_provider",
        lambda **_kwargs: object(),
    )

    def fake_generate_provider_for_race(**kwargs):
        calls.append(kwargs)
        return "LOCAL_MODEL_SHOULD_NOT_OWN_THIS_REQUEST"

    monkeypatch.setattr(
        race,
        "_generate_provider_for_race",
        fake_generate_provider_for_race,
    )

    result = kernel.execute_text(
        message,
        workspace=tmp_path,
    )

    assert result is None
    assert calls == []
