"""Persistent state helpers for Sophyane Service Fabric."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def state_root() -> Path:
    return (
        Path.home()
        / ".local"
        / "share"
        / "sophyane"
        / "service_fabric"
    )


def ensure_state_root() -> Path:
    root = state_root()

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    return root


def save_state(
    name: str,
    payload: dict[str, Any],
) -> Path:
    root = ensure_state_root()

    path = (
        root
        / f"{name}.json"
    )

    temporary = path.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        path
    )

    return path


def load_state(
    name: str,
) -> dict[str, Any]:
    path = (
        state_root()
        / f"{name}.json"
    )

    if not path.is_file():
        return {}

    value = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    return (
        value
        if isinstance(
            value,
            dict,
        )
        else {}
    )
