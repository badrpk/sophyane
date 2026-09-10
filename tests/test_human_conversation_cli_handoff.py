from __future__ import annotations

import sys

import pytest

import sophyane.cli_entry as cli_entry


@pytest.fixture
def isolated_cli_main(monkeypatch):
    monkeypatch.setattr(
        cli_entry,
        "_canonicalize_launch_workspace",
        lambda: None,
    )
    monkeypatch.setattr(
        cli_entry,
        "_runtime_identity",
        lambda: "Sophyane test runtime",
    )
    monkeypatch.setattr(
        cli_entry,
        "_start_local_server_if_needed",
        lambda: None,
    )
    monkeypatch.setattr(
        cli_entry,
        "_user_start_tips",
        lambda: "",
    )

    import sophyane.startup_update as startup_update

    monkeypatch.setattr(
        startup_update,
        "maybe_update_before_startup",
        lambda: None,
    )

    import sophyane.platform_kernel as platform_kernel

    monkeypatch.setattr(
        platform_kernel,
        "ensure_platform_filesystem",
        lambda: None,
    )

    patches = (
        (
            "sophyane.runtime_artifact_patch",
            "install_artifact_patch",
        ),
        (
            "sophyane.runtime_browser_patch",
            "install_browser_patch",
        ),
        (
            "sophyane.runtime_deep_agent_patch",
            "install_deep_agent_runtime",
        ),
        (
            "sophyane.runtime_input_patch",
            "install_input_patch",
        ),
        (
            "sophyane.runtime_interactive_patch",
            "install_runtime_patch",
        ),
        (
            "sophyane.runtime_interrupt_patch",
            "install_interrupt_patch",
        ),
        (
            "sophyane.runtime_intent_refinement_patch",
            "install_intent_refinement",
        ),
        (
            "sophyane.runtime_orchestration_patch",
            "install_orchestration_patch",
        ),
        (
            "sophyane.runtime_premium_asset_pipeline",
            "install_premium_asset_pipeline",
        ),
        (
            "sophyane.runtime_provider_context_patch",
            "install_provider_context_patch",
        ),
        (
            "sophyane.runtime_capability_acquisition_patch",
            "install_capability_acquisition_patch",
        ),
        (
            "sophyane.runtime_provider_error_patch",
            "install_provider_error_patch",
        ),
        (
            "sophyane.runtime_quality_escalation",
            "install_quality_escalation",
        ),
        (
            "sophyane.runtime_safety",
            "install_runtime_safety",
        ),
        (
            "sophyane.runtime_filesystem_capabilities_v20",
            "install_filesystem_capabilities_v20",
        ),
        (
            "sophyane.runtime_software_routing_guard",
            "install_software_routing_guard",
        ),
        (
            "sophyane.runtime_stagnation_patch",
            "install_stagnation_patch",
        ),
        (
            "sophyane.runtime_cursor_tab_patch",
            "install_cursor_tab_patch",
        ),
    )

    for module_name, function_name in patches:
        module = __import__(
            module_name,
            fromlist=[function_name],
        )
        monkeypatch.setattr(
            module,
            function_name,
            lambda: None,
        )

    monkeypatch.setattr(
        sys,
        "argv",
        ["sophyane"],
    )


def test_human_conversation_mode_calls_human_cli(
    monkeypatch,
    isolated_cli_main,
):
    human_calls = []
    v13_calls = []

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )
    monkeypatch.delenv(
        "SOPHYANE_SLI_CONTINUOUS",
        raising=False,
    )

    import sophyane.human_conversation_cli as human_cli
    import sophyane.v13_cli as v13_cli

    monkeypatch.setattr(
        human_cli,
        "main",
        lambda: human_calls.append(True) or 37,
    )
    monkeypatch.setattr(
        v13_cli,
        "main",
        lambda: v13_calls.append(True) or 91,
    )

    result = cli_entry.main()

    assert result == 37
    assert human_calls == [True]
    assert v13_calls == []


def test_explicit_human_conversation_skips_startup_selector(
    monkeypatch,
    isolated_cli_main,
):
    selector_calls = []
    human_calls = []

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )
    monkeypatch.delenv(
        "SOPHYANE_SLI_CONTINUOUS",
        raising=False,
    )

    import sophyane.startup_policy as startup_policy
    import sophyane.human_conversation_cli as human_cli

    monkeypatch.setattr(
        startup_policy,
        "choose_startup_provider",
        lambda: selector_calls.append(True),
    )
    monkeypatch.setattr(
        human_cli,
        "main",
        lambda: human_calls.append(True) or 0,
    )

    result = cli_entry.main()

    assert result == 0
    assert selector_calls == []
    assert human_calls == [True]
