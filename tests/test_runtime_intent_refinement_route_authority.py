from sophyane import tui_v2
from sophyane.runtime_intent_refinement_patch import _parse_refinement


def test_standalone_absolute_script_creation_cannot_be_model_continuation():
    request = (
        "Create a script `/tmp/poll_status.py` that outputs "
        "`STATUS: IN_PROGRESS` and returns exit code 0."
    )

    raw = """{
      "objective": "Create /tmp/poll_status.py as requested.",
      "selection_reason": "route=continue_project",
      "action": {
        "type": "respond",
        "message": "Create /tmp/poll_status.py as requested."
      },
      "success_criteria": []
    }"""

    route, refined, _ = _parse_refinement(
        raw,
        request,
        has_project=True,
        tui_v2=tui_v2,
    )

    assert tui_v2._project_continuation(request, True) is False
    assert tui_v2._execution_requested(request) is True
    assert route == "execution"
    assert refined
