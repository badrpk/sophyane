from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from sophyane.human_conversation import (
    conversation_turn,
    human_conversation_status,
)

from sophyane.native_sensor_actions import (
    probe_and_record_camera_capture,
    probe_and_record_speech_to_text,
)

from sophyane.native_readonly_capabilities import (
    native_sensor_capabilities,
)
from sophyane.native_sensor_evidence import (
    attach_sensor_probe_evidence,
)


def _repository_execution_request(text: str) -> bool:
    """Return whether text explicitly requests repository execution.

    Classification is deliberately conservative. An executable verb alone is
    insufficient: the request must also identify repository/workspace work.
    Explanatory, advisory, and opinion questions remain conversational.
    """

    normalized = " ".join(
        str(text or "").casefold().split()
    )

    if not normalized:
        return False

    conversational_prefixes = (
        "explain ",
        "what is ",
        "what are ",
        "what does ",
        "how does ",
        "how could ",
        "how can i ",
        "tell me how ",
        "do you think ",
    )

    if normalized.startswith(
        conversational_prefixes
    ):
        return False

    executable = bool(
        re.search(
            r"\b(?:modify|patch|fix|create|make|delete|remove|"
            r"run|build|test|inspect|edit|replace|update)\b",
            normalized,
        )
    )

    if not executable:
        return False

    repository_context = bool(
        re.search(
            r"(?:"
            r"\brepository\b|"
            r"\brepo\b|"
            r"\bworkspace\b|"
            r"\btests?\b|"
            r"\bbuild\b|"
            r"\btargeted_patch\b|"
            r"(?:^|[\s`'\"])(?:\.{0,2}/)?"
            r"(?:[\w.-]+/)+[\w.-]+|"
            r"\b[\w.-]+\.(?:py|pyi|js|ts|tsx|jsx|json|"
            r"toml|yaml|yml|md|txt|html|css|sh|bash|lean)\b"
            r")",
            normalized,
        )
    )

    return executable and repository_context



def _gallery_roots() -> tuple[Path, ...]:
    """Return ordinary readable gallery locations without prompting."""

    home = Path.home()

    candidates = (
        home / "storage" / "dcim",
        home / "storage" / "pictures",
        Path("/storage/emulated/0/DCIM"),
        Path("/storage/emulated/0/Pictures"),
        Path("/sdcard/DCIM"),
        Path("/sdcard/Pictures"),
    )

    unique: list[Path] = []
    seen: set[str] = set()

    for candidate in candidates:
        key = str(candidate)

        if key in seen:
            continue

        seen.add(key)
        unique.append(candidate)

    return tuple(unique)


def _gallery_photo_paths() -> list[Path]:
    """Discover readable image files from existing gallery storage."""

    image_suffixes = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".heic",
        ".heif",
    }

    discovered: list[Path] = []
    seen: set[str] = set()

    for root in _gallery_roots():
        try:
            if not root.is_dir():
                continue

            candidates = list(root.rglob("*"))

        except OSError:
            continue

        for candidate in candidates:
            try:
                if (
                    not candidate.is_file()
                    or candidate.suffix.casefold()
                    not in image_suffixes
                ):
                    continue

                resolved = candidate.resolve()

            except OSError:
                continue

            key = str(resolved)

            if key in seen:
                continue

            seen.add(key)
            discovered.append(resolved)

    return sorted(
        discovered,
        key=lambda value: str(value).casefold(),
    )


def _enrich_gallery_execution_request(
    text: str,
    *,
    active_request: str,
) -> str:
    """Attach deterministic real gallery paths to an active task."""

    active = str(active_request or "").strip()
    followup = str(text or "").strip()

    parts = [
        value
        for value in (
            active,
            followup,
        )
        if value
    ]

    base_request = "\n".join(parts)

    photos = _gallery_photo_paths()

    if not photos:
        return (
            base_request
            + "\n\n"
            + "No readable gallery images were found in the "
              "currently available filesystem locations."
        )

    seed = (
        active
        + "\n"
        + followup
    ).encode(
        "utf-8",
        errors="surrogatepass",
    )

    def deterministic_key(path: Path) -> bytes:
        digest = hashlib.sha256()
        digest.update(seed)
        digest.update(b"\0")
        digest.update(
            str(path).encode(
                "utf-8",
                errors="surrogatepass",
            )
        )
        return digest.digest()

    selected = sorted(
        photos,
        key=deterministic_key,
    )[:20]

    path_lines = "\n".join(
        f"- {path}"
        for path in selected
    )

    return (
        base_request
        + "\n\n"
        + "Gallery filesystem access is already available.\n"
        + "Do not request photo/media permission.\n"
        + "Use these real image paths for the task:\n"
        + path_lines
    )


def _continue_execution_request(
    text: str,
    *,
    active_request: str,
) -> str:
    """Combine a natural follow-up with the currently active task."""

    followup = str(text or "").strip()
    active = str(active_request or "").strip()

    normalized = followup.casefold()

    gallery_followup = bool(
        "gallery" in normalized
        and any(
            word in normalized
            for word in (
                "photo",
                "photos",
                "picture",
                "pictures",
                "image",
                "images",
            )
        )
    )

    if gallery_followup:
        return _enrich_gallery_execution_request(
            followup,
            active_request=active,
        )

    if not active:
        return followup

    if not followup:
        return active

    return active + "\n" + followup


def _execute_repository_request(
    text: str,
    *,
    workspace: Path | None = None,
) -> str:
    """Execute an explicit repository request through the canonical runtime."""

    from sophyane.adaptive_execution import (
        execution_prefix_for_repair,
        run_adaptive_loop,
    )
    from sophyane.config import load_config
    from sophyane.main import create_provider
    from sophyane.request_classification import (
        RepositoryCapability,
        classify_repository_capability,
    )
    from sophyane.rsi.authority import Operation

    request = str(text or "").strip()

    if not request:
        raise ValueError(
            "repository execution request must be non-empty"
        )

    capability = classify_repository_capability(request)
    operation = (
        Operation.READ_ONLY_OPERATION
        if capability is RepositoryCapability.READ_ONLY
        else Operation.SOPHYANE_SOURCE_MUTATION
    )

    from sophyane.main import load_runtime_config

    provider = create_provider(
        load_runtime_config()
        if os.environ.get("SOPHYANE_SESSION_MODE", "").strip().lower() == "human_conversation"
        else load_config()
    )

    system_prompt = (
        "You are Sophyane's repository execution provider. "
        "Follow the supplied execution contract exactly. "
        "Return executable JSON actions only when requested. "
        "Do not claim an action succeeded before the runtime verifies it."
    )

    def ask(prompt: str) -> str:
        from sophyane.providers.human_conversation import HumanConversationProvider

        if isinstance(provider, HumanConversationProvider):
            return str(
                provider.generate(
                    str(prompt),
                    system_prompt,
                    operation=operation,
                )
            )
        return str(
            provider.generate(
                str(prompt),
                system_prompt,
            )
        )

    initial_prompt = (
        execution_prefix_for_repair(
            request
        )
        + "\n\nORIGINAL TASK:\n"
        + request
        + "\n\nChoose the single next executable action "
          "for this task."
    )

    initial_text = ask(
        initial_prompt
    )

    resolved_workspace = (
        workspace.resolve()
        if workspace is not None
        else None
    )

    return run_adaptive_loop(
        initial_text=initial_text,
        original_request=request,
        ask=ask,
        workspace=resolved_workspace,
        max_steps=16,
    )

def _print_voice_status() -> None:
    """Print read-only STT discovery and cached evidence."""

    report = native_sensor_capabilities()
    report = attach_sensor_probe_evidence(
        report
    )

    capability = (
        report.get("capabilities", {})
        .get("speech_to_text", {})
    )

    def yes_no(value) -> str:
        return (
            "yes"
            if bool(value)
            else "no"
        )

    print(
        "\nSophyane voice status:"
    )

    print(
        "  Discovery available:",
        yes_no(
            capability.get("available")
        ),
    )

    print(
        "  Discovery verified:",
        yes_no(
            capability.get("verified")
        ),
    )

    print(
        "  Discovery reason:",
        str(
            capability.get(
                "reason",
                "unknown",
            )
        ),
    )

    last_probe = capability.get(
        "last_probe"
    )

    if not isinstance(
        last_probe,
        dict,
    ):
        print(
            "  Last probe: none"
        )
        return

    print(
        "  Last probe reason:",
        str(
            last_probe.get(
                "reason",
                "unknown",
            )
        ),
    )

    print(
        "  Last probe fresh:",
        yes_no(
            last_probe.get("fresh")
        ),
    )

    print(
        "  Platform match:",
        yes_no(
            last_probe.get(
                "current_platform_match"
            )
        ),
    )

    age = last_probe.get(
        "age_seconds"
    )

    if age is not None:
        print(
            "  Last probe age seconds:",
            age,
        )

    ttl = last_probe.get(
        "freshness_ttl_seconds"
    )

    if ttl is not None:
        print(
            "  Freshness TTL seconds:",
            ttl,
        )


def _voice_input_text() -> str | None:
    """Run one explicit live STT action for /voice only."""

    print(
        "\nSophyane voice: Listening..."
    )

    try:
        probe = (
            probe_and_record_speech_to_text()
        )

    except Exception:
        print(
            "\nSophyane voice:",
            "Speech recognition could not be completed.",
        )

        return None

    reason = str(
        probe.get(
            "reason",
            "",
        )
    )

    transcript = str(
        probe.get(
            "transcript",
            "",
        )
    ).strip()

    transcript_verified = bool(
        probe.get(
            "transcript_verified"
        )
    )

    if (
        reason == "verified_transcript"
        and transcript_verified
        and transcript
    ):
        print(
            "\nYou (voice):",
            transcript,
        )

        return transcript

    messages = {
        "recognizer_no_match": (
            "No speech was recognized."
        ),
        "no_transcript_observed": (
            "No speech transcript was returned."
        ),
        "permission_denied": (
            "Microphone permission is not available."
        ),
        "probe_timeout": (
            "Speech recognition timed out."
        ),
        "recognizer_error": (
            "Speech recognizer returned an error."
        ),
        "command_not_found": (
            "Speech recognition command is not installed."
        ),
        "google_play_termux_api_unavailable": (
            "Termux:API speech recognition is not available "
            "in this environment."
        ),
        "process_execution_failed": (
            "Speech recognition could not be started."
        ),
    }

    message = messages.get(
        reason,
        (
            "Speech recognition did not produce "
            "a verified transcript."
        ),
    )

    print(
        "\nSophyane voice:",
        message,
    )

    return None




def _automatic_perception_intent(
    text: str,
) -> str | None:
    """Select a sensor only for clear current-world perception intent.

    This intentionally starts conservative. Mentioning a camera does not
    itself activate hardware. The request must ask Sophyane to visually
    observe the user's present surroundings.
    """

    normalized = " ".join(
        str(
            text
            or ""
        )
        .casefold()
        .strip()
        .split()
    )

    if not normalized:
        return None

    direct_visual_requests = (
        "what do you see",
        "what can you see",
        "can you see what",
        "can you see me",
        "look around",
        "look at this",
        "look at me",
        "look in front",
        "use your camera",
        "use the camera",
        "check the camera",
        "see what is",
        "see what's",
        "tell me what you see",
        "tell me what is in front",
    )

    if any(
        phrase in normalized
        for phrase in direct_visual_requests
    ):
        return "camera"

    terminal_visual_questions = {
        "do you see",
        "can you see",
        "are you able to see",
        "can you look",
        "can you look around",
    }

    terminal = normalized.rstrip(
        "?!."
    ).strip()

    if terminal in terminal_visual_questions:
        return "camera"

    return None


def _camera_visual_input() -> tuple[str, dict] | None:
    """Run one explicit verified camera capture for /see only."""

    print(
        "\nSophyane vision: Opening camera..."
    )

    try:
        probe = (
            probe_and_record_camera_capture()
        )

    except Exception:
        print(
            "\nSophyane vision:",
            "Camera capture could not be completed.",
        )

        return None

    valid = bool(
        probe.get(
            "available"
        )
        is True
        and probe.get(
            "verified"
        )
        is True
        and str(
            probe.get(
                "reason",
                "",
            )
        )
        == "verified_capture"
        and probe.get(
            "artifact_verified"
        )
        is True
        and probe.get(
            "image_verified"
        )
        is True
        and probe.get(
            "pixel_decode_verified"
        )
        is True
    )

    artifact_path = str(
        probe.get(
            "artifact_path",
            "",
        )
        or ""
    ).strip()

    if (
        not valid
        or not artifact_path
    ):
        print(
            "\nSophyane vision:",
            "Camera did not produce a verified image.",
        )

        return None

    metadata = {
        "input_mode": "camera",
        "visual_artifact": {
            "backend": str(
                probe.get(
                    "backend"
                )
                or ""
            ),
            "artifact_sha256": str(
                probe.get(
                    "artifact_sha256"
                )
                or ""
            ),
            "artifact_bytes": int(
                probe.get(
                    "artifact_bytes"
                )
                or 0
            ),
            "image_format": str(
                probe.get(
                    "image_format"
                )
                or ""
            ),
            "image_width": int(
                probe.get(
                    "image_width"
                )
                or 0
            ),
            "image_height": int(
                probe.get(
                    "image_height"
                )
                or 0
            ),
            "pixel_decode_verified": True,
            "evidence_observed_at": str(
                probe.get(
                    "evidence_observed_at"
                )
                or ""
            ),
        },
    }

    print(
        "\nSophyane vision:",
        "Verified camera image captured."
    )

    return (
        artifact_path,
        metadata,
    )


def _camera_hardware_api_factory():
    """Return the read-only hardware API facade."""

    from sophyane.hardware_api import HardwareAPI

    return HardwareAPI()


def _camera_status_report() -> dict:
    """Read camera discovery/evidence without activating hardware."""

    return (
        _camera_hardware_api_factory()
        .sensors()
    )


def _yes_no(value: object) -> str:
    return (
        "yes"
        if value is True
        else "no"
    )


def _camera_status_text() -> str:
    """Format read-only camera discovery and cached evidence."""

    report = _camera_status_report()

    capabilities = report.get(
        "capabilities"
    )

    if not isinstance(
        capabilities,
        dict,
    ):
        return (
            "Camera status unavailable: "
            "sensor capability report missing."
        )

    camera = capabilities.get(
        "camera_capture"
    )

    if not isinstance(
        camera,
        dict,
    ):
        return (
            "Camera status unavailable: "
            "camera capability missing."
        )

    lines = [
        "Camera status:",
        (
            "  Discovery command: "
            + str(
                camera.get(
                    "command"
                )
                or "unknown"
            )
        ),
        (
            "  Command present: "
            + _yes_no(
                camera.get(
                    "command_present"
                )
            )
        ),
        (
            "  Discovery available: "
            + _yes_no(
                camera.get(
                    "available"
                )
            )
        ),
        (
            "  Discovery verified: "
            + _yes_no(
                camera.get(
                    "verified"
                )
            )
        ),
        (
            "  Discovery reason: "
            + str(
                camera.get(
                    "reason"
                )
                or "unknown"
            )
        ),
    ]

    last_probe = camera.get(
        "last_probe"
    )

    if not isinstance(
        last_probe,
        dict,
    ):
        lines.append(
            "  Last active camera probe: none"
        )

        return "\n".join(
            lines
        )

    width = int(
        last_probe.get(
            "image_width"
        )
        or 0
    )

    height = int(
        last_probe.get(
            "image_height"
        )
        or 0
    )

    dimensions = (
        f"{width}x{height}"
        if width > 0 and height > 0
        else "unknown"
    )

    lines.extend(
        [
            "  Last active camera probe:",
            (
                "    Backend: "
                + str(
                    last_probe.get(
                        "backend"
                    )
                    or "unknown"
                )
            ),
            (
                "    Available: "
                + _yes_no(
                    last_probe.get(
                        "available"
                    )
                )
            ),
            (
                "    Verified: "
                + _yes_no(
                    last_probe.get(
                        "verified"
                    )
                )
            ),
            (
                "    Reason: "
                + str(
                    last_probe.get(
                        "reason"
                    )
                    or "unknown"
                )
            ),
            (
                "    Image verified: "
                + _yes_no(
                    last_probe.get(
                        "image_verified"
                    )
                )
            ),
            (
                "    Format: "
                + str(
                    last_probe.get(
                        "image_format"
                    )
                    or "unknown"
                )
            ),
            (
                "    Dimensions: "
                + dimensions
            ),
            (
                "    Fresh: "
                + _yes_no(
                    last_probe.get(
                        "fresh"
                    )
                )
            ),
            (
                "    Platform match: "
                + _yes_no(
                    last_probe.get(
                        "current_platform_match"
                    )
                )
            ),
        ]
    )

    return "\n".join(
        lines
    )



def _runtime_introspection_reply(
    text: str,
    *,
    execution_context_active: bool = False,
) -> str | None:
    """Answer clear Mode-6 runtime-state questions without LLM speculation."""

    normalized = " ".join(
        str(text or "").casefold().strip().split()
    )

    terminal = normalized.rstrip(
        "?!. "
    )

    if not terminal:
        return None

    explicit_agent_question = (
        "agent" in terminal
        and any(
            phrase in terminal
            for phrase in (
                "how many",
                "running",
                "status",
                "purpose",
                "job",
                "doing",
                "what is name",
                "what is the name",
            )
        )
    )

    direct_activity_followups = {
        "is it doing something now or it will do in future",
        "is it doing something now or will it do something in future",
        "is it doing something now",
        "what it is doing",
        "what is it doing",
        "what are you doing now",
    }

    if (
        not explicit_agent_question
        and terminal
        not in direct_activity_followups
    ):
        return None

    context_line = (
        "A repository execution context is retained for follow-up, "
        "but no repository job is executing while Sophyane is "
        "waiting at this prompt."
        if execution_context_active
        else
        "No repository execution job is currently active."
    )

    return "\n".join(
        (
            "Runtime status:",
            "  Name: Sophyane",
            (
                "  Purpose: interactive Mode-6 conversation "
                "and guarded repository execution."
            ),
            "  Interactive sessions: 1",
            "  Background agents running: 0",
            "  Current state: idle, waiting for your input.",
            "  " + context_line,
            (
                "  Provider entries such as codex_cli, "
                "nifdu_browser, and local_gguf are available "
                "capabilities/fallbacks, not concurrently "
                "running agents."
            ),
        )
    )

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-human-chat"
    )

    parser.add_argument(
        "--status",
        action="store_true",
    )

    parser.add_argument(
        "--once",
        type=str,
        default=None,
    )

    args = parser.parse_args()

    if args.status:
        print(
            json.dumps(
                human_conversation_status(),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        return 0

    if args.once is not None:
        if _repository_execution_request(
            args.once
        ):
            print(
                _execute_repository_request(
                    args.once
                )
            )
        else:
            result = conversation_turn(
                args.once
            )

            print(
                result.reply
            )

        return 0

    print(
        "Sophyane human conversation mode."
    )

    print(
        "Talk naturally. Type /voice to speak, "
        "/see to use the camera, "
        "/voice-status or /camera-status for status, "
        "or /exit to leave."
    )

    active_execution_request: str | None = None

    while True:
        try:
            value = input(
                "\nYou: "
            )

        except (
            EOFError,
            KeyboardInterrupt,
        ):
            print()

            return 0

        text = value.strip()

        if text in {
            "/exit",
            "/quit",
            "exit",
            "quit",
        }:
            return 0

        if not text:
            continue

        runtime_reply = _runtime_introspection_reply(
            text,
            execution_context_active=(
                active_execution_request
                is not None
            ),
        )

        if runtime_reply is not None:
            print(
                "\nSophyane:",
                runtime_reply,
            )
            continue

        if text.strip() == "/camera-status":
            print(_camera_status_text())
            continue

        if text == "/voice-status":
            _print_voice_status()
            continue

        visual_artifact_path = None
        turn_metadata = None

        explicit_visual_request = bool(
            text == "/see"
            or text.startswith(
                "/see "
            )
        )

        automatic_perception = (
            None
            if explicit_visual_request
            else _automatic_perception_intent(
                text
            )
        )

        if (
            explicit_visual_request
            or automatic_perception
            == "camera"
        ):
            if explicit_visual_request:
                visual_question = (
                    text[
                        len("/see"):
                    ].strip()
                )

                if not visual_question:
                    visual_question = (
                        "Describe what you can see "
                        "in this camera image."
                    )

            else:
                # Preserve the user's natural request exactly.
                visual_question = text

            visual_input = (
                _camera_visual_input()
            )

            if visual_input is None:
                continue

            (
                visual_artifact_path,
                turn_metadata,
            ) = visual_input

            if (
                automatic_perception
                == "camera"
            ):
                turn_metadata = dict(
                    turn_metadata
                    or {}
                )

                turn_metadata[
                    "perception_trigger"
                ] = (
                    "automatic_visual_intent"
                )

            text = visual_question

        elif text == "/voice":
            voice_text = (
                _voice_input_text()
            )

            if voice_text is None:
                continue

            text = voice_text

        try:
            if visual_artifact_path:
                result = conversation_turn(
                    text,
                    visual_artifact_path=
                        visual_artifact_path,
                    metadata=
                        turn_metadata,
                )

                reply = result.reply

            elif active_execution_request is not None:
                execution_request = (
                    _continue_execution_request(
                        text,
                        active_request=
                            active_execution_request,
                    )
                )

                reply = _execute_repository_request(
                    execution_request
                )

                active_execution_request = (
                    execution_request
                )

            elif _repository_execution_request(
                text
            ):
                reply = _execute_repository_request(
                    text
                )

                active_execution_request = text

            else:
                result = conversation_turn(
                    text
                )

                reply = result.reply

            print(
                "\nSophyane:",
                reply,
            )

        except Exception as exc:
            print(
                "\nSophyane error:",
                type(exc).__name__
                + ": "
                + str(exc),
            )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
