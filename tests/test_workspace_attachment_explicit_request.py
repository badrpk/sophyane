from pathlib import Path

from sophyane import tui_v2
from sophyane.workspace_attachment import install_workspace_attachment


def test_attachment_wrapper_preserves_explicit_new_workspace(tmp_path):
    original = tui_v2.ObservableTUI._workspace_for

    try:
        install_workspace_attachment()

        tui = object.__new__(tui_v2.ObservableTUI)
        tui.active_workspace = tmp_path / "launch-project"
        tui.active_workspace.mkdir()
        tui.active_request = "Existing project"
        tui.trace = False
        tui.progress = lambda _message: None

        requested = tmp_path / "external" / "poll_status.py"

        workspace = tui._workspace_for(
            False,
            request=f"Create a script `{requested}` and run it.",
        )

        assert workspace == requested.parent.resolve()
        assert tui.active_workspace == requested.parent.resolve()

    finally:
        tui_v2.ObservableTUI._workspace_for = original
