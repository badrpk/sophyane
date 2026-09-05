"""Regression coverage for TUI post-build environment access."""

import os


def test_tui_post_build_environment_has_os_module_global(
    monkeypatch,
):
    from sophyane import tui

    monkeypatch.delenv(
        "SOPHYANE_AUTO_POST_BUILD_MENU",
        raising=False,
    )

    # run_with_post_build_menu() is nested inside run_grok_style_tui()
    # and therefore resolves ``os`` from this module's global namespace.
    # This exact lookup previously raised NameError after a successful
    # browser artifact build and preview.
    assert tui.os is os
    assert (
        eval(
            'os.environ.get("SOPHYANE_AUTO_POST_BUILD_MENU")',
            tui.__dict__,
        )
        is None
    )


def test_tui_post_build_environment_reads_opt_in_flag(
    monkeypatch,
):
    from sophyane import tui

    monkeypatch.setenv(
        "SOPHYANE_AUTO_POST_BUILD_MENU",
        "1",
    )

    assert (
        eval(
            'os.environ.get("SOPHYANE_AUTO_POST_BUILD_MENU")',
            tui.__dict__,
        )
        == "1"
    )
