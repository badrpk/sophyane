
from unittest.mock import patch

import pytest
import sophyane.adaptive_execution as ae
import sophyane.rsi.supervisor as supervisor
from sophyane.rsi.authority import Operation


def test_real_adaptive_rejection_reaches_supervisor(monkeypatch, tmp_path):
    def forbidden_execution(*args, **kwargs):
        pytest.fail("Rejected command reached execution")

    def forbidden_provider(*args, **kwargs):
        pytest.fail("This supplied-action test requested a provider")

    monkeypatch.setattr(ae, "_execute", forbidden_execution)
    with patch.object(supervisor.autonomous_bus, "submit") as submitted:
        result = ae.run_adaptive_loop(
            initial_text=(
                '{"action":{"type":"run_command",'
                '"command":"python -m unittest discover"}}'
            ),
            original_request="Run unit tests. Do not modify any files.",
            ask=forbidden_provider,
            workspace=tmp_path,
            max_steps=1,
            operation=Operation.READ_ONLY_OPERATION,
        )

    assert "explicit no-edit request rejected command" in result
    assert getattr(result, "execution_failed", False) is True
    assert getattr(result, "capability_class", "") == ""
    submitted.assert_called_once()
    observation = submitted.call_args.args[0]
    assert any(
        "explicit no-edit request rejected command" in item
        for item in observation.evidence
    )
