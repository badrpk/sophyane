from __future__ import annotations

from pathlib import Path

from sophyane.mission_engine import MissionStore, run_mission


def test_durable_mission_executes_steps(tmp_path: Path) -> None:
    store = MissionStore(tmp_path / "missions.sqlite3")

    mission = store.create(
        "Create two verified local programs",
        [
            'create first.py and run it printing "first"',
            'create second.cpp compile and run it printing "second"',
        ],
        workspace=tmp_path / "workspace",
    )

    result = run_mission(
        mission.mission_id,
        store=store,
    )

    assert result["ok"] is True

    updated = store.get(mission.mission_id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.completed_steps == 2

    workspace = Path(updated.workspace)
    assert (workspace / "first.py").is_file()
    assert (workspace / "second.cpp").is_file()
