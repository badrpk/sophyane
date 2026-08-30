from __future__ import annotations

from sophyane import execution_runtime
from sophyane.adaptive_execution import (
    _recover_simple_empty_file_action,
    _selected_action,
)


RAW = r'''```json
{
  "action": "python3 -c \"import os; open(os.path.join('/tmp', 'test.py'), 'w').close()\"",
  "artifact": "/tmp/test.py"
}
```'''


def test_exact_mode3_json_fence_parses() -> None:
    plan = execution_runtime.extract_plan(RAW)

    assert plan is not None
    assert plan["artifact"] == "/tmp/test.py"


def test_string_action_is_not_arbitrarily_executed() -> None:
    plan = execution_runtime.extract_plan(RAW)

    assert plan is not None
    assert (
        _selected_action(
            execution_runtime,
            plan,
        )
        is None
    )


def test_exact_mode3_failure_recovers_workspace_file() -> None:
    plan = execution_runtime.extract_plan(RAW)

    action = _recover_simple_empty_file_action(
        "make a file test.py",
        plan,
    )

    assert action == {
        "type": "write_file",
        "path": "test.py",
        "content": "",
        "replace": True,
        "artifact_source": "simple_empty_file_recovery",
    }


def test_provider_tmp_destination_is_not_authoritative() -> None:
    plan = execution_runtime.extract_plan(RAW)

    action = _recover_simple_empty_file_action(
        "create file nested/example.py",
        plan,
    )

    assert action is not None
    assert action["path"] == "nested/example.py"
    assert "/tmp" not in action["path"]


def test_absolute_destination_is_rejected() -> None:
    plan = execution_runtime.extract_plan(RAW)

    assert (
        _recover_simple_empty_file_action(
            "create file /tmp/test.py",
            plan,
        )
        is None
    )


def test_parent_escape_is_rejected() -> None:
    plan = execution_runtime.extract_plan(RAW)

    assert (
        _recover_simple_empty_file_action(
            "create file ../test.py",
            plan,
        )
        is None
    )


def test_nontrivial_content_request_is_not_faked_empty() -> None:
    plan = execution_runtime.extract_plan(RAW)

    assert (
        _recover_simple_empty_file_action(
            "create test.py containing a FastAPI server",
            plan,
        )
        is None
    )


def test_valid_structured_action_is_left_to_normal_runtime() -> None:
    plan = {
        "action": {
            "type": "write_file",
            "path": "test.py",
            "content": "print('ok')\n",
        },
        "artifact": "test.py",
    }

    assert (
        _recover_simple_empty_file_action(
            "make a file test.py",
            plan,
        )
        is None
    )
