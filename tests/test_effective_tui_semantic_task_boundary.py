from types import SimpleNamespace

import pytest


def test_effective_tui_clears_previous_semantic_task_before_routing(
    monkeypatch,
):
    from sophyane import tui_v2
    from sophyane.runtime_intent_refinement_patch import (
        install_intent_refinement,
    )
    from sophyane import conversational_graph_session

    install_intent_refinement()

    tui = object.__new__(tui_v2.ObservableTUI)

    tui.active_request = "previous project"
    tui.active_workspace = None
    tui.project_requirements = ["previous project"]
    tui._semantic_original_request = "previous audit"
    tui._semantic_live_instructions = ["count old files"]
    tui._sophyane_canonical_request_snapshot = (
        "previous audit plus count old files"
    )

    prompts = iter(["new independent question"])

    def read_prompt(_prompt):
        return next(prompts)

    def handle_command(message):
        return message

    def check_boundary(_self, message):
        assert message == "new independent question"
        assert _self._semantic_original_request == ""
        assert _self._semantic_live_instructions == []
        assert not _self._sophyane_canonical_request_snapshot
        assert _self.active_request == "previous project"
        assert _self.project_requirements == ["previous project"]

        raise RuntimeError("BOUNDARY_OBSERVED")

    monkeypatch.setattr(
        tui,
        "read_prompt",
        read_prompt,
    )
    monkeypatch.setattr(
        tui,
        "_handle_command",
        handle_command,
    )
    monkeypatch.setattr(
        conversational_graph_session,
        "try_conversational_graph_followup",
        check_boundary,
    )

    with pytest.raises(
        RuntimeError,
        match="BOUNDARY_OBSERVED",
    ):
        tui.run()
