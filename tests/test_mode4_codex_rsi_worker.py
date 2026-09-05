from __future__ import annotations

import inspect

import sophyane.providers.codex_cli as codex_cli
import sophyane.recursive_evolution_controller as rsi


def test_codex_candidate_factory_is_readonly_workspace_worker(
    tmp_path,
    monkeypatch,
):
    captured = {}

    class FakeCodexProvider:
        provider_id = "codex_cli"

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        codex_cli,
        "CodexCliProvider",
        FakeCodexProvider,
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "codex-default",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_TIMEOUT",
        "240",
    )

    provider = (
        rsi.create_mode4_codex_candidate_provider(
            tmp_path,
        )
    )

    assert provider.provider_id == "codex_cli"
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["model"] == "codex-default"
    assert captured["timeout"] == 240


def test_supervised_rsi_selects_codex_worker_only_for_explicit_mode():
    source = inspect.getsource(
        rsi.run_supervised_mode3_nifdu_rsi
    )

    assert (
        "local_provider is None"
        in source
    )
    assert (
        '"codex_cli"'
        in source
    )
    assert (
        "create_mode4_codex_candidate_provider("
        in source
    )
    assert (
        'candidate_provider_id = "local_gguf"'
        in source
    )


def test_codex_worker_disables_optional_speculation():
    source = inspect.getsource(
        rsi.run_supervised_mode3_nifdu_rsi
    )

    assert (
        'candidate_provider_id == "local_gguf"'
        in source
    )
    assert (
        "mode4_initial_txq_policy.allow_speculative_readonly"
        in source
    )


def test_candidate_provider_identity_is_verified():
    source = inspect.getsource(
        rsi.run_supervised_mode3_nifdu_rsi
    )

    assert (
        "observed_candidate_provider"
        in source
    )
    assert (
        "candidate provider authority mismatch"
        in source
    )
