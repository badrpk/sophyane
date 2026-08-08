"""Controlled PostgreSQL production preparation for Sophyane SLI.

This module can create, verify and roll back the production PostgreSQL
SLI schema. It intentionally does not select PostgreSQL as the runtime
backend.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from sophyane import sli
from sophyane.sli_migrate_postgres import (
    migrate,
    sqlite_snapshot,
    snapshot_digest,
    verify_snapshots,
)
from sophyane.sli_postgres import (
    PostgresSLIStore,
)


PRODUCTION_SCHEMA = "sli"

STATE_DIR = (
    Path.home()
    / ".local/state/sophyane"
)

CUTOVER_STATE = (
    STATE_DIR
    / "sli-postgres-cutover.json"
)


def _write_manifest(
    payload: dict[str, Any],
) -> None:
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    CUTOVER_STATE.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_manifest() -> dict[str, Any] | None:
    if not CUTOVER_STATE.is_file():
        return None

    return json.loads(
        CUTOVER_STATE.read_text(
            encoding="utf-8"
        )
    )


def source_fingerprint(
    sqlite_path: Path | str = sli.DB_PATH,
) -> dict[str, Any]:
    snapshot = sqlite_snapshot(
        sqlite_path
    )

    return {
        "sqlite":
            str(
                Path(
                    sqlite_path
                ).expanduser()
            ),

        "digest":
            snapshot_digest(
                snapshot
            ),

        "memories":
            len(
                snapshot[
                    "memories"
                ]
            ),

        "traces":
            len(
                snapshot[
                    "traces"
                ]
            ),
    }


def prepare(
    *,
    sqlite_path: Path | str = sli.DB_PATH,
    store: PostgresSLIStore | None = None,
) -> dict[str, Any]:
    target = (
        store
        or PostgresSLIStore(
            schema=PRODUCTION_SCHEMA,
        )
    )

    if target.schema != PRODUCTION_SCHEMA:
        raise ValueError(
            "Production prepare requires schema 'sli'."
        )

    if target.schema_exists():
        raise RuntimeError(
            "Production PostgreSQL SLI schema already exists. "
            "Refusing destructive overwrite."
        )

    source = sqlite_snapshot(
        sqlite_path
    )

    source_digest = snapshot_digest(
        source
    )

    verification = migrate(
        sqlite_path=sqlite_path,
        store=target,
    )

    if not verification[
        "equivalent"
    ]:
        target.drop_schema()

        raise RuntimeError(
            "Production SLI migration failed verification."
        )

    manifest = {
        "state":
            "prepared",

        "schema":
            PRODUCTION_SCHEMA,

        "sqlite_path":
            str(
                Path(
                    sqlite_path
                ).expanduser()
            ),

        "source_digest":
            source_digest,

        "target_digest":
            verification[
                "target_digest"
            ],

        "memories":
            verification[
                "target_memories"
            ],

        "traces":
            verification[
                "target_traces"
            ],

        "runtime_backend":
            "sqlite",
    }

    _write_manifest(
        manifest
    )

    return manifest


def verify(
    *,
    sqlite_path: Path | str = sli.DB_PATH,
    store: PostgresSLIStore | None = None,
) -> dict[str, Any]:
    target = (
        store
        or PostgresSLIStore(
            schema=PRODUCTION_SCHEMA,
        )
    )

    if not target.schema_exists():
        raise RuntimeError(
            "Production PostgreSQL SLI schema does not exist."
        )

    source = sqlite_snapshot(
        sqlite_path
    )

    target_snapshot = target.export_snapshot()

    verification = verify_snapshots(
        source,
        target_snapshot,
    )

    if not verification[
        "equivalent"
    ]:
        raise RuntimeError(
            "Production PostgreSQL SLI differs from SQLite source: "
            + json.dumps(
                verification,
                sort_keys=True,
            )
        )

    manifest = _read_manifest()

    return {
        **verification,

        "schema":
            PRODUCTION_SCHEMA,

        "manifest_present":
            manifest is not None,

        "runtime_backend":
            "sqlite",
    }


def rollback(
    *,
    sqlite_path: Path | str = sli.DB_PATH,
    store: PostgresSLIStore | None = None,
) -> dict[str, Any]:
    target = (
        store
        or PostgresSLIStore(
            schema=PRODUCTION_SCHEMA,
        )
    )

    source_before = source_fingerprint(
        sqlite_path
    )

    target.drop_schema()

    source_after = source_fingerprint(
        sqlite_path
    )

    if source_before != source_after:
        raise RuntimeError(
            "SQLite source changed during PostgreSQL rollback."
        )

    manifest = {
        "state":
            "rolled_back",

        "schema":
            PRODUCTION_SCHEMA,

        "source_digest":
            source_after[
                "digest"
            ],

        "memories":
            source_after[
                "memories"
            ],

        "traces":
            source_after[
                "traces"
            ],

        "runtime_backend":
            "sqlite",
    }

    _write_manifest(
        manifest
    )

    return manifest


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-sli-cutover",
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    for name in (
        "prepare",
        "verify",
        "rollback",
        "status",
    ):
        command = sub.add_parser(
            name
        )

        command.add_argument(
            "--sqlite",
            default=str(
                sli.DB_PATH
            ),
        )

    args = parser.parse_args(
        argv
    )

    if args.command == "status":
        print(
            json.dumps(
                {
                    "manifest":
                        _read_manifest(),

                    "production_schema_exists":
                        PostgresSLIStore(
                            schema=PRODUCTION_SCHEMA,
                        ).schema_exists(),

                    "runtime_backend":
                        "sqlite",
                },
                sort_keys=True,
                indent=2,
            )
        )

        return 0

    if args.command == "prepare":
        result = prepare(
            sqlite_path=args.sqlite,
        )

    elif args.command == "verify":
        result = verify(
            sqlite_path=args.sqlite,
        )

    else:
        result = rollback(
            sqlite_path=args.sqlite,
        )

    print(
        json.dumps(
            result,
            sort_keys=True,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
