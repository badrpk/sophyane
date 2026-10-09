import json

import pytest

from sophyane.adaptive_execution import (
    _canonicalize_explicit_file_path,
    _simple_file_write_request_completed,
    run_adaptive_loop,
)


@pytest.mark.parametrize(
    "user_request",
    [
        "make ytyt.py",
        "create ytyt.py",
        "create file ytyt.py",
        "create a file ytyt.py",
        "create the file ytyt.py",
        "write ytyt.py",
        "write file ytyt.py",
        "write a file ytyt.py",
        "make file ytyt.py",
    ],
)
def test_natural_single_file_write_forms_complete(user_request, tmp_path):
    target = tmp_path / "ytyt.py"
    target.write_text("print('test')\n", encoding="utf-8")

    action = {
        "type": "write_file",
        "path": "ytyt.py",
        "content": "print('test')\n",
    }

    assert _simple_file_write_request_completed(
        user_request,
        action,
        True,
        tmp_path,
    )


@pytest.mark.parametrize(
    "user_request",
    [
        "make ytyt.py",
        "create ytyt.py",
        "create file ytyt.py",
        "write ytyt.py",
        "make file ytyt.py",
    ],
)
def test_natural_single_file_request_canonicalizes_to_workspace_root(user_request):
    action = {
        "type": "write_file",
        "path": "tools/ytyt.py",
        "content": "print('test')\n",
    }

    corrected = _canonicalize_explicit_file_path(
        user_request,
        action,
    )

    assert corrected["path"] == "ytyt.py"


def test_make_single_file_stops_after_verified_write_without_followup(tmp_path):
    calls = []

    def ask(_prompt):
        calls.append(_prompt)
        raise AssertionError(
            "successful simple write must not request another provider action"
        )

    initial = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "ytyt.py",
                "content": "print('hello')\n",
            }
        }
    )

    result = run_adaptive_loop(
        initial_text=initial,
        original_request="make ytyt.py",
        ask=ask,
        workspace=tmp_path,
        max_steps=12,
        progress=lambda _message: None,
    )

    assert calls == []
    assert (tmp_path / "ytyt.py").read_text(
        encoding="utf-8"
    ) == "print('hello')\n"
    assert result.startswith("DONE")


def test_compound_make_request_does_not_false_terminalize(tmp_path):
    target = tmp_path / "ytyt.py"
    target.write_text("print('test')\n", encoding="utf-8")

    action = {
        "type": "write_file",
        "path": "ytyt.py",
        "content": "print('test')\n",
    }

    assert not _simple_file_write_request_completed(
        "make ytyt.py then run it",
        action,
        True,
        tmp_path,
    )


def test_wrong_filename_does_not_complete(tmp_path):
    target = tmp_path / "wrong.py"
    target.write_text("print('test')\n", encoding="utf-8")

    action = {
        "type": "write_file",
        "path": "wrong.py",
        "content": "print('test')\n",
    }

    assert not _simple_file_write_request_completed(
        "make ytyt.py",
        action,
        True,
        tmp_path,
    )
