
import json
from unittest.mock import patch
import pytest

import sophyane.adaptive_execution as ae
import sophyane.rsi.supervisor as supervisor
from sophyane.rsi.authority import Operation


def test_rejection_then_blocked_reply_remains_observable(monkeypatch, tmp_path):
    real_execute = ae._execute

    def execute(runtime, action, workspace, progress):
        assert action["type"] == "respond"
        return real_execute(runtime, action, workspace, progress)

    def ask(prompt):
        return json.dumps({"action": {
            "type": "respond",
            "text": "Execution is blocked. No commands ran.",
        }})

    monkeypatch.setattr(ae, "_execute", execute)
    with patch.object(supervisor.autonomous_bus, "submit") as submitted:
        result = ae.run_adaptive_loop(
            initial_text=json.dumps({"action": {
                "type": "run_command",
                "command": "python -m unittest discover",
            }}),
            original_request="Run this exact test command. Do not modify any files.",
            ask=ask,
            workspace=tmp_path,
            max_steps=3,
            operation=Operation.READ_ONLY_OPERATION,
        )

    assert "Execution is blocked" in result
    assert getattr(result, "execution_failed", False) is True
    submitted.assert_called_once()
    assert any(
        "explicit no-edit request rejected command" in item
        for item in submitted.call_args.args[0].evidence
    )
