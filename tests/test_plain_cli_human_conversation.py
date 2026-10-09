from __future__ import annotations

import builtins
import sys

import pytest

import sophyane.cli_entry as cli_entry
import sophyane.human_conversation_cli as human_cli


_INSTALLERS = (
    ("sophyane.runtime_artifact_patch", "install_artifact_patch"),
    ("sophyane.runtime_browser_patch", "install_browser_patch"),
    ("sophyane.runtime_deep_agent_patch", "install_deep_agent_runtime"),
    ("sophyane.runtime_input_patch", "install_input_patch"),
    ("sophyane.runtime_interactive_patch", "install_runtime_patch"),
    ("sophyane.runtime_interrupt_patch", "install_interrupt_patch"),
    ("sophyane.runtime_intent_refinement_patch", "install_intent_refinement"),
    ("sophyane.runtime_orchestration_patch", "install_orchestration_patch"),
    ("sophyane.runtime_premium_asset_pipeline", "install_premium_asset_pipeline"),
    ("sophyane.runtime_provider_context_patch", "install_provider_context_patch"),
    ("sophyane.runtime_capability_acquisition_patch", "install_capability_acquisition_patch"),
    ("sophyane.runtime_provider_error_patch", "install_provider_error_patch"),
    ("sophyane.runtime_quality_escalation", "install_quality_escalation"),
    ("sophyane.runtime_safety", "install_runtime_safety"),
    ("sophyane.runtime_filesystem_capabilities_v20", "install_filesystem_capabilities_v20"),
    ("sophyane.runtime_software_routing_guard", "install_software_routing_guard"),
    ("sophyane.runtime_stagnation_patch", "install_stagnation_patch"),
    ("sophyane.runtime_cursor_tab_patch", "install_cursor_tab_patch"),
)


@pytest.fixture
def isolated_entry(monkeypatch):
    monkeypatch.setattr(cli_entry, "_canonicalize_launch_workspace", lambda: None)
    monkeypatch.setattr(cli_entry, "_runtime_identity", lambda: "Sophyane test runtime")
    monkeypatch.setattr(cli_entry, "_start_local_server_if_needed", lambda: None)
    monkeypatch.setattr(cli_entry, "_user_start_tips", lambda: "")

    import sophyane.platform_kernel as platform_kernel
    import sophyane.startup_update as startup_update

    monkeypatch.setattr(platform_kernel, "ensure_platform_filesystem", lambda: None)
    monkeypatch.setattr(startup_update, "maybe_update_before_startup", lambda: None)

    for module_name, function_name in _INSTALLERS:
        module = __import__(module_name, fromlist=[function_name])
        monkeypatch.setattr(module, function_name, lambda: None)

    monkeypatch.delenv("SOPHYANE_SESSION_MODE", raising=False)
    monkeypatch.delenv("SOPHYANE_SLI_CONTINUOUS", raising=False)
    monkeypatch.setattr(sys, "argv", ["sophyane"])


def test_plain_no_argument_entry_delegates_without_startup_selector(
    monkeypatch,
    isolated_entry,
):
    selector_calls = []
    human_calls = []

    import sophyane.startup_policy as startup_policy

    monkeypatch.setattr(
        startup_policy,
        "choose_startup_provider",
        lambda: selector_calls.append(True),
    )
    monkeypatch.setattr(
        human_cli,
        "main",
        lambda: human_calls.append(True) or 23,
    )

    assert cli_entry.main() == 23
    assert selector_calls == []
    assert human_calls == [True]


def test_human_cli_welcome_is_concise_and_first_turn_reaches_conversation(
    monkeypatch,
    capsys,
):
    calls = []
    values = iter(("Plan the next step", "/quit"))

    class Result:
        reply = "I can help with that."

    def fake_turn(text, **kwargs):
        calls.append((text, kwargs))
        return Result()

    monkeypatch.setattr(human_cli, "conversation_turn", fake_turn)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(values))
    monkeypatch.setattr(sys, "argv", ["sophyane-human-chat"])

    assert human_cli.main() == 0

    output = capsys.readouterr().out
    assert "Sophyane\n" in output
    assert "Hello. I'm ready." in output
    assert "What would you like us to accomplish?" in output
    assert "Mode 1" not in output
    assert calls[0][0] == "Plan the next step"


def test_human_cli_eof_and_quit_exit_cleanly(monkeypatch):
    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": (_ for _ in ()).throw(EOFError),
    )
    monkeypatch.setattr(sys, "argv", ["sophyane-human-chat"])
    assert human_cli.main() == 0
