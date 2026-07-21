"""Safe compatibility checks and migration for Sophyane SLI databases."""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


EXPECTED_MEMORIES = {
    "id", "request", "state", "action", "result", "reward", "confidence",
    "elapsed_seconds", "source_type", "created_at",
}
EXPECTED_TRACES = {
    "trace_id", "request", "action", "status", "reward", "quality_reward",
    "failure_category", "quality_signals", "result", "elapsed_seconds",
    "workspace_before", "workspace_after", "created_at",
}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def schema_is_current(path: Path) -> bool:
    if not path.exists():
        return True
    with sqlite3.connect(path) as db:
        memories = _columns(db, "memories")
        traces = _columns(db, "learned_execution_traces")
    return EXPECTED_MEMORIES.issubset(memories) and EXPECTED_TRACES.issubset(traces)


def ensure_current_schema(path: Path | str | None = None) -> dict[str, str | bool]:
    """Back up an incompatible legacy database and recreate the current schema."""
    from sophyane import sli

    target = Path(path or sli.DB_PATH).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    if schema_is_current(target):
        with sli.connect(target):
            pass
        return {"migrated": False, "database": str(target), "backup": ""}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = target.with_name(f"{target.name}.backup.{stamp}")
    target.replace(backup)

    with sli.connect(target):
        pass

    return {
        "migrated": True,
        "database": str(target),
        "backup": str(backup),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-sli-migrate",
        description="Back up an incompatible legacy SLI database and recreate the current schema.",
    )
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args(argv)
    result = ensure_current_schema(args.database)
    if result["migrated"]:
        print(f"SLI schema migrated: {result['database']}")
        print(f"Legacy backup: {result['backup']}")
    else:
        print(f"SLI schema is current: {result['database']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
