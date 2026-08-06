import json
from pathlib import Path

from sophyane.evolution.curriculum import (
    capability_mastered,
    focused_capability,
)


def test_curriculum_stays_on_unmastered_capability(
    tmp_path: Path,
) -> None:
    root = (
        tmp_path
        / ".sophyane-evolution"
    )
    root.mkdir(parents=True)

    scores = {
        "filesystem": {
            "attempts": 20,
            "passes": 20,
            "rate": 1.0,
        },
        "shell": {
            "attempts": 20,
            "passes": 19,
            "rate": 0.95,
        },
        "python": {
            "attempts": 20,
            "passes": 5,
            "rate": 0.25,
        },
        "html": {
            "attempts": 20,
            "passes": 18,
            "rate": 0.90,
        },
        "semantic_routing": {
            "attempts": 20,
            "passes": 17,
            "rate": 0.85,
        },
        "security": {
            "attempts": 20,
            "passes": 20,
            "rate": 1.0,
        },
    }

    (
        root
        / "capability-scores.json"
    ).write_text(
        json.dumps(scores),
        encoding="utf-8",
    )

    assert (
        focused_capability(
            tmp_path,
            threshold=0.90,
            minimum_samples=20,
        )
        == "python"
    )

    assert (
        capability_mastered(
            tmp_path,
            "shell",
            threshold=0.90,
            minimum_samples=20,
        )
        is True
    )
