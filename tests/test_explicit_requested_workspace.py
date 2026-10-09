from pathlib import Path

from sophyane.tui_v2 import ObservableTUI


def _bare_tui():
    tui = object.__new__(ObservableTUI)
    tui.active_workspace = None
    tui.active_request = ""
    tui.trace = False
    tui.progress = lambda _message: None
    return tui


def test_new_request_honors_explicit_absolute_workspace(tmp_path):
    requested = tmp_path / "harness_test_1"
    tui = _bare_tui()

    workspace = tui._workspace_for(
        False,
        request=(
            f"Create a workspace directory `{requested}`. "
            "Inside it, create todo.md and execute every step."
        ),
    )

    assert workspace == requested.resolve()
    assert tui.active_workspace == requested.resolve()
    assert requested.is_dir()




def test_mode6_work_in_tilde_directory_becomes_active_workspace(
    tmp_path,
    monkeypatch,
):
    """
    Natural Mode-6 workspace intent must establish the authority boundary.

    This is deliberately the wording used by the live failure.  The fix must
    select the requested directory; it must not permit ../ writes around an
    incorrectly selected workspace.
    """
    monkeypatch.setattr(
        Path,
        "home",
        staticmethod(lambda: tmp_path),
    )

    requested = tmp_path / "mode6_rsi_capability_test"
    requested.mkdir()

    tui = _bare_tui()

    workspace = tui._workspace_for(
        False,
        request=(
            "Work in ~/mode6_rsi_capability_test.\n\n"
            "Read README.md and telemetry.sphy.\n"
            "Create a reusable Python program named sphy_telemetry.py."
        ),
    )

    assert workspace == requested.resolve()
    assert tui.active_workspace == requested.resolve()


def test_new_request_without_explicit_workspace_remains_isolated():
    tui = _bare_tui()

    workspace = tui._workspace_for(
        False,
        request="Create a small project and verify it.",
    )

    expected_root = Path.home() / ".sophyane" / "workspaces"

    assert workspace.parent == expected_root
    assert tui.active_workspace == workspace


def test_new_request_absolute_script_uses_parent_as_workspace(tmp_path):
    requested = tmp_path / "poll_status.py"
    tui = _bare_tui()

    workspace = tui._workspace_for(
        False,
        request=(
            f"Create a script `{requested}` that outputs "
            "`STATUS: IN_PROGRESS` and run it."
        ),
    )

    assert workspace == requested.parent.resolve()
    assert tui.active_workspace == requested.parent.resolve()
