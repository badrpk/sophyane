from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import sophyane.browser_partial_recovery as bpr


def _rendered():
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


def _report(*, score, accepted):
    return {
        "accepted": accepted,
        "score": score,
        "critical_issues": 0 if accepted else 1,
        "unmet_requirements": 0 if accepted else 1,
        "repair_code": (
            "NONE"
            if accepted
            else "VISUAL_HIERARCHY"
        ),
    }


def test_runtime_hook_writes_episode_even_if_xerus_fails(
    monkeypatch,
    tmp_path: Path,
):
    workspace = tmp_path
    quality = workspace / ".sophyane" / "visual-quality"
    quality.mkdir(parents=True)

    html = quality / "iteration-1.html"
    shot = quality / "iteration-1.png"

    html.write_text(
        "<html><body>premium dogs website</body></html>",
        encoding="utf-8",
    )

    # Hashing only; Neuron is stubbed below.
    shot.write_bytes(
        b"\x89PNG" + b"x" * 2000
    )

    import sophyane.creative_episode as ce

    def fake_enrich(episode, *, screenshot_path):
        from dataclasses import replace

        return replace(
            episode,
            perceptual_signature="ctx-123",
            pixel_digest="pixel-123",
            perception_status="ok",
            perception_error="",
        )

    monkeypatch.setattr(
        ce,
        "enrich_with_neuron",
        fake_enrich,
    )

    monkeypatch.setattr(
        ce,
        "persist_to_xerus",
        lambda episode: {
            "ok": False,
            "reason": "test unavailable",
        },
    )

    messages = []

    score, artifact_hash = bpr._record_creative_episode(
        workspace=workspace,
        target=workspace / "index.html",
        original_request=(
            "make a premium modern dogs website "
            "with professional photography"
        ),
        rendered=_rendered(),
        report=_report(
            score=86,
            accepted=False,
        ),
        iteration=1,
        screenshot=shot,
        iteration_html=html,
        iteration_screenshot=shot,
        previous_score=None,
        parent_artifact_sha256="",
        progress=messages.append,
    )

    assert score == 86
    assert len(artifact_hash) == 64

    saved = (
        quality
        / "iteration-1-episode.json"
    )

    assert saved.is_file()

    data = json.loads(
        saved.read_text(encoding="utf-8")
    )

    assert data["judge_score"] == 86
    assert data["accepted"] is False
    assert data["perception_status"] == "ok"
    assert data["perceptual_signature"] == "ctx-123"

    assert any(
        "Xerus=unavailable" in message
        for message in messages
    )


def test_episode_chain_records_score_delta(
    monkeypatch,
    tmp_path: Path,
):
    workspace = tmp_path
    quality = workspace / ".sophyane" / "visual-quality"
    quality.mkdir(parents=True)

    import sophyane.creative_episode as ce

    monkeypatch.setattr(
        ce,
        "enrich_with_neuron",
        lambda episode, screenshot_path: episode,
    )

    monkeypatch.setattr(
        ce,
        "persist_to_xerus",
        lambda episode: {"ok": True},
    )

    previous_score = None
    previous_hash = ""

    for iteration, score, accepted in (
        (1, 86, False),
        (2, 96, True),
    ):
        html = quality / f"iteration-{iteration}.html"
        shot = quality / f"iteration-{iteration}.png"

        html.write_text(
            f"<html><body>{iteration}</body></html>",
            encoding="utf-8",
        )
        shot.write_bytes(
            b"\x89PNG"
            + bytes([iteration])
            + b"x" * 2000
        )

        previous_score, previous_hash = (
            bpr._record_creative_episode(
                workspace=workspace,
                target=workspace / "index.html",
                original_request="premium dogs website",
                rendered=_rendered(),
                report=_report(
                    score=score,
                    accepted=accepted,
                ),
                iteration=iteration,
                screenshot=shot,
                iteration_html=html,
                iteration_screenshot=shot,
                previous_score=previous_score,
                parent_artifact_sha256=previous_hash,
                progress=lambda _: None,
            )
        )

    first = json.loads(
        (
            quality
            / "iteration-1-episode.json"
        ).read_text(encoding="utf-8")
    )

    second = json.loads(
        (
            quality
            / "iteration-2-episode.json"
        ).read_text(encoding="utf-8")
    )

    assert first["previous_score"] is None
    assert first["score_delta"] is None

    assert second["previous_score"] == 86
    assert second["score_delta"] == 10

    assert (
        second["parent_artifact_sha256"]
        == first["artifact_sha256"]
    )


def test_memory_exception_does_not_change_report_authority(
    monkeypatch,
    tmp_path: Path,
):
    quality = tmp_path / ".sophyane" / "visual-quality"
    quality.mkdir(parents=True)

    html = quality / "iteration-1.html"
    shot = quality / "iteration-1.png"

    html.write_text(
        "<html><body>ok</body></html>",
        encoding="utf-8",
    )
    shot.write_bytes(
        b"\x89PNG" + b"x" * 2000
    )

    import sophyane.creative_episode as ce

    monkeypatch.setattr(
        ce,
        "persist_to_xerus",
        lambda episode: (_ for _ in ()).throw(
            RuntimeError("memory down")
        ),
    )

    report = _report(
        score=96,
        accepted=True,
    )

    score, _ = bpr._record_creative_episode(
        workspace=tmp_path,
        target=tmp_path / "index.html",
        original_request="premium dogs website",
        rendered=_rendered(),
        report=report,
        iteration=1,
        screenshot=shot,
        iteration_html=html,
        iteration_screenshot=shot,
        previous_score=None,
        parent_artifact_sha256="",
        progress=lambda _: None,
    )

    assert score == 96
    assert report["accepted"] is True
    assert report["score"] == 96
