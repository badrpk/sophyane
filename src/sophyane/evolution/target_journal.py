"""Durable append-only records for cross-BADRPK evaluation.

The journal stores metadata and validation results only.

It does not:

* apply patches;
* alter git state;
* commit;
* promote;
* push.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .target_validator_resolver import (
    RepositoryValidationProfile,
)


def default_journal_dir() -> Path:
    return (
        Path.home()
        / ".local"
        / "state"
        / "sophyane"
        / "evolution-target-journal"
    )


def profile_record(
    profile: RepositoryValidationProfile,
    *,
    target_head: str,
) -> dict[str, Any]:
    return {
        "schema": "sophyane.cross-badrpk.v2d.profile.v1",
        "recorded_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_name": profile.target_name,
        "target_repo": str(
            profile.repo
        ),
        "target_head": target_head,
        "readiness": profile.readiness,
        "validators": [
            {
                **asdict(
                    candidate
                ),
                "cwd": str(
                    candidate.cwd
                ),
                "argv": list(
                    candidate.argv
                ),
            }
            for candidate in profile.candidates
        ],
    }


def write_profile_record(
    profile: RepositoryValidationProfile,
    *,
    target_head: str,
    journal_dir: Path | None = None,
) -> Path:
    root = (
        Path(journal_dir)
        .expanduser()
        .resolve()
        if journal_dir is not None
        else default_journal_dir().resolve()
    )

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    record = profile_record(
        profile,
        target_head=target_head,
    )

    safe_name = (
        profile.target_name
        .replace(
            "/",
            "_",
        )
    )

    stamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )

    destination = (
        root
        / f"{stamp}-{safe_name}.json"
    )

    fd, temporary = tempfile.mkstemp(
        prefix=".sophyane-v2d-",
        suffix=".json",
        dir=root,
    )

    temp_path = Path(
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
            temp_path,
            destination,
        )

    finally:
        if temp_path.exists():
            temp_path.unlink()

    return destination
