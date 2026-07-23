from __future__ import annotations

import json
from pathlib import Path

import sophyane.self_improve.ledger as ledger


def configure_isolated_ledger(
    tmp_path: Path,
    monkeypatch,
) -> tuple[Path, Path]:
    state = tmp_path / "state"
    repository = tmp_path / "repository-improvements"

    monkeypatch.setattr(
        ledger,
        "STATE_DIR",
        state,
    )
    monkeypatch.setattr(
        ledger,
        "LEDGER_PATH",
        state / "improvement_chain.jsonl",
    )
    monkeypatch.setattr(
        ledger,
        "EPOCH_DIR",
        state / "improvement_epochs",
    )
    monkeypatch.setattr(
        ledger,
        "REPO_IMPROVEMENTS",
        repository,
    )

    return state, repository


def test_default_epoch_export_is_state_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state, repository = configure_isolated_ledger(
        tmp_path,
        monkeypatch,
    )

    ledger.propose_improvement(
        "fact",
        "state-only export",
        "ordinary exports must not change repositories",
    )

    result = ledger.export_daily_epoch(
        "2026-07-23",
    )

    local_path = Path(result["local_path"])

    assert local_path.exists()
    assert state.resolve() in local_path.resolve().parents
    assert result["repo_path"] == ""
    assert result["repository_published"] is False
    assert not repository.exists()


def test_explicit_repository_publication_writes_epoch_and_catalog(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, repository = configure_isolated_ledger(
        tmp_path,
        monkeypatch,
    )

    ledger.propose_improvement(
        "benchmark",
        "explicit publication",
        "publish only after an explicit request",
    )

    result = ledger.export_daily_epoch(
        "2026-07-23",
        publish_to_repository=True,
    )

    repo_path = Path(result["repo_path"])
    catalog = repository / "CATALOG.md"

    assert result["repository_published"] is True
    assert repo_path.exists()
    assert catalog.exists()
    assert "2026-07-23" in catalog.read_text(
        encoding="utf-8",
    )


def test_explicit_publication_can_target_a_selected_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_isolated_ledger(
        tmp_path,
        monkeypatch,
    )

    selected = tmp_path / "published-catalog"

    result = ledger.export_daily_epoch(
        "2026-07-23",
        publish_to_repository=True,
        repository_directory=selected,
    )

    assert Path(result["repo_path"]).parent == (
        selected.resolve()
    )
    assert (
        selected / "epoch-2026-07-23.json"
    ).exists()


def test_repeated_publication_does_not_duplicate_catalog_line(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, repository = configure_isolated_ledger(
        tmp_path,
        monkeypatch,
    )

    ledger.export_daily_epoch(
        "2026-07-23",
        publish_to_repository=True,
    )
    ledger.export_daily_epoch(
        "2026-07-23",
        publish_to_repository=True,
    )

    catalog_text = (
        repository / "CATALOG.md"
    ).read_text(
        encoding="utf-8",
    )

    assert catalog_text.count("2026-07-23") == 1


def test_local_epoch_contains_valid_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_isolated_ledger(
        tmp_path,
        monkeypatch,
    )

    result = ledger.export_daily_epoch(
        "2026-07-23",
    )

    payload = json.loads(
        Path(result["local_path"]).read_text(
            encoding="utf-8",
        )
    )

    assert payload["day"] == "2026-07-23"
    assert "merkle_root" in payload
