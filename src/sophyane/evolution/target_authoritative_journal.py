"""Durable journal for authoritative V2F baseline results."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .target_authoritative_baseline import (
    AuthoritativeBaselineResult,
)


def default_authoritative_journal_dir() -> Path:
    return (
        Path.home()
        / ".local"
        / "state"
        / "sophyane"
        / "evolution-authoritative-baselines"
    )


def write_authoritative_result(
    result: AuthoritativeBaselineResult,
    *,
    journal_dir: Path | None = None,
) -> Path:
    root = (
        Path(journal_dir)
        .expanduser()
        .resolve()
        if journal_dir is not None
        else default_authoritative_journal_dir().resolve()
    )

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    record = {
        "schema": (
            "sophyane.cross-badrpk."
            "v2f.authoritative-baseline.v1"
        ),
        "recorded_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_name": result.target_name,
        "source_head": result.source_head,
        "contract_head": result.contract_head,
        "status": result.status,
        "message": result.message,
        "missing": list(
            result.missing
        ),
        "unavailable": list(
            result.unavailable
        ),
        "runs": [
            {
                "kind": run.kind,
                "relative_cwd": run.relative_cwd,
                "argv": list(
                    run.argv
                ),
                "returncode": run.returncode,
                "timed_out": run.timed_out,
                "passed": run.passed,
                "stdout": run.stdout,
                "stderr": run.stderr,
            }
            for run in result.runs
        ],
    }

    stamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )

    destination = (
        root
        / (
            f"{stamp}-"
            f"{result.target_name}.json"
        )
    )

    fd, temporary = tempfile.mkstemp(
        prefix=".v2f-",
        suffix=".json",
        dir=root,
    )

    temporary_path = Path(
        temporary
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                record,
                handle,
                indent=2,
                sort_keys=True,
            )

            handle.write("\n")
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temporary_path,
            destination,
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return destination
