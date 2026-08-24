import inspect

import pytest

import sophyane.main as main
import sophyane.tui_v2 as tui


def test_helper_imports_authoritative_provider_factory() -> None:
    source = inspect.getsource(
        tui._create_provider_for_observable_tui
    )

    assert (
        "from sophyane.main import"
        in source
    )

    assert (
        "create_provider as authoritative_create_provider"
        in source
    )


def test_sli_only_provider_refusal_becomes_none(
    monkeypatch,
) -> None:
    def refuse(
        _config,
    ):
        raise RuntimeError(
            "SLI-only session forbids LLM provider construction. "
            "Route this request through the SLI execution path."
        )

    monkeypatch.setattr(
        main,
        "create_provider",
        refuse,
    )

    assert (
        tui
        ._create_provider_for_observable_tui(
            {}
        )
        is None
    )


def test_normal_provider_is_preserved(
    monkeypatch,
) -> None:
    provider = object()

    monkeypatch.setattr(
        main,
        "create_provider",
        lambda _config:
            provider,
    )

    assert (
        tui
        ._create_provider_for_observable_tui(
            {}
        )
        is provider
    )


def test_unrelated_runtime_error_is_not_hidden(
    monkeypatch,
) -> None:
    def fail(
        _config,
    ):
        raise RuntimeError(
            "arbitrary provider failure"
        )

    monkeypatch.setattr(
        main,
        "create_provider",
        fail,
    )

    with pytest.raises(
        RuntimeError,
        match="arbitrary provider failure",
    ):
        (
            tui
            ._create_provider_for_observable_tui(
                {}
            )
        )


def test_non_runtime_error_is_not_hidden(
    monkeypatch,
) -> None:
    def fail(
        _config,
    ):
        raise ValueError(
            "bad config"
        )

    monkeypatch.setattr(
        main,
        "create_provider",
        fail,
    )

    with pytest.raises(
        ValueError,
        match="bad config",
    ):
        (
            tui
            ._create_provider_for_observable_tui(
                {}
            )
        )


def test_run_observable_tui_uses_helper() -> None:
    source = inspect.getsource(
        tui.run_observable_tui
    )

    assert (
        "_create_provider_for_observable_tui(config)"
        in source
    )

    assert (
        "create_provider(config)"
        not in source
    )
