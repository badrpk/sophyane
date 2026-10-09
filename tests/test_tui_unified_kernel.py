from __future__ import annotations

import os

import json
from pathlib import Path

from sophyane import tui_v2


def test_tui_executes_cpp_before_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    response = tui_v2._simple_chat_reply(
        'create hello.cpp compile and run it printing "TUI kernel works"'
    )

    assert response is not None

    payload = json.loads(response)

    assert payload["handled"] is True
    assert payload["ok"] is True
    assert payload["capability"] == (
        "development.cpp_create_compile_run"
    )
    assert (tmp_path / "hello.cpp").is_file()
    executable = (
        "hello.exe"
        if os.name == "nt"
        else "hello"
    )
    assert (tmp_path / executable).is_file()
    assert (
        payload["evidence"][-1]["stdout"].strip()
        == "TUI kernel works"
    )


def test_tui_mission_list_is_local(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "missions.sqlite3"

    from sophyane import mission_engine

    monkeypatch.setattr(
        mission_engine,
        "MISSION_DB",
        database,
    )

    response = tui_v2._simple_chat_reply(
        "sophyane-mission list"
    )

    assert response is not None

    payload = json.loads(response)

    assert payload["ok"] is True
    assert payload["count"] == 0
    assert payload["missions"] == []


def test_tui_reads_previous_deterministic_file_followup(
    tmp_path: Path,
) -> None:
    target = tmp_path / "red.py"
    target.write_text("print('red')\n", encoding="utf-8")
    reply = json.dumps({"evidence": {"data": {"path": str(target)}}})

    remembered = tui_v2._written_file_from_reply(reply)
    result = tui_v2._read_followup_file(
        "show me content of this file",
        remembered,
    )

    assert result == "Contents of " + str(target) + ":\nprint('red')\n"


def test_tui_remembers_file_from_real_human_readable_creation_reply(
    tmp_path: Path,
) -> None:
    target = tmp_path / "kunlun.py"
    target.write_text("", encoding="utf-8")

    reply = (
        "Created kunlun.py directly through Sophyane's guarded "
        "filesystem authority.\n\n"
        f"Path: {target}"
    )

    remembered = tui_v2._written_file_from_reply(reply)

    assert remembered == target

    result = tui_v2._read_followup_file(
        "what is content of this file?",
        remembered,
    )

    assert result == f"Contents of {target}:\n"


# SOPHYANE_MODE4_GROUNDED_FILE_FOLLOWUP_SHARP_RED_V1


def test_written_file_parser_accepts_real_coding_result_files(
    tmp_path: Path,
) -> None:
    target = tmp_path / "yring.py"
    target.write_text(
        "print('yring')\n",
        encoding="utf-8",
    )

    reply = json.dumps(
        {
            "handled": True,
            "ok": True,
            "capability": "development.python_create_validate",
            "summary": "Created and syntax-validated yring.py.",
            "workspace": str(tmp_path),
            "files": ["yring.py"],
            "evidence": [],
            "error": "",
        }
    )

    remembered = tui_v2._written_file_from_reply(reply)

    assert remembered == target


def test_file_content_followup_tolerates_observed_minor_typos() -> None:
    assert tui_v2._file_content_followup(
        "what ia content if this file?"
    )


def test_real_coding_result_can_drive_typoed_grounded_followup(
    tmp_path: Path,
) -> None:
    target = tmp_path / "yring.py"
    target.write_text(
        "print('yring')\n",
        encoding="utf-8",
    )

    reply = json.dumps(
        {
            "handled": True,
            "ok": True,
            "capability": "development.python_create_validate",
            "summary": "Created and syntax-validated yring.py.",
            "workspace": str(tmp_path),
            "files": ["yring.py"],
            "evidence": [],
            "error": "",
        }
    )

    remembered = tui_v2._written_file_from_reply(reply)

    result = tui_v2._read_followup_file(
        "what ia content if this file?",
        remembered,
    )

    assert result == (
        f"Contents of {target}:\n"
        "print('yring')\n"
    )


# SOPHYANE_MODE4_ACTIVE_FILE_PRONOUN_SHARP_RED_V1

def test_file_content_followup_accepts_active_file_pronouns() -> None:
    assert tui_v2._file_content_followup(
        "what is its content"
    )
    assert tui_v2._file_content_followup(
        "what's its content"
    )
    assert tui_v2._file_content_followup(
        "show its content"
    )
    assert tui_v2._file_content_followup(
        "read it"
    )
