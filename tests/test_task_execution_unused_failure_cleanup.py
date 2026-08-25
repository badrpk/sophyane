from __future__ import annotations

import inspect

from sophyane import task_execution
from sophyane import task_orchestrator


def test_compiled_task_failure_contract_is_preserved() -> None:
    source = inspect.getsource(
        task_execution.execute_compiled_task
    )

    assert '"error": "source_validation_failed"' in source
    assert '"error": "task_timeout"' in source
    assert '"error": "task_failed"' in source
    assert '"error": "invalid_json_output"' in source


def test_failed_subprocess_preserves_diagnostic_evidence() -> None:
    source = inspect.getsource(
        task_execution.execute_compiled_task
    )

    assert '"exit_code": process.returncode' in source
    assert '"stderr": process.stderr[' in source
    assert '"workspace": str(workspace)' in source


def test_orchestrator_consumes_compiled_task_failures() -> None:
    source = inspect.getsource(
        task_orchestrator.try_compiled_task_reply
    )

    assert "execute_compiled_task(" in source
    assert 'if not result.get("ok"):' in source
    assert 'result.get(' in source
    assert '"error"' in source
    assert '"task_failed"' in source
    assert '"source_validation_failed"' in source


def test_legacy_action_result_failure_state_is_not_required() -> None:
    source = inspect.getsource(
        task_execution
    )

    assert "failed_action = action.action_id" not in source
    assert "previous_failure = result.to_dict()" not in source
