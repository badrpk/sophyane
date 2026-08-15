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
