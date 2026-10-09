from pathlib import Path
from types import SimpleNamespace

from sophyane import human_conversation_cli as cli


def _run(monkeypatch, inputs, disposition, execute):
    values = iter([*inputs, "/exit"])
    monkeypatch.setattr(cli, "_read_atomic_submission", lambda _prompt: next(values))
    monkeypatch.setattr("sys.argv", ["sophyane-human-chat"])
    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: SimpleNamespace(
            reply="INTELLIGENCE_REPLY",
            semantic_disposition=disposition,
        ),
    )
    monkeypatch.setattr(cli, "_execute_repository_request", execute)
    return cli.main()


def test_actionable_mission_is_intelligence_first_and_preserves_original(monkeypatch):
    events = []

    def conversation(text, **kwargs):
        events.append(("conversation", text))
        return SimpleNamespace(reply="route", semantic_disposition="actionable_mission")

    def execute(text, **kwargs):
        events.append(("execute", text))
        return cli._CompletedRepositoryExecution("done")

    monkeypatch.setattr(cli, "conversation_turn", conversation)
    _run_with = iter(["/exit"])
    monkeypatch.setattr(cli, "_read_atomic_submission", lambda _prompt: next(_run_with))
    monkeypatch.setattr("sys.argv", ["sophyane-human-chat"])
    # The helper's first call must be replaced with the real event recorder.
    values = iter(["make snake game and open in browser", "/exit"])
    monkeypatch.setattr(cli, "_read_atomic_submission", lambda _prompt: next(values))
    monkeypatch.setattr(cli, "_execute_repository_request", execute)

    assert cli.main() == 0
    assert events == [
        ("conversation", "make snake game and open in browser"),
        ("execute", "make snake game and open in browser"),
    ]


def test_unrelated_actionable_mission_uses_same_structured_route(monkeypatch):
    calls = []
    values = iter(["prepare a small calculator application for me", "/exit"])
    monkeypatch.setattr(cli, "_read_atomic_submission", lambda _prompt: next(values))
    monkeypatch.setattr("sys.argv", ["sophyane-human-chat"])
    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: SimpleNamespace(reply="route", semantic_disposition="actionable_mission"),
    )
    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda text, **kwargs: (
            calls.append(text)
            or cli._CompletedRepositoryExecution("done")
        ),
    )

    assert cli.main() == 0
    assert calls == ["prepare a small calculator application for me"]


def test_conversation_clarification_and_missing_disposition_never_execute(monkeypatch):
    for disposition in ("conversation", "clarification", None, "not-a-disposition"):
        calls = []
        _run(
            monkeypatch,
            ["what is Python?"],
            disposition,
            lambda text, **kwargs: calls.append(text),
        )
        assert calls == []


def test_incomplete_mission_keeps_original_for_proceed(monkeypatch):
    values = iter(["prepare a calculator", "proceed", "/exit"])
    monkeypatch.setattr(cli, "_read_atomic_submission", lambda _prompt: next(values))
    monkeypatch.setattr("sys.argv", ["sophyane-human-chat"])
    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: SimpleNamespace(reply="route", semantic_disposition="actionable_mission"),
    )
    calls = []

    def execute(text, **kwargs):
        calls.append(text)
        return "needs more detail" if len(calls) == 1 else cli._CompletedRepositoryExecution("done")

    monkeypatch.setattr(cli, "_execute_repository_request", execute)
    assert cli.main() == 0
    assert calls == ["prepare a calculator", "prepare a calculator\nproceed"]


def test_routing_has_no_phrase_specific_game_or_browser_branch():
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "snake" not in source.casefold()
    assert "calculator" not in source.casefold()


def test_admitted_exact_write_uses_existing_verified_capability_before_second_provider(
    monkeypatch,
    tmp_path,
):
    """After semantic admission, an existing verified capability wins before
    Sophyane spends another intelligence/provider resource.
    """
    request = (
        "Create proof.txt containing exactly: "
        "SOPHYANE_EXISTING_CAPABILITY"
    )

    provider_calls = []

    def forbidden_create_provider(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError(
            "existing deterministic capability unnecessarily acquired provider"
        )

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        forbidden_create_provider,
    )

    result = cli._execute_repository_request(
        request,
        workspace=tmp_path,
    )

    assert provider_calls == []
    assert (
        tmp_path / "proof.txt"
    ).read_bytes() == b"SOPHYANE_EXISTING_CAPABILITY"

    assert isinstance(
        result,
        cli._CompletedRepositoryExecution,
    )

    assert "filesystem.write_exact_verified" in str(result)


def test_pre_provider_fast_path_does_not_enter_unified_execution_kernel(
    monkeypatch,
    tmp_path,
):
    """Provider-resource optimization must use only the deterministic dispatcher.

    The full unified kernel contains side-effectful local coding and therefore
    must not be used merely to decide whether another provider is necessary.
    """
    request = (
        "Create deterministic_probe.txt containing exactly: "
        "DETERMINISTIC_ONLY"
    )

    def forbidden_kernel(*args, **kwargs):
        raise AssertionError(
            "pre-provider fast path entered the full unified execution kernel"
        )

    def forbidden_provider(*args, **kwargs):
        raise AssertionError(
            "verified deterministic capability unnecessarily acquired provider"
        )

    monkeypatch.setattr(
        "sophyane.unified_execution_kernel.execute_request",
        forbidden_kernel,
    )
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        forbidden_provider,
    )

    result = cli._execute_repository_request(
        request,
        workspace=tmp_path,
    )

    assert (
        tmp_path / "deterministic_probe.txt"
    ).read_bytes() == b"DETERMINISTIC_ONLY"

    assert isinstance(
        result,
        cli._CompletedRepositoryExecution,
    )
    assert "filesystem.write_exact_verified" in str(result)


def test_unsupported_deterministic_request_falls_through_to_provider(
    monkeypatch,
    tmp_path,
):
    """None from the deterministic dispatcher preserves provider fallback."""
    request = "implement a novel parser architecture in this workspace"

    provider_attempted = []

    class ProviderBoundaryReached(RuntimeError):
        pass

    def provider_boundary(*args, **kwargs):
        provider_attempted.append(True)
        raise ProviderBoundaryReached("PROVIDER_BOUNDARY_REACHED")

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        provider_boundary,
    )

    import pytest

    with pytest.raises(
        ProviderBoundaryReached,
        match="PROVIDER_BOUNDARY_REACHED",
    ):
        cli._execute_repository_request(
            request,
            workspace=tmp_path,
        )

    assert provider_attempted == [True]


def test_failed_claimed_deterministic_action_does_not_execute_again_via_provider(
    monkeypatch,
    tmp_path,
):
    """A claimed deterministic action that fails is terminal for that attempt.

    Falling through after a side-effectful failed attempt could duplicate a
    mutation through the provider/adaptive executor.
    """
    from sophyane.capability_executors import CapabilityExecution

    request = "perform deterministic claimed mutation"

    def failed_capability(message, *, workspace=None):
        assert message == request
        return CapabilityExecution(
            ok=False,
            capability_id="test.claimed_deterministic_failure",
            text="DETERMINISTIC_ACTION_FAILED",
            data={
                "ok": False,
                "runtime_executed_action": True,
                "deterministic": True,
                "provider_bypassed": True,
            },
        )

    provider_calls = []

    def forbidden_provider(*args, **kwargs):
        provider_calls.append(True)
        raise AssertionError(
            "failed claimed deterministic action was executed again via provider"
        )

    monkeypatch.setattr(
        "sophyane.capability_executors.execute_deterministic_capability",
        failed_capability,
    )
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        forbidden_provider,
    )

    result = cli._execute_repository_request(
        request,
        workspace=tmp_path,
    )

    assert provider_calls == []
    assert "test.claimed_deterministic_failure" in str(result)
    assert "DETERMINISTIC_ACTION_FAILED" in str(result)
