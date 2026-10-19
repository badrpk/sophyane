import pytest

from sophyane.rsi.guest_protocol import (
    GuestProtocolError,
    GuestResult,
    validate_manifest,
    validate_result,
)


def manifest(command=("python3", "-c", "print(1)")):
    return {
        "schema_version": 1,
        "task_id": "task-1",
        "command": list(command),
        "cwd": "/sophyane-input/candidate",
    }


def test_valid_manifest_normalizes_argv():
    result = validate_manifest(manifest())

    assert result.task_id == "task-1"
    assert result.command == ("python3", "-c", "print(1)")
    assert result.cwd == "/sophyane-input/candidate"


@pytest.mark.parametrize(
    "command",
    [([],), ("python3",), ("/bin/sh", "-c", "echo unsafe"), ("bash", "-c", "echo unsafe"),
     ("python3", "-c", "print(1); rm -rf /"), ("python3", "-c", "$(touch bad)")],
)
def test_manifest_rejects_empty_disallowed_or_shell_commands(command):
    with pytest.raises(GuestProtocolError):
        validate_manifest(manifest(command))


def test_manifest_rejects_string_command_and_path_traversal():
    payload = manifest()
    payload["command"] = "python3 -c 'print(1)'"
    with pytest.raises(GuestProtocolError):
        validate_manifest(payload)

    payload = manifest()
    payload["cwd"] = "/sophyane-input/candidate/../../etc"
    with pytest.raises(GuestProtocolError, match="cwd"):
        validate_manifest(payload)


def test_manifest_rejects_oversized_fields():
    payload = manifest()
    payload["task_id"] = "x" * 257
    with pytest.raises(GuestProtocolError):
        validate_manifest(payload)


def test_valid_result_is_normalized():
    result = validate_result({
        "schema_version": 1, "task_id": "task-1", "status": "passed", "exit_code": 0,
        "stdout": "ok", "stderr": "",
    })

    assert isinstance(result, GuestResult)
    assert result.status == "passed"
    assert result.exit_code == 0


@pytest.mark.parametrize("status", ["", "running", "passed-again", "invalid"])
def test_result_rejects_invalid_statuses(status):
    payload = {"schema_version": 1, "task_id": "task-1", "status": status,
               "exit_code": 0, "stdout": "", "stderr": ""}
    with pytest.raises(GuestProtocolError):
        validate_result(payload)


def test_result_rejects_duplicate_marker_and_oversized_output():
    payload = {"schema_version": 1, "task_id": "task-1", "status": "passed",
               "exit_code": 0, "stdout": "", "stderr": "", "completed": True}
    with pytest.raises(GuestProtocolError, match="completed"):
        validate_result(payload)

    payload.pop("completed")
    payload["stdout"] = "x" * 65537
    with pytest.raises(GuestProtocolError, match="output"):
        validate_result(payload)
