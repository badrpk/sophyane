from pathlib import Path

import pytest

from sophyane.evolution.badrpk_targets import (
    BADRPK_REPOSITORY_NAMES,
    available_targets,
    canonical_target_name,
    resolve_target,
)
from sophyane.evolution.engine import EvolutionEngine
from sophyane.evolution.models import EvolutionConfig


def _git_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def test_canonical_target_name_is_case_insensitive():
    assert canonical_target_name("VEYRON") == "Veyron"
    assert canonical_target_name("RANGOONS") == "rangoons"


def test_unknown_target_is_rejected():
    with pytest.raises(ValueError):
        canonical_target_name("not-badrpk")


def test_sophyane_defaults_to_active_harness(tmp_path: Path):
    harness = tmp_path / "sophyane"
    _git_dir(harness)

    sibling_root = tmp_path / "repos"
    sibling = sibling_root / "sophyane"
    _git_dir(sibling)

    target = resolve_target(
        name="sophyane",
        harness_repo=harness,
        badrpk_root=sibling_root,
    )

    assert target.repo == harness.resolve()
    assert target.is_harness


def test_non_harness_repo_comes_from_badrpk_root(tmp_path: Path):
    harness = tmp_path / "sophyane"
    _git_dir(harness)

    root = tmp_path / "badrpk-repos"
    rangoons = root / "rangoons"
    _git_dir(rangoons)

    target = resolve_target(
        name="rangoons",
        harness_repo=harness,
        badrpk_root=root,
    )

    assert target.repo == rangoons.resolve()
    assert not target.is_harness


def test_available_targets_discovers_existing_repos(tmp_path: Path):
    harness = tmp_path / "sophyane"
    _git_dir(harness)

    root = tmp_path / "badrpk-repos"

    for name in ("Droidra", "rangoons", "xerus"):
        _git_dir(root / name)

    found = available_targets(
        harness_repo=harness,
        badrpk_root=root,
    )

    assert "sophyane" in found
    assert "Droidra" in found
    assert "rangoons" in found
    assert "xerus" in found


def test_engine_preserves_harness_repo_semantics(tmp_path: Path):
    harness = tmp_path / "sophyane"
    _git_dir(harness)

    root = tmp_path / "badrpk-repos"
    target_repo = root / "rangoons"
    _git_dir(target_repo)

    config = EvolutionConfig(
        repo=harness,
        target_name="rangoons",
        badrpk_root=root,
    )

    engine = EvolutionEngine(config)

    assert engine.repo == harness.resolve()
    assert engine.harness_repo == harness.resolve()
    assert engine.target_repo == target_repo.resolve()
    assert engine.target.name == "rangoons"


def test_repository_name_set_is_stable():
    assert BADRPK_REPOSITORY_NAMES == (
        "Droidra",
        "rangoons",
        "xerus",
        "sophyane",
        "shmry",
        "Veyron",
    )
