"""Explicit native sensor actions with evidence-backed results.

Unlike native_readonly_capabilities, functions in this module may invoke
device APIs. Command presence and process return code are never sufficient
evidence that a sensor operation succeeded.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from sophyane.native_sensor_evidence import (
    record_sensor_probe_evidence,
)


_GOOGLE_PLAY_API_MESSAGE = (
    "termux:api is not yet available on google play"
)

_RECORD_AUDIO_PERMISSION = (
    "android.permission.record_audio"
)


def _combined_output(
    completed: subprocess.CompletedProcess[str],
) -> str:
    return "\n".join(
        part.strip()
        for part in (
            str(completed.stdout or ""),
            str(completed.stderr or ""),
        )
        if part.strip()
    )


def _run(
    command: list[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return None


def inspect_m4a_artifact(
    path: str | Path,
) -> dict[str, Any]:
    """Inspect top-level ISO-BMFF boxes without external tools."""

    artifact = Path(path)

    try:
        data = artifact.read_bytes()
    except OSError:
        data = b""

    artifact_bytes = len(data)

    has_ftyp = False
    has_mdat = False
    has_moov = False
    media_payload_bytes = 0

    offset = 0
    length = len(data)

    while offset + 8 <= length:
        size = int.from_bytes(
            data[offset:offset + 4],
            "big",
        )

        kind = data[
            offset + 4:
            offset + 8
        ]

        header_size = 8

        if size == 1:
            if offset + 16 > length:
                break

            size = int.from_bytes(
                data[
                    offset + 8:
                    offset + 16
                ],
                "big",
            )

            header_size = 16

        elif size == 0:
            size = length - offset

        if (
            size < header_size
            or offset + size > length
        ):
            break

        payload_size = (
            size - header_size
        )

        if kind == b"ftyp":
            has_ftyp = True

        elif kind == b"mdat":
            has_mdat = True
            media_payload_bytes += max(
                payload_size,
                0,
            )

        elif kind == b"moov":
            has_moov = True

        offset += size

    container_verified = bool(
        has_ftyp
        and has_mdat
        and has_moov
        and media_payload_bytes > 0
    )

    # ISO-BMFF handler/sample-entry markers are stored inside moov/trak.
    # Requiring both markers avoids classifying a generic MP4 container
    # with arbitrary media payload as verified microphone audio.
    audio_track_declared = (
        b"soun" in data
    )

    audio_codec = None

    for codec in (
        b"mp4a",
        b"alac",
        b"ac-3",
        b"ec-3",
        b"Opus",
    ):
        if codec in data:
            audio_codec = codec.decode(
                "ascii",
                errors="replace",
            )
            break

    audio_codec_declared = (
        audio_codec is not None
    )

    audio_verified = bool(
        container_verified
        and audio_track_declared
        and audio_codec_declared
        and media_payload_bytes > 0
    )

    return {
        "artifact_bytes": artifact_bytes,
        "has_ftyp": has_ftyp,
        "has_mdat": has_mdat,
        "has_moov": has_moov,
        "media_payload_bytes": media_payload_bytes,
        "container_verified": container_verified,
        "audio_track_declared": audio_track_declared,
        "audio_codec_declared": audio_codec_declared,
        "audio_codec": audio_codec,
        "audio_verified": audio_verified,
    }


def _base_result(
    *,
    command_path: str | None,
    available: bool,
    verified: bool,
    reason: str,
    artifact_path: str | None,
    artifact_bytes: int = 0,
    artifact_verified: bool = False,
    container_verified: bool = False,
    media_payload_bytes: int = 0,
    audio_verified: bool = False,
    audio_codec: str | None = None,
    audio_track_declared: bool = False,
    audio_codec_declared: bool = False,
    process_returncode: int | None = None,
    output: str = "",
) -> dict[str, Any]:
    return {
        "id": "microphone_capture",
        "command": "termux-microphone-record",
        "command_path": command_path,
        "command_present": bool(command_path),
        "available": available,
        "verified": verified,
        "backend": (
            "termux_api"
            if command_path
            else None
        ),
        "reason": reason,
        "artifact_verified": artifact_verified,
        "container_verified": container_verified,
        "artifact_path": artifact_path,
        "artifact_bytes": artifact_bytes,
        "media_payload_bytes": media_payload_bytes,
        "audio_verified": audio_verified,
        "audio_codec": audio_codec,
        "audio_track_declared": audio_track_declared,
        "audio_codec_declared": audio_codec_declared,
        "process_returncode": process_returncode,
        "output": output,
    }


def probe_microphone_capture(
    *,
    output_dir: str | Path | None = None,
    duration_seconds: int = 1,
) -> dict[str, Any]:
    """Perform one bounded microphone capture and verify media evidence."""

    command = shutil.which(
        "termux-microphone-record"
    )

    if not command:
        return _base_result(
            command_path=None,
            available=False,
            verified=True,
            reason="command_not_found",
            artifact_path=None,
        )

    duration = max(
        1,
        min(
            int(duration_seconds),
            10,
        ),
    )

    root = (
        Path(output_dir).expanduser()
        if output_dir is not None
        else (
            Path.home()
            / ".local"
            / "state"
            / "sophyane"
            / "sensor-probes"
        )
    )

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    artifact = (
        root
        / f"microphone-{time.time_ns()}.m4a"
    )

    try:
        artifact.unlink(
            missing_ok=True,
        )
    except OSError:
        pass

    completed = _run(
        [
            command,
            "-f",
            str(artifact),
            "-l",
            str(duration),
            "-e",
            "aac",
        ],
        timeout=8.0,
    )

    if completed is None:
        return _base_result(
            command_path=command,
            available=False,
            verified=False,
            reason="process_execution_failed",
            artifact_path=str(artifact),
        )

    output = _combined_output(
        completed
    )

    lowered = output.casefold()

    if (
        _RECORD_AUDIO_PERMISSION in lowered
        or (
            "permission" in lowered
            and "record_audio" in lowered
        )
    ):
        return _base_result(
            command_path=command,
            available=False,
            verified=True,
            reason="permission_denied",
            artifact_path=str(artifact),
            process_returncode=completed.returncode,
            output=output,
        )

    if _GOOGLE_PLAY_API_MESSAGE in lowered:
        return _base_result(
            command_path=command,
            available=False,
            verified=True,
            reason=(
                "google_play_termux_api_unavailable"
            ),
            artifact_path=str(artifact),
            process_returncode=completed.returncode,
            output=output,
        )

    if (
        "recording started"
        not in lowered
    ):
        return _base_result(
            command_path=command,
            available=False,
            verified=True,
            reason="recording_not_started",
            artifact_path=str(artifact),
            process_returncode=completed.returncode,
            output=output,
        )

    # termux-microphone-record starts an Android background service.
    # Allow the requested recording interval to elapse before issuing
    # the explicit stop/flush command.
    time.sleep(
        float(duration) + 0.35
    )

    stop_completed = _run(
        [
            command,
            "-q",
        ],
        timeout=5.0,
    )

    stop_output = (
        _combined_output(
            stop_completed
        )
        if stop_completed is not None
        else ""
    )

    combined_output = "\n".join(
        part
        for part in (
            output,
            stop_output,
        )
        if part
    )

    evidence = inspect_m4a_artifact(
        artifact
    )

    artifact_bytes = int(
        evidence["artifact_bytes"]
    )

    container_verified = bool(
        evidence["container_verified"]
    )

    media_payload_bytes = int(
        evidence["media_payload_bytes"]
    )

    audio_verified = bool(
        evidence["audio_verified"]
    )

    audio_codec = evidence.get(
        "audio_codec"
    )

    audio_track_declared = bool(
        evidence["audio_track_declared"]
    )

    audio_codec_declared = bool(
        evidence["audio_codec_declared"]
    )

    if audio_verified:
        return _base_result(
            command_path=command,
            available=True,
            verified=True,
            reason="verified_capture",
            artifact_path=str(artifact),
            artifact_bytes=artifact_bytes,
            artifact_verified=True,
            container_verified=True,
            media_payload_bytes=media_payload_bytes,
            audio_verified=True,
            audio_codec=audio_codec,
            audio_track_declared=audio_track_declared,
            audio_codec_declared=audio_codec_declared,
            process_returncode=completed.returncode,
            output=combined_output,
        )

    if artifact_bytes <= 0:
        reason = "capture_artifact_missing"
    else:
        reason = "capture_artifact_invalid"

    return _base_result(
        command_path=command,
        available=False,
        verified=True,
        reason=reason,
        artifact_path=str(artifact),
        artifact_bytes=artifact_bytes,
        artifact_verified=False,
        container_verified=False,
        media_payload_bytes=media_payload_bytes,
        process_returncode=completed.returncode,
        output=combined_output,
    )


def probe_and_record_microphone_capture(
    *,
    output_dir: str | Path | None = None,
    duration_seconds: int = 1,
    evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run an explicit microphone probe and persist bounded evidence."""

    result = probe_microphone_capture(
        output_dir=output_dir,
        duration_seconds=duration_seconds,
    )

    stored = record_sensor_probe_evidence(
        result,
        path=evidence_path,
    )

    enriched = dict(
        result
    )

    enriched[
        "evidence_recorded"
    ] = True

    enriched[
        "evidence_observed_at"
    ] = stored[
        "observed_at"
    ]

    return enriched


def _speech_to_text_result(
    *,
    command_path: str | None,
    available: bool,
    verified: bool,
    reason: str,
    transcript: str = "",
    process_returncode: int | None = None,
    output: str = "",
) -> dict[str, Any]:
    transcript = str(
        transcript
    ).strip()

    return {
        "id": "speech_to_text",
        "command": "termux-speech-to-text",
        "command_path": command_path,
        "command_present": bool(
            command_path
        ),
        "available": available,
        "verified": verified,
        "backend": (
            "termux_api"
            if available
            else None
        ),
        "reason": reason,
        "transcript": transcript,
        "transcript_verified": bool(
            available
            and verified
            and transcript
        ),
        "transcript_chars": len(
            transcript
        ),
        "process_returncode":
            process_returncode,
        "output": output,
    }



def inspect_jpeg_artifact(
    path: str | Path,
) -> dict[str, Any]:
    """Verify a JPEG by structure and full pixel decode.

    Samsung Motion Photo files may contain payload after the JPEG EOI
    marker, so EOI is required to be present but not necessarily at EOF.
    """

    import hashlib

    try:
        from PIL import Image
    except ImportError:
        Image = None

    artifact = Path(
        path
    )

    try:
        data = artifact.read_bytes()
    except OSError:
        data = b""

    artifact_bytes = len(
        data
    )

    jpeg_soi_verified = bool(
        artifact_bytes >= 2
        and data.startswith(
            b"\xff\xd8"
        )
    )

    jpeg_eoi_offset = (
        data.rfind(
            b"\xff\xd9"
        )
        if jpeg_soi_verified
        else -1
    )

    jpeg_eoi_present = bool(
        jpeg_eoi_offset >= 2
    )

    trailing_bytes_after_eoi = (
        artifact_bytes
        - (
            jpeg_eoi_offset
            + 2
        )
        if jpeg_eoi_present
        else None
    )

    image_format = None
    image_width = None
    image_height = None
    pixel_decode_verified = False

    if (
        artifact_bytes > 0
        and Image is not None
    ):
        try:
            with Image.open(
                artifact
            ) as image:
                image.load()

                image_format = str(
                    image.format
                    or ""
                ).upper() or None

                image_width = int(
                    image.width
                )

                image_height = int(
                    image.height
                )

                pixel_decode_verified = bool(
                    image_format == "JPEG"
                    and image_width > 0
                    and image_height > 0
                )

        except (
            OSError,
            ValueError,
        ):
            pixel_decode_verified = False

    image_verified = bool(
        artifact_bytes > 1000
        and jpeg_soi_verified
        and jpeg_eoi_present
        and pixel_decode_verified
    )

    artifact_sha256 = (
        hashlib.sha256(
            data
        ).hexdigest()
        if data
        else None
    )

    return {
        "artifact_bytes":
            artifact_bytes,
        "artifact_verified":
            image_verified,
        "image_verified":
            image_verified,
        "image_format":
            image_format,
        "image_width":
            image_width,
        "image_height":
            image_height,
        "jpeg_soi_verified":
            jpeg_soi_verified,
        "jpeg_eoi_present":
            jpeg_eoi_present,
        "jpeg_eoi_offset":
            (
                jpeg_eoi_offset
                if jpeg_eoi_present
                else None
            ),
        "trailing_bytes_after_eoi":
            trailing_bytes_after_eoi,
        "pixel_decode_verified":
            pixel_decode_verified,
        "artifact_sha256":
            artifact_sha256,
    }


def _camera_directory_snapshot(
    camera_dir: str | Path,
) -> dict[str, tuple[int, int]]:
    root = Path(
        camera_dir
    )

    records: dict[
        str,
        tuple[int, int],
    ] = {}

    try:
        entries = tuple(
            root.iterdir()
        )
    except OSError:
        return records

    for artifact in entries:
        try:
            if not artifact.is_file():
                continue

            stat = artifact.stat()

        except OSError:
            continue

        records[
            str(artifact)
        ] = (
            int(
                stat.st_size
            ),
            int(
                stat.st_mtime_ns
            ),
        )

    return records


def _new_camera_artifacts(
    *,
    camera_dir: str | Path,
    baseline: dict[
        str,
        tuple[int, int],
    ],
) -> list[Path]:
    current = (
        _camera_directory_snapshot(
            camera_dir
        )
    )

    candidates: list[
        tuple[
            int,
            str,
        ]
    ] = []

    for path, state in current.items():
        previous = baseline.get(
            path
        )

        if (
            previous is None
            or previous != state
        ):
            candidates.append(
                (
                    state[1],
                    path,
                )
            )

    candidates.sort(
        reverse=True
    )

    return [
        Path(path)
        for _, path
        in candidates
    ]


def _camera_result(
    *,
    command_path: str | None,
    available: bool,
    verified: bool,
    reason: str,
    artifact_path: str | None = None,
    process_returncode: int | None = None,
    output: str = "",
    **evidence: Any,
) -> dict[str, Any]:
    result: dict[
        str,
        Any,
    ] = {
        "id": "camera_capture",
        "command": "am",
        "command_path":
            command_path,
        "command_present":
            bool(
                command_path
            ),
        "available":
            available,
        "verified":
            verified,
        "backend": (
            "android_camera_activity"
            if command_path
            else None
        ),
        "reason":
            reason,
        "artifact_path":
            artifact_path,
        "artifact_verified":
            False,
        "image_verified":
            False,
        "process_returncode":
            process_returncode,
        "output":
            output,
    }

    result.update(
        evidence
    )

    return result


def probe_camera_capture(
    *,
    camera_dir: str | Path = (
        "/storage/emulated/0/DCIM/Camera"
    ),
    wait_seconds: int = 60,
) -> dict[str, Any]:
    """Launch Android Camera and verify one newly saved real image."""

    command = shutil.which(
        "am"
    )

    if not command:
        return _camera_result(
            command_path=None,
            available=False,
            verified=True,
            reason="command_not_found",
        )

    root = Path(
        camera_dir
    ).expanduser()

    if not root.is_dir():
        return _camera_result(
            command_path=command,
            available=False,
            verified=True,
            reason="camera_directory_unavailable",
        )

    wait = max(
        0,
        min(
            int(
                wait_seconds
            ),
            120,
        ),
    )

    baseline = (
        _camera_directory_snapshot(
            root
        )
    )

    completed = _run(
        [
            command,
            "start",
            "--user",
            "0",
            "-W",
            "-a",
            (
                "android.media.action."
                "STILL_IMAGE_CAMERA"
            ),
        ],
        timeout=10.0,
    )

    if completed is None:
        return _camera_result(
            command_path=command,
            available=False,
            verified=False,
            reason="process_execution_failed",
        )

    output = _combined_output(
        completed
    )

    lowered = output.casefold()

    if (
        completed.returncode != 0
        or "error:" in lowered
        or "exception" in lowered
    ):
        return _camera_result(
            command_path=command,
            available=False,
            verified=True,
            reason="camera_activity_launch_failed",
            process_returncode=
                completed.returncode,
            output=output,
        )

    deadline = (
        time.monotonic()
        + float(wait)
    )

    while True:
        candidates = (
            _new_camera_artifacts(
                camera_dir=root,
                baseline=baseline,
            )
        )

        for artifact in candidates:
            evidence = (
                inspect_jpeg_artifact(
                    artifact
                )
            )

            if evidence[
                "image_verified"
            ]:
                return _camera_result(
                    command_path=command,
                    available=True,
                    verified=True,
                    reason="verified_capture",
                    artifact_path=str(
                        artifact
                    ),
                    process_returncode=
                        completed.returncode,
                    output=output,
                    **evidence,
                )

        if (
            wait <= 0
            or time.monotonic()
            >= deadline
        ):
            break

        time.sleep(
            0.25
        )

    candidates = (
        _new_camera_artifacts(
            camera_dir=root,
            baseline=baseline,
        )
    )

    if candidates:
        artifact = candidates[0]

        evidence = (
            inspect_jpeg_artifact(
                artifact
            )
        )

        return _camera_result(
            command_path=command,
            available=False,
            verified=True,
            reason="camera_artifact_invalid",
            artifact_path=str(
                artifact
            ),
            process_returncode=
                completed.returncode,
            output=output,
            **evidence,
        )

    return _camera_result(
        command_path=command,
        available=False,
        verified=True,
        reason="no_new_camera_artifact",
        process_returncode=
            completed.returncode,
        output=output,
    )


def probe_and_record_camera_capture(
    *,
    camera_dir: str | Path = (
        "/storage/emulated/0/DCIM/Camera"
    ),
    wait_seconds: int = 60,
    evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run explicit camera capture and persist bounded metadata."""

    result = probe_camera_capture(
        camera_dir=camera_dir,
        wait_seconds=wait_seconds,
    )

    stored = (
        record_sensor_probe_evidence(
            result,
            path=evidence_path,
        )
    )

    enriched = dict(
        result
    )

    enriched[
        "evidence_recorded"
    ] = True

    enriched[
        "evidence_observed_at"
    ] = stored[
        "observed_at"
    ]

    return enriched

def probe_speech_to_text() -> dict[str, Any]:
    """Run one bounded Android speech recognizer operation."""

    command = shutil.which(
        "termux-speech-to-text"
    )

    if not command:
        return _speech_to_text_result(
            command_path=None,
            available=False,
            verified=True,
            reason="command_not_found",
        )

    try:
        completed = subprocess.run(
            [
                command,
            ],
            capture_output=True,
            text=True,
            timeout=20.0,
            check=False,
        )

    except subprocess.TimeoutExpired:
        return _speech_to_text_result(
            command_path=command,
            available=False,
            verified=False,
            reason="probe_timeout",
        )

    except OSError as error:
        return _speech_to_text_result(
            command_path=command,
            available=False,
            verified=False,
            reason="process_execution_failed",
            output=str(
                error
            ),
        )

    stdout = str(
        completed.stdout or ""
    ).strip()

    stderr = str(
        completed.stderr or ""
    ).strip()

    combined = "\n".join(
        part
        for part in (
            stdout,
            stderr,
        )
        if part
    )

    lowered = combined.casefold()

    if (
        "termux:api is not yet available on google play"
        in lowered
    ):
        return _speech_to_text_result(
            command_path=command,
            available=False,
            verified=True,
            reason=(
                "google_play_termux_api_unavailable"
            ),
            process_returncode=completed.returncode,
            output=combined,
        )

    if (
        "permission" in lowered
        and (
            "record_audio" in lowered
            or "microphone" in lowered
        )
    ):
        return _speech_to_text_result(
            command_path=command,
            available=False,
            verified=True,
            reason="permission_denied",
            process_returncode=completed.returncode,
            output=combined,
        )

    transcript = stdout.strip()

    transcript_upper = transcript.upper()

    if transcript_upper in {
        "ERROR: ERROR_NO_MATCH",
        "ERROR_NO_MATCH",
    }:
        return _speech_to_text_result(
            command_path=command,
            available=True,
            verified=True,
            reason="recognizer_no_match",
            process_returncode=completed.returncode,
            output=combined,
        )

    if (
        transcript_upper.startswith("ERROR:")
        or transcript_upper.startswith("ERROR_")
    ):
        return _speech_to_text_result(
            command_path=command,
            available=False,
            verified=True,
            reason="recognizer_error",
            process_returncode=completed.returncode,
            output=combined,
        )

    if not transcript:
        return _speech_to_text_result(
            command_path=command,
            available=False,
            verified=True,
            reason="no_transcript_observed",
            process_returncode=completed.returncode,
            output=combined,
        )

    return _speech_to_text_result(
        command_path=command,
        available=True,
        verified=True,
        reason="verified_transcript",
        transcript=transcript,
        process_returncode=completed.returncode,
        output=combined,
    )


def probe_and_record_speech_to_text(
    *,
    evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run explicit STT and persist metadata without transcript content."""

    result = probe_speech_to_text()

    stored = record_sensor_probe_evidence(
        result,
        path=evidence_path,
    )

    enriched = dict(
        result
    )

    enriched[
        "evidence_recorded"
    ] = True

    enriched[
        "evidence_observed_at"
    ] = stored[
        "observed_at"
    ]

    return enriched
