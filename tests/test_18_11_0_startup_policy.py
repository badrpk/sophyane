from __future__ import annotations


def test_nested_sophyane_command_is_local():
    from sophyane.runtime_input_patch import install_input_patch
    from sophyane import tui_v2

    install_input_patch()
    reply = tui_v2._simple_chat_reply("sophyane")
    assert reply is not None
    assert "already running" in reply.lower()


def test_help_is_local():
    from sophyane.runtime_input_patch import install_input_patch
    from sophyane import tui_v2

    install_input_patch()
    reply = tui_v2._simple_chat_reply("/help")
    assert reply is not None
    assert "/status" in reply


def test_startup_policy_module_imports():
    from sophyane.startup_policy import choose_startup_provider

    assert callable(choose_startup_provider)
