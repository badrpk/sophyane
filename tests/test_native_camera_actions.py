from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import sophyane.native_sensor_actions as actions


def _completed(
    *,
    returncode=0,
    stdout="",
    stderr="",
):
    return SimpleNamespace(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _jpeg(
    path: Path,
    *,
    width: int = 64,
    height: int = 48,
    trailing: bytes = b"",
) -> None:
    image = Image.new(
        "RGB",
        (width, height),
        (12, 34, 56),
    )

    image.save(
        path,
        format="JPEG",
        quality=90,
    )

    if trailing:
        with path.open("ab") as stream:
            stream.write(trailing)


def test_inspect_jpeg_accepts_trailing_motion_photo_payload(
    tmp_path,
):
    path = tmp_path / "motion-photo.jpg"

    _jpeg(
        path,
        width=400,
        height=225,
        trailing=(
            b"\x00" * 64
            + b"MotionPhoto"
            + b"\x00" * 64
        ),
    )

    result = actions.inspect_jpeg_artifact(
        path
    )

    assert result["artifact_verified"] is True
    assert result["image_verified"] is True
    assert result["image_format"] == "JPEG"
    assert result["image_width"] == 400
    assert result["image_height"] == 225
    assert result["jpeg_soi_verified"] is True
    assert result["jpeg_eoi_present"] is True
    assert result["pixel_decode_verified"] is True
    assert result["artifact_bytes"] > 1000
    assert len(result["artifact_sha256"]) == 64


def test_inspect_jpeg_rejects_non_image(
    tmp_path,
):
    path = tmp_path / "fake.jpg"

    path.write_bytes(
        b"\xff\xd8"
        + b"not-a-real-jpeg"
        + b"\xff\xd9"
    )

    result = actions.inspect_jpeg_artifact(
        path
    )

    assert result["artifact_verified"] is False
    assert result["image_verified"] is False
    assert result["pixel_decode_verified"] is False


def test_camera_capture_requires_new_real_artifact(
    monkeypatch,
    tmp_path,
):
    camera_dir = tmp_path / "Camera"

    camera_dir.mkdir()

    old = camera_dir / "old.jpg"

    _jpeg(old)

    calls = []

    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/am"
            if name == "am"
            else None
        ),
    )

    def fake_run(command, **kwargs):
        calls.append(
            tuple(command)
        )

        assert command == [
            "/mock/am",
            "start",
            "--user",
            "0",
            "-W",
            "-a",
            "android.media.action.STILL_IMAGE_CAMERA",
        ]

        new = camera_dir / "new.jpg"

        _jpeg(
            new,
            width=320,
            height=180,
            trailing=b"MotionPhoto",
        )

        return _completed(
            returncode=0,
            stdout=(
                "Starting: Intent "
                "{ act=android.media.action.STILL_IMAGE_CAMERA }"
            ),
        )

    monkeypatch.setattr(
        actions,
        "_run",
        fake_run,
    )

    result = actions.probe_camera_capture(
        camera_dir=camera_dir,
        wait_seconds=1,
    )

    assert calls
    assert result["id"] == "camera_capture"
    assert result["available"] is True
    assert result["verified"] is True
    assert result["backend"] == "android_camera_activity"
    assert result["reason"] == "verified_capture"
    assert result["artifact_verified"] is True
    assert result["image_verified"] is True
    assert result["image_format"] == "JPEG"
    assert result["image_width"] == 320
    assert result["image_height"] == 180
    assert result["artifact_bytes"] > 1000
    assert len(result["artifact_sha256"]) == 64
    assert result["process_returncode"] == 0


def test_camera_zero_exit_without_new_artifact_is_not_success(
    monkeypatch,
    tmp_path,
):
    camera_dir = tmp_path / "Camera"

    camera_dir.mkdir()

    _jpeg(
        camera_dir / "existing.jpg"
    )

    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/am"
            if name == "am"
            else None
        ),
    )

    monkeypatch.setattr(
        actions,
        "_run",
        lambda *args, **kwargs: _completed(
            returncode=0,
            stdout="Starting camera",
        ),
    )

    monkeypatch.setattr(
        actions.time,
        "sleep",
        lambda seconds: None,
    )

    result = actions.probe_camera_capture(
        camera_dir=camera_dir,
        wait_seconds=0,
    )

    assert result["available"] is False
    assert result["verified"] is True
    assert result["artifact_verified"] is False
    assert result["image_verified"] is False
    assert result["reason"] == "no_new_camera_artifact"


def test_camera_activity_launch_failure_is_not_available(
    monkeypatch,
    tmp_path,
):
    camera_dir = tmp_path / "Camera"

    camera_dir.mkdir()

    monkeypatch.setattr(
        actions.shutil,
        "which",
        lambda name: (
            "/mock/am"
            if name == "am"
            else None
        ),
    )

    monkeypatch.setattr(
        actions,
        "_run",
        lambda *args, **kwargs: _completed(
            returncode=1,
            stderr="Error: Activity not started",
        ),
    )

    result = actions.probe_camera_capture(
        camera_dir=camera_dir,
        wait_seconds=0,
    )

    assert result["available"] is False
    assert result["verified"] is True
    assert result["reason"] == "camera_activity_launch_failed"


def test_probe_and_record_camera_capture_persists_evidence(
    monkeypatch,
    tmp_path,
):
    camera_dir = tmp_path / "Camera"

    camera_dir.mkdir()

    image_path = camera_dir / "captured.jpg"

    _jpeg(
        image_path,
        width=128,
        height=72,
    )

    expected = {
        "id": "camera_capture",
        "command": "am",
        "command_path": "/mock/am",
        "command_present": True,
        "available": True,
        "verified": True,
        "backend": "android_camera_activity",
        "reason": "verified_capture",
        "artifact_path": str(image_path),
        "artifact_bytes": image_path.stat().st_size,
        "artifact_verified": True,
        "image_verified": True,
        "image_format": "JPEG",
        "image_width": 128,
        "image_height": 72,
        "artifact_sha256": "a" * 64,
        "process_returncode": 0,
        "output": "Starting camera",
    }

    monkeypatch.setattr(
        actions,
        "probe_camera_capture",
        lambda **kwargs: dict(expected),
    )

    stored_calls = []

    monkeypatch.setattr(
        actions,
        "record_sensor_probe_evidence",
        lambda result, *, path=None: (
            stored_calls.append(
                (dict(result), path)
            )
            or {
                "observed_at":
                    "2026-09-08T11:00:00+00:00",
            }
        ),
    )

    evidence_path = (
        tmp_path / "evidence.json"
    )

    result = (
        actions.probe_and_record_camera_capture(
            camera_dir=camera_dir,
            wait_seconds=30,
            evidence_path=evidence_path,
        )
    )

    assert len(stored_calls) == 1
    assert (
        stored_calls[0][0]["id"]
        == "camera_capture"
    )
    assert (
        stored_calls[0][1]
        == evidence_path
    )

    assert result["available"] is True
    assert result["image_verified"] is True
    assert result["evidence_recorded"] is True
    assert (
        result["evidence_observed_at"]
        == "2026-09-08T11:00:00+00:00"
    )
