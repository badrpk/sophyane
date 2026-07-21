from __future__ import annotations

import json

from sophyane.runtime_sli_mission_os import compile_mission, is_mission_request, materialize


REQUEST = (
    "make a chess game for browser where one player uses a local llm and the other "
    "uses Gemini; record the match, upload it to YouTube, report views and earnings, "
    "and notify my phone every hour"
)


def test_complex_request_is_compiled_as_mission() -> None:
    assert is_mission_request(REQUEST)
    plan = compile_mission(REQUEST)
    ids = {node.node_id for node in plan.nodes}
    assert {"chess_ui", "local_ai", "gemini_ai", "recorder", "youtube", "analytics", "notifications"} <= ids
    youtube = next(node for node in plan.nodes if node.node_id == "youtube")
    assert youtube.state == "BLOCKED"
    assert "encoder" in youtube.depends_on


def test_simple_game_is_not_forced_into_mission_mode() -> None:
    assert not is_mission_request("make a snake game for browser")


def test_materialization_writes_graph_and_browser_scaffold(tmp_path) -> None:
    plan = compile_mission(REQUEST)
    materialize(plan, tmp_path)
    root = tmp_path / plan.mission_id
    ledger = json.loads((root / "mission.json").read_text(encoding="utf-8"))
    assert ledger["mission_id"] == plan.mission_id
    assert (root / "projects/chess_ui/index.html").exists()
    assert (root / "projects/youtube/node.json").exists()
    assert (root / "projects/shared/move-protocol.json").exists()
