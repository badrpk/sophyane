import inspect

from sophyane import tui


def test_tui_reapplies_semantic_repair_after_html_recovery_wrappers():
    source = inspect.getsource(tui.run_grok_style_tui)

    semantic_call = source.rindex("install_snake_semantic_repair()")
    html_policy_call = source.index("install_html_repair_policy()")
    partial_recovery_call = source.index("install_browser_partial_recovery()")
    workspace_call = source.index("install_workspace_attachment()")

    assert semantic_call > html_policy_call
    assert semantic_call > partial_recovery_call
    assert semantic_call > workspace_call
