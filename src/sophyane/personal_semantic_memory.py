"""Private semantic policies and confirmed personal facts.

Raw connector content is never promoted into general SLI memory.
Only user-approved routing rules and confirmed facts are persisted.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

STATE_DIR = Path(
    os.environ.get(
        "SOPHYANE_STATE_DIR",
        Path.home() / ".local/state/sophyane",
    )
).expanduser()

MEMORY_FILE = STATE_DIR / "personal-semantic-memory.json"

DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "source_policies": {
        "personal_facts": [],
    },
    "confirmed_facts": {},
    "feedback": [],
}


def _load() -> dict[str, Any]:
    if not MEMORY_FILE.is_file():
        return {
            "version": 1,
            "source_policies": {
                "personal_facts": [],
            },
            "confirmed_facts": {},
            "feedback": [],
        }

    try:
        data = json.loads(
            MEMORY_FILE.read_text(
                encoding="utf-8",
            )
        )
    except Exception:
        data = {}

    data.setdefault("version", 1)
    data.setdefault(
        "source_policies",
        {"personal_facts": []},
    )
    data["source_policies"].setdefault(
        "personal_facts",
        [],
    )
    data.setdefault("confirmed_facts", {})
    data.setdefault("feedback", [])

    return data


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    MEMORY_FILE.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        os.chmod(MEMORY_FILE, 0o600)
    except OSError:
        pass


def learn_source_policy(
    domain: str,
    sources: list[str],
    *,
    instruction: str,
) -> None:
    data = _load()

    clean_sources = [
        str(source).strip().casefold()
        for source in sources
        if str(source).strip()
    ]

    data["source_policies"][domain] = clean_sources

    data["feedback"].append(
        {
            "type": "source_policy",
            "domain": domain,
            "sources": clean_sources,
            "instruction": instruction,
            "learned_at": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
    )

    _save(data)


def source_policy(
    domain: str,
) -> list[str]:
    data = _load()

    return [
        str(item)
        for item in (
            data.get("source_policies", {})
            .get(domain, [])
        )
        if str(item).strip()
    ]


def save_confirmed_fact(
    key: str,
    value: str,
    *,
    provenance: str,
    evidence_source: str,
) -> None:
    data = _load()

    data["confirmed_facts"][key] = {
        "value": str(value).strip(),
        "provenance": str(provenance).strip(),
        "evidence_source": str(
            evidence_source
        ).strip(),
        "confirmed_at": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }

    _save(data)


def confirmed_fact(
    key: str,
) -> dict[str, str] | None:
    item = (
        _load()
        .get("confirmed_facts", {})
        .get(key)
    )

    if not isinstance(item, dict):
        return None

    value = str(item.get("value") or "").strip()

    if not value:
        return None

    return {
        "value": value,
        "provenance": str(
            item.get("provenance") or ""
        ),
        "evidence_source": str(
            item.get("evidence_source") or ""
        ),
        "confirmed_at": str(
            item.get("confirmed_at") or ""
        ),
    }


def forget_fact(key: str) -> bool:
    data = _load()

    if key not in data["confirmed_facts"]:
        return False

    del data["confirmed_facts"][key]
    _save(data)

    return True


__all__ = [
    "MEMORY_FILE",
    "confirmed_fact",
    "forget_fact",
    "learn_source_policy",
    "save_confirmed_fact",
    "source_policy",
]
