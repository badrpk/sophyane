from __future__ import annotations

import sqlite3
from pathlib import Path

from sophyane.expert.answer import answer_tough_question
from sophyane.sli_schema import ensure_current_schema, schema_is_current
from sophyane.vela import validate_workspace


def test_hybrid_preserves_short_exact_local_answer() -> None:
    result = answer_tough_question(
        "Reply with exactly: LOCAL_OK",
        generate=lambda _prompt, _system: "LOCAL_OK",
        mode="hybrid",
    )
    assert result["answer"] == "LOCAL_OK"
    assert result["used"] == "llm_short"


def test_sli_migration_backs_up_legacy_database(tmp_path: Path) -> None:
    database = tmp_path / "sli.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, request TEXT)")
        db.execute("CREATE TABLE learned_execution_traces(trace_id TEXT PRIMARY KEY)")
    assert not schema_is_current(database)
    result = ensure_current_schema(database)
    assert result["migrated"] is True
    assert Path(str(result["backup"])).exists()
    assert schema_is_current(database)


def test_vela_validates_offline_html(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body><h1>OK</h1></body></html>",
        encoding="utf-8",
    )
    report = validate_workspace(tmp_path)
    assert report["ok"] is True
    assert any(check["name"] == "all_deterministic_checks" for check in report["checks"])
