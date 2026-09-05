from __future__ import annotations


def test_explicit_mode3_runtime_config_never_calls_interactive_selector(
    monkeypatch,
):
    import sophyane.main as main
    import sophyane.startup_policy as policy

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    monkeypatch.setattr(
        main,
        "load_config",
        lambda: {
            "provider": "gemini",
            "model": "gemini-3.7-flash",
            "company": "Google Gemini",
            "timeout": 600,
        },
    )

    called = []

    def forbidden_selector():
        called.append(
            True
        )
        raise AssertionError(
            "interactive startup selector must not run"
        )

    monkeypatch.setattr(
        policy,
        "choose_startup_provider",
        forbidden_selector,
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

    config = main.load_runtime_config()

    assert not called
    assert config["provider"] == "local_gguf"
    assert config["model"] == "qwen-local-test"
    assert config["company"] == "Local"


def test_local_resolver_contains_no_interactive_input():
    import ast
    import inspect
    import textwrap

    from sophyane.startup_policy import (
        resolve_local_session_config,
    )

    source = textwrap.dedent(
        inspect.getsource(
            resolve_local_session_config
        )
    )

    tree = ast.parse(
        source
    )

    calls = []

    for node in ast.walk(
        tree
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        fn = node.func

        if isinstance(
            fn,
            ast.Name,
        ):
            calls.append(
                fn.id
            )

        elif isinstance(
            fn,
            ast.Attribute,
        ):
            calls.append(
                fn.attr
            )

    assert "input" not in calls
    assert "isatty" not in calls
    assert "_configured_clouds" not in calls
    assert "local_gguf" in source
