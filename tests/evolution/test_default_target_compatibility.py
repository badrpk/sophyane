from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.evolution.engine import EvolutionEngine
from sophyane.evolution.models import EvolutionConfig


def test_implicit_default_sophyane_accepts_non_git_repo(
    tmp_path: Path,
) -> None:
    assert not (tmp_path / ".git").exists()

    engine = EvolutionEngine(
        EvolutionConfig(
            repo=tmp_path,
        )
    )

    assert engine.repo == tmp_path.resolve()
    assert engine.harness_repo == tmp_path.resolve()

    assert engine.target.name == "sophyane"
    assert engine.target.repo == tmp_path.resolve()
    assert engine.target.harness_repo == tmp_path.resolve()

    assert engine.target.git_repo is False


def test_explicit_target_repo_remains_strict(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "harness"
    explicit = tmp_path / "explicit"

    harness.mkdir()
    explicit.mkdir()

    assert not (explicit / ".git").exists()

    with pytest.raises(
        ValueError,
        match="not a git repository",
    ):
        EvolutionEngine(
            EvolutionConfig(
                repo=harness,
                target_repo=explicit,
            )
        )


def test_explicit_badrpk_root_keeps_strictness(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "harness"
    badrpk_root = tmp_path / "badrpk-repos"

    harness.mkdir()
    badrpk_root.mkdir()

    # An explicitly supplied BADRPK root is target-selection
    # intent even when the target name retains its default.
    with pytest.raises(
        ValueError,
        match="not a git repository",
    ):
        EvolutionEngine(
            EvolutionConfig(
                repo=harness,
                badrpk_root=badrpk_root,
            )
        )


def test_non_default_target_name_remains_strict(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "harness"
    badrpk_root = tmp_path / "badrpk-repos"
    target = badrpk_root / "Droidra"

    harness.mkdir()
    target.mkdir(parents=True)

    assert not (target / ".git").exists()

    with pytest.raises(
        ValueError,
        match="not a git repository",
    ):
        EvolutionEngine(
            EvolutionConfig(
                repo=harness,
                target_name="droidra",
                badrpk_root=badrpk_root,
            )
        )
