import json
import shlex
import sys

from sophyane import adaptive_execution as adaptive
from sophyane import execution_runtime as runtime


def test_python_command_uses_current_sophyane_interpreter():
    command = runtime._canonicalize_python_command(
        "python -m pytest -q test_app.py"
    )

    expected = (
        shlex.quote(sys.executable)
        + " -m pytest -q test_app.py"
    )

    assert command == expected


def test_python3_command_uses_current_sophyane_interpreter():
    command = runtime._canonicalize_python_command(
        'python3 -c "print(123)"'
    )

    assert command.startswith(
        shlex.quote(sys.executable)
        + " -c "
    )

    assert '"print(123)"' in command


def test_non_python_command_is_unchanged():
    command = (
        "printf '%s\\n' hello"
    )

    assert (
        runtime._canonicalize_python_command(
            command
        )
        == command
    )


def test_absolute_python_path_is_not_rewritten():
    command = (
        "/tmp/custom-python -V"
    )

    assert (
        runtime._canonicalize_python_command(
            command
        )
        == command
    )


def test_valid_run_command_json_still_parses_normally():
    raw = json.dumps(
        {
            "action": {
                "type": "run_command",
                "command": (
                    "python -c "
                    "'print(123)'"
                ),
            }
        }
    )

    plan = runtime.extract_plan(
        raw
    )

    action = adaptive._selected_action(
        runtime,
        plan,
    )

    assert action["type"] == "run_command"


def test_exact_live_malformed_run_command_recovers():
    raw = (
        '{"action":{"type":"run_command","command":'
        '"python -c "import test_app; '
        'test_app.test_health_endpoint()""}}'
    )

    plan = runtime.extract_plan(
        raw
    )

    assert isinstance(
        plan,
        dict,
    )

    action = adaptive._selected_action(
        runtime,
        plan,
    )

    assert action == {
        "type": "run_command",
        "command": (
            "python -c "
            '"import test_app; '
            'test_app.test_health_endpoint()"'
        ),
    }


def test_quasi_run_command_requires_exact_nested_envelope():
    raw = (
        '{"action":{"type":"run_command","command":'
        '"python -c "print(1)""},'
        '"extra":"unexpected"}'
    )

    assert (
        runtime.extract_plan(raw)
        is None
    )


def test_quasi_run_command_does_not_recover_unknown_action():
    raw = (
        '{"action":{"type":"dangerous_command","command":'
        '"python -c "print(1)""}}'
    )

    assert (
        runtime.extract_plan(raw)
        is None
    )
