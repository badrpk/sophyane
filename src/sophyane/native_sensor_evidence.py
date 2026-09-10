"""Persistent evidence from explicit native sensor operations.

This module never invokes sensors. It only stores and reads bounded results
produced by explicit active sensor actions.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_EVIDENCE_VERSION = 1

_DEFAULT_FRESHNESS_TTL_SECONDS = 300

_ALLOWED_FIELDS = (
    "available",
    "verified",
    "backend",
    "reason",
    "artifact_verified",
    "container_verified",
    "audio_verified",
    "audio_codec",
    "audio_track_declared",
    "audio_codec_declared",
    "transcript_verified",
    "transcript_chars",
    "artifact_path",
    "artifact_bytes",
    "media_payload_bytes",
    "process_returncode",
    "image_verified",
    "image_format",
    "image_width",
    "image_height",
    "jpeg_soi_verified",
    "jpeg_eoi_present",
    "pixel_decode_verified",
    "artifact_sha256",
    "trailing_bytes_after_eoi",
)


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _bounded_command_output(
    command: list[str],
) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return ""

    return str(
        completed.stdout or ""
    ).strip()


def _android_release() -> str:
    value = _bounded_command_output(
        [
            "getprop",
            "ro.build.version.release",
        ]
    )

    if value:
        return value

    return str(
        platform.release() or ""
    ).strip()


def _device_model() -> str:
    value = _bounded_command_output(
        [
            "getprop",
            "ro.product.model",
        ]
    )

    if value:
        return value

    return str(
        platform.machine() or ""
    ).strip()


def _current_platform_fingerprint(
    *,
    backend: str = "termux_api",
) -> dict[str, str]:
    return {
        "android_release": _android_release(),
        "device_model": _device_model(),
        "termux_version": str(
            os.environ.get(
                "TERMUX_VERSION",
                "",
            )
        ).strip(),
        "backend": backend,
    }


def default_sensor_evidence_path() -> Path:
    """Return the persistent native sensor evidence path."""

    override = os.environ.get(
        "SOPHYANE_SENSOR_EVIDENCE_PATH",
        "",
    ).strip()

    if override:
        return Path(override).expanduser()

    return (
        Path.home()
        / ".local"
        / "state"
        / "sophyane"
        / "native-sensor-evidence.json"
    )


def _load_store(
    path: Path,
) -> dict[str, Any]:
    try:
        raw = json.loads(
            path.read_text()
        )
    except (
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return {
            "version": _EVIDENCE_VERSION,
            "probes": {},
        }

    if not isinstance(raw, dict):
        return {
            "version": _EVIDENCE_VERSION,
            "probes": {},
        }

    probes = raw.get("probes")

    if not isinstance(probes, dict):
        probes = {}

    return {
        "version": _EVIDENCE_VERSION,
        "probes": probes,
    }


def _atomic_write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )

    temporary_path = Path(
        temporary
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                sort_keys=True,
            )

            handle.write("\n")
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temporary_path,
            path,
        )

    finally:
        try:
            temporary_path.unlink(
                missing_ok=True,
            )
        except OSError:
            pass


def record_sensor_probe_evidence(
    result: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist one bounded explicit sensor probe result."""

    capability_id = str(
        result.get("id") or ""
    ).strip()

    if not capability_id:
        raise ValueError(
            "sensor probe result requires a non-empty id"
        )

    evidence_path = (
        Path(path).expanduser()
        if path is not None
        else default_sensor_evidence_path()
    )

    stored: dict[str, Any] = {
        "capability_id": capability_id,
        "observed_at": _utc_now().isoformat(),
    }

    platform_fingerprint = dict(
        _current_platform_fingerprint()
    )

    platform_fingerprint[
        "backend"
    ] = str(
        result.get("backend")
        or platform_fingerprint.get(
            "backend"
        )
        or "termux_api"
    )

    stored[
        "platform_fingerprint"
    ] = platform_fingerprint

    for field in _ALLOWED_FIELDS:
        if field in result:
            stored[field] = result[field]

    store = _load_store(
        evidence_path
    )

    probes = dict(
        store.get("probes") or {}
    )

    probes[
        capability_id
    ] = stored

    store = {
        "version": _EVIDENCE_VERSION,
        "probes": probes,
    }

    _atomic_write_json(
        evidence_path,
        store,
    )

    return dict(
        stored
    )


def read_sensor_probe_evidence(
    capability_id: str,
    *,
    path: str | Path | None = None,
    freshness_ttl_seconds: int = _DEFAULT_FRESHNESS_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Read the latest stored evidence for one capability."""

    evidence_path = (
        Path(path).expanduser()
        if path is not None
        else default_sensor_evidence_path()
    )

    store = _load_store(
        evidence_path
    )

    item = (
        store.get("probes") or {}
    ).get(
        str(capability_id)
    )

    if not isinstance(
        item,
        dict,
    ):
        return None

    result = dict(
        item
    )

    artifact_path = result.get(
        "artifact_path"
    )

    if artifact_path:
        try:
            artifact = Path(
                str(artifact_path)
            )

            result[
                "artifact_exists_now"
            ] = artifact.is_file()

        except OSError:
            result[
                "artifact_exists_now"
            ] = False

    enriched = result

    ttl = max(
        0,
        int(
            freshness_ttl_seconds
        ),
    )

    enriched[
        "freshness_ttl_seconds"
    ] = ttl

    observed_at = str(
        enriched.get(
            "observed_at",
            "",
        )
    ).strip()

    age_seconds: float | None = None

    if observed_at:
        try:
            observed = datetime.fromisoformat(
                observed_at
            )

            if observed.tzinfo is None:
                observed = observed.replace(
                    tzinfo=timezone.utc
                )

            age_seconds = max(
                0.0,
                (
                    _utc_now()
                    - observed.astimezone(
                        timezone.utc
                    )
                ).total_seconds(),
            )

        except (
            TypeError,
            ValueError,
        ):
            age_seconds = None

    enriched[
        "age_seconds"
    ] = age_seconds

    stored_fingerprint = enriched.get(
        "platform_fingerprint"
    )

    current_fingerprint = (
        _current_platform_fingerprint()
    )

    # ``backend`` describes the active evidence producer rather than a
    # mutable device identity property. A camera probe can truthfully use
    # android_camera_activity while microphone/STT use termux_api on the
    # same Android/Termux platform. Compare the current platform against
    # the stored backend namespace instead of forcing every capability to
    # equal the default termux_api backend.
    if isinstance(
        stored_fingerprint,
        dict,
    ):
        stored_backend = (
            stored_fingerprint.get(
                "backend"
            )
        )

        if stored_backend:
            current_fingerprint = dict(
                current_fingerprint
            )

            current_fingerprint[
                "backend"
            ] = stored_backend

    current_platform_match = bool(
        isinstance(
            stored_fingerprint,
            dict,
        )
        and stored_fingerprint
        == current_fingerprint
    )

    enriched[
        "current_platform_match"
    ] = current_platform_match

    enriched[
        "fresh"
    ] = bool(
        age_seconds is not None
        and age_seconds <= ttl
        and current_platform_match
    )

    return enriched


def attach_sensor_probe_evidence(
    report: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Attach cached runtime evidence without invoking sensor hardware."""

    enriched = dict(
        report
    )

    capabilities_raw = report.get(
        "capabilities"
    )

    if not isinstance(
        capabilities_raw,
        dict,
    ):
        return enriched

    capabilities: dict[str, Any] = {}

    for capability_id, raw in capabilities_raw.items():
        if isinstance(
            raw,
            dict,
        ):
            item = dict(
                raw
            )
        else:
            item = raw

        if isinstance(
            item,
            dict,
        ):
            last_probe = read_sensor_probe_evidence(
                str(capability_id),
                path=path,
            )

            if last_probe is not None:
                item[
                    "last_probe"
                ] = last_probe

        capabilities[
            capability_id
        ] = item

    enriched[
        "capabilities"
    ] = capabilities

    enriched[
        "runtime_evidence_policy"
    ] = (
        "cached_active_probe_evidence_does_not_replace_"
        "read_only_discovery_truth"
    )

    return enriched
