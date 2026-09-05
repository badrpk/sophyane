from __future__ import annotations

import inspect


def test_mode3_runtime_identity_never_calls_interactive_selector(
    monkeypatch,
):
    import sophyane.cli_entry as entry
    import sophyane.startup_policy as policy

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    monkeypatch.setattr(
        entry,
        "load_config",
        lambda: {
            "provider": "gemini",
            "model": "gemini-3.7-flash",
        },
    )

    def forbidden():
        raise AssertionError(
            "interactive startup selector called"
        )

    monkeypatch.setattr(
        policy,
        "choose_startup_provider",
        forbidden,
    )

    monkeypatch.setattr(
        policy,
        "resolve_local_session_config",
        lambda: {
            "provider": "local_gguf",
            "model": "qwen-local-test",
            "company": "Local",
            "timeout": 300,
        },
    )

    identity = entry._runtime_identity()

    assert "qwen-local-test" in identity
    assert "gemini" not in identity.casefold()
    assert "google" not in identity.casefold()


def test_runtime_identity_source_has_no_mode3_interactive_selector():
    import sophyane.cli_entry as entry

    source = inspect.getsource(
        entry._runtime_identity
    )

    assert (
        "resolve_local_session_config"
        in source
    )

    assert (
        "choose_startup_provider"
        not in source
    )


def test_explicit_session_guard_exists_before_startup_selector():
    import sophyane.cli_entry as entry

    source = inspect.getsource(
        entry.main
    )

    assert (
        "explicit_session_mode"
        in source
    )

    assert (
        "and not explicit_session_mode"
        in source
    )
