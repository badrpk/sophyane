from pathlib import Path

from sophyane.evolution.curriculum import (
    generate_task,
    update_score,
    weakest_capability,
)
from sophyane.evolution.models import (
    EvolutionConfig,
)


def test_config_defaults_are_safe(
    tmp_path: Path,
) -> None:
    config = EvolutionConfig(
        repo=tmp_path,
    )

    assert (
        config.allow_candidate_patches
        is False
    )
    assert (
        config.allow_promotion
        is False
    )
    assert config.max_patch_files == 1


def test_curriculum_tracks_capabilities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.evolution.curriculum._local_generate",
        lambda _prompt: (_ for _ in ()).throw(
            OSError("offline")
        ),
    )

    task = generate_task(
        tmp_path,
        1,
    )

    assert task.prompt
    assert task.capability

    update_score(
        tmp_path,
        task.capability,
        True,
    )

    assert weakest_capability(
        tmp_path
    )
