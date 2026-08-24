from __future__ import annotations

import json
import time
from pathlib import Path

import sophyane.self_improve.ledger as ledger


def _timestamp(
    day: str,
    second: int = 0,
) -> float:
    parsed = time.strptime(
        f"{day} 12:00:{second:02d}",
        "%Y-%m-%d %H:%M:%S",
    )

    return time.mktime(parsed)


def _block(
    *,
    index: int,
    timestamp: float,
    block_hash: str,
) -> dict:
    return {
        "index": index,
        "timestamp": timestamp,
        "proposal": {
            "proposal_id": f"proposal-{index}",
            "kind": "fact",
            "title": "test",
            "body": "body",
            "source_device": "test-device",
            "evidence": {},
            "score": 0.0,
            "created_at": timestamp,
        },
        "prev_hash": "",
        "hash": block_hash,
        "device": "test-device",
        "version": "test",
    }


def _configure(
    *,
    monkeypatch,
    local_dir: Path,
    repo_dir: Path,
    current_blocks: list[dict],
) -> None:
    monkeypatch.setattr(
        ledger,
        "EPOCH_DIR",
        local_dir,
    )

    monkeypatch.setattr(
        ledger,
        "REPO_IMPROVEMENTS",
        repo_dir,
    )

    monkeypatch.setattr(
        ledger,
        "_device_id",
        lambda: "test-device",
    )

    monkeypatch.setattr(
        ledger,
        "verify_chain",
        lambda: {
            "ok": True,
            "length": len(current_blocks),
            "tip": (
                current_blocks[-1]["hash"]
                if current_blocks
                else ""
            ),
        },
    )

    monkeypatch.setattr(
        ledger,
        "_load_blocks",
        lambda: list(current_blocks),
    )


def test_same_day_reexport_refreshes_catalog(
    tmp_path: Path,
    monkeypatch,
):
    day = "2099-01-02"

    local_dir = tmp_path / "local"
    repo_dir = (
        tmp_path
        / "repo"
        / "improvements"
    )

    first_blocks = [
        _block(
            index=1,
            timestamp=_timestamp(day, 0),
            block_hash="aaa",
        ),
    ]

    second_blocks = [
        *first_blocks,
        _block(
            index=2,
            timestamp=_timestamp(day, 1),
            block_hash="bbb",
        ),
    ]

    current_blocks = list(
        first_blocks
    )

    _configure(
        monkeypatch=monkeypatch,
        local_dir=local_dir,
        repo_dir=repo_dir,
        current_blocks=current_blocks,
    )

    first = ledger.export_daily_epoch(
        day
    )

    catalog = (
        repo_dir
        / "CATALOG.md"
    )

    first_rows = [
        line
        for line
        in catalog.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.startswith(
            f"- {day}:"
        )
    ]

    assert len(first_rows) == 1
    assert "1 proposals" in first_rows[0]
    assert first["count"] == 1

    current_blocks[:] = second_blocks

    second = ledger.export_daily_epoch(
        day
    )

    second_rows = [
        line
        for line
        in catalog.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.startswith(
            f"- {day}:"
        )
    ]

    assert len(second_rows) == 1
    assert "2 proposals" in second_rows[0]
    assert second["count"] == 2

    epoch = json.loads(
        (
            repo_dir
            / f"epoch-{day}.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    expected = (
        f"- {day}: "
        f"{epoch['count']} proposals "
        f"· merkle "
        f"`{epoch['merkle_root'][:16]}…` "
        f"· device `{epoch['device']}`"
    )

    assert second_rows == [expected]


def test_same_day_reexport_deduplicates_existing_rows(
    tmp_path: Path,
    monkeypatch,
):
    day = "2099-01-03"

    local_dir = tmp_path / "local"
    repo_dir = (
        tmp_path
        / "repo"
        / "improvements"
    )

    repo_dir.mkdir(
        parents=True
    )

    catalog = (
        repo_dir
        / "CATALOG.md"
    )

    catalog.write_text(
        "# Sophyane daily improvement catalog\n\n"
        f"- {day}: stale one\n"
        f"- {day}: stale two\n",
        encoding="utf-8",
    )

    blocks = [
        _block(
            index=1,
            timestamp=_timestamp(day, 0),
            block_hash="ccc",
        ),
    ]

    _configure(
        monkeypatch=monkeypatch,
        local_dir=local_dir,
        repo_dir=repo_dir,
        current_blocks=blocks,
    )

    result = ledger.export_daily_epoch(
        day
    )

    rows = [
        line
        for line
        in catalog.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.startswith(
            f"- {day}:"
        )
    ]

    assert len(rows) == 1

    expected = (
        f"- {day}: "
        f"{result['count']} proposals "
        f"· merkle "
        f"`{result['merkle_root'][:16]}…` "
        f"· device `{result['device']}`"
    )

    assert rows == [expected]


def test_reexport_preserves_other_catalog_rows(
    tmp_path: Path,
    monkeypatch,
):
    day = "2099-01-04"

    local_dir = tmp_path / "local"
    repo_dir = (
        tmp_path
        / "repo"
        / "improvements"
    )

    repo_dir.mkdir(
        parents=True
    )

    catalog = (
        repo_dir
        / "CATALOG.md"
    )

    other_before = (
        "- 2099-01-01: preserved row"
    )

    other_after = (
        "- 2099-01-05: another preserved row"
    )

    catalog.write_text(
        "# Sophyane daily improvement catalog\n\n"
        f"{other_before}\n"
        f"- {day}: stale row\n"
        f"{other_after}\n",
        encoding="utf-8",
    )

    blocks = [
        _block(
            index=1,
            timestamp=_timestamp(day, 0),
            block_hash="ddd",
        ),
    ]

    _configure(
        monkeypatch=monkeypatch,
        local_dir=local_dir,
        repo_dir=repo_dir,
        current_blocks=blocks,
    )

    ledger.export_daily_epoch(day)

    lines = (
        catalog.read_text(
            encoding="utf-8"
        ).splitlines()
    )

    assert other_before in lines
    assert other_after in lines

    assert (
        lines.index(other_before)
        < lines.index(other_after)
    )

    rows = [
        line
        for line in lines
        if line.startswith(
            f"- {day}:"
        )
    ]

    assert len(rows) == 1
