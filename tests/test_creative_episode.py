from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sophyane.creative_episode import (
    NAMESPACE,
    build_episode,
    objective_hash,
    persist_to_xerus,
    recall_creative_episodes,
    searchable_content,
)


def rendered():
    return SimpleNamespace(
        viewport_width=390,
        viewport_height=844,
        document_width=390,
        document_height=7904,
        images=14,
        broken_images=0,
        console_errors=0,
        log_errors=0,
        horizontal_overflow=False,
    )


def report(*, score=96, accepted=True):
    return {
        "accepted": accepted,
        "score": score,
        "critical_issues": 0 if accepted else 1,
        "unmet_requirements": 0 if accepted else 1,
        "repair_code": "NONE" if accepted else "VISUAL_HIERARCHY",
    }


def make_episode(tmp_path, **kwargs):
    html = tmp_path / "index.html"
    png = tmp_path / "shot.png"

    html.write_text(
        "<html><body>dogs</body></html>",
        encoding="utf-8",
    )
    png.write_bytes(b"\x89PNG" + b"x" * 2000)

    return build_episode(
        objective=(
            "make a premium modern dogs website "
            "with professional photography"
        ),
        artifact_path=html,
        screenshot_path=png,
        iteration=kwargs.get("iteration", 2),
        provider_id="nifdu_browser",
        rendered=rendered(),
        report=report(
            score=kwargs.get("score", 96),
            accepted=kwargs.get("accepted", True),
        ),
        parent_artifact_sha256="abc",
        previous_score=kwargs.get("previous_score", 86),
    )


def test_episode_hashes_and_delta(tmp_path):
    episode = make_episode(tmp_path)

    assert len(episode.objective_hash) == 64
    assert len(episode.artifact_sha256) == 64
    assert len(episode.screenshot_sha256) == 64
    assert len(episode.episode_id) == 32
    assert episode.score_delta == 10
    assert episode.accepted is True


def test_objective_hash_normalizes_whitespace():
    assert objective_hash("make   dogs\nwebsite") == objective_hash(
        "make dogs website"
    )


def test_searchable_content_contains_recall_terms(tmp_path):
    episode = make_episode(tmp_path)
    content = searchable_content(episode)

    assert "dogs website" in content
    assert "accepted" in content
    assert "score 96" in content


def test_xerus_round_trip(monkeypatch, tmp_path):
    repo = tmp_path / "xerus"
    source = repo / "src" / "xerus"
    source.mkdir(parents=True)

    real = (
        Path.home()
        / "badrpk-repos"
        / "xerus"
        / "src"
        / "xerus"
        / "memory.py"
    )

    if not real.is_file():
        import pytest
        pytest.skip("local Xerus runtime unavailable")

    (source / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )

    (source / "memory.py").write_text(
        real.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    state = tmp_path / "xerus-state"
    monkeypatch.setenv(
        "XERUS_HOME",
        str(state),
    )

    map_path = tmp_path / "repos.json"
    map_path.write_text(
        json.dumps({
            "schema": 1,
            "repositories": {
                "xerus": str(repo),
            },
        }),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_ECOSYSTEM_REPO_MAP",
        str(map_path),
    )

    episode = make_episode(tmp_path)

    result = persist_to_xerus(episode)

    assert result["ok"] is True

    hits = recall_creative_episodes(
        "premium dogs website photography",
        limit=5,
    )

    assert len(hits) == 1
    assert hits[0]["namespace"] == NAMESPACE

    metadata = hits[0]["metadata"]

    assert metadata["judge_score"] == 96
    assert metadata["accepted"] is True
    assert metadata["repair_code"] == "NONE"


def test_same_episode_is_latest_authority(monkeypatch, tmp_path):
    repo = tmp_path / "xerus"
    source = repo / "src" / "xerus"
    source.mkdir(parents=True)

    real = (
        Path.home()
        / "badrpk-repos"
        / "xerus"
        / "src"
        / "xerus"
        / "memory.py"
    )

    if not real.is_file():
        import pytest
        pytest.skip("local Xerus runtime unavailable")

    (source / "__init__.py").write_text("")
    (source / "memory.py").write_text(
        real.read_text(encoding="utf-8")
    )

    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path / "state"),
    )

    map_path = tmp_path / "repos.json"
    map_path.write_text(
        json.dumps({
            "schema": 1,
            "repositories": {
                "xerus": str(repo),
            },
        })
    )

    monkeypatch.setenv(
        "SOPHYANE_ECOSYSTEM_REPO_MAP",
        str(map_path),
    )

    episode = make_episode(tmp_path)

    first = persist_to_xerus(episode)
    second = persist_to_xerus(episode)

    assert first["memory_key"] == second["memory_key"]

    hits = recall_creative_episodes(
        "dogs website",
        limit=10,
    )

    assert len(hits) == 1
