from __future__ import annotations

from sophyane.mode6_rsi_handoff import (
    record_mode6_improvement_observation,
)

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
from sophyane.mode6_session import (
    Mode6ConversationSession,
)
from sophyane.tui_v2 import (
    _read_atomic_submission,
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

    natural_file_mutation = bool(
        re.search(
            r"\b(?:leave me a note|leave a note|write me a note|"
            r"write a note)\b",
            normalized,
        )
        or re.search(
            r"\bnote named\s+[\w.-]+\.(?:py|pyi|js|ts|tsx|jsx|json|"
            r"toml|yaml|yml|md|txt|html|css|sh|bash|lean)\b",
            normalized,
        )
    )

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

    web_product_context = bool(
        re.search(
            r"\b(?:saas|website|web\s+app|webapp|site|app)\b",
            normalized,
        )
        and re.search(
            r"(?:"
            r"https?://[^\s]+|"
            r"\bwww\.[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?|"
            r"\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
            r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
            r"(?:/[^\s]*)?"
            r")",
            normalized,
        )
    )

    return (
        executable
        or natural_file_mutation
    ) and (
        repository_context
        or web_product_context
    )




# SOPHYANE_GITHUB_IDENTITY_BOUNDARY_V1
def _local_workspace_for_github_identity(
    request: str,
) -> Path | None:
    """Resolve an existing checkout only after verifying its Git remote."""
    import subprocess

    text = str(request or "")

    matches = re.findall(
        r"(?<![\\w/])(?:https://github\\.com/)?"
        r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
        r"(?:\\.git)?(?![\\w/])",
        text,
    )

    identities = {
        match.removesuffix(".git").casefold()
        for match in matches
    }

    if len(identities) != 1:
        return None

    identity = next(iter(identities))
    owner, name = identity.split("/", 1)

    if owner in {".", ".."} or name in {".", ".."}:
        return None

    candidate = Path.home() / name

    if not candidate.is_dir():
        return None

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(candidate),
                "remote",
                "get-url",
                "origin",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    remote = result.stdout.strip().casefold()

    if remote.startswith("git@github.com:"):
        remote_identity = remote.split(":", 1)[1]
    elif remote.startswith("ssh://git@github.com/"):
        remote_identity = remote.split("github.com/", 1)[1]
    elif remote.startswith("https://github.com/"):
        remote_identity = remote.split("github.com/", 1)[1]
    else:
        return None

    remote_identity = (
        remote_identity.rstrip("/").removesuffix(".git")
    )

    if remote_identity != identity:
        return None

    return candidate.resolve()


def _requested_execution_workspace(
    request: str,
) -> Path | None:
    """Resolve an explicit workspace through the canonical TUI policy."""

    from sophyane.tui_v2 import ObservableTUI

    text = str(request or "").strip()

    if not text:
        return None

    # This boundary recognizes only explicit workspace authority.
    #
    # Keep the accepted forms deliberately narrow.  Once a path has been
    # recognized, canonicalize the request back to "Work in <path>" and let
    # ObservableTUI._workspace_for() remain authoritative for path handling.
    explicit_patterns = (
        r"\bwork\s+in\s+`?((?:~|/)[^\s`]+)",
        r"workspace\s+directory\s+`?((?:~|/)[^\s`]+)",
        r"(?:script|file)\s+`?((?:~|/)[^\s`]+)",
        r"\bthis\s+exact\s+directory\s*:\s*"
        r"`?((?:~|/)[^\s`]+)",
        r"\bexplicitly\s+supplied\s+repository\s+"
        r"`?((?:~|/)[^\s`]+)",
    )

    explicit_path = None

    for pattern in explicit_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match is not None:
            explicit_path = match.group(1).rstrip(
                ".,;:!?)]}"
            )
            break

    if not explicit_path:
        return _local_workspace_for_github_identity(text)

    resolver = object.__new__(ObservableTUI)
    resolver.active_workspace = None
    resolver.active_request = ""
    resolver.trace = False
    resolver.progress = lambda _message: None

    # Preserve the canonical TUI workspace policy rather than constructing
    # workspace authority directly from the extracted path.
    canonical_request = f"Work in {explicit_path}"

    return resolver._workspace_for(
        False,
        request=canonical_request,
    ).resolve()



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

    # An explicit no-edit instruction to execute an existing file
    # is a new execution contract, not permission to repeat an
    # unfinished creation operation.
    run_existing = re.search(
        r"^\s*(?:execute|run)\s+the\s+existing\s+file\b",
        followup,
        flags=re.IGNORECASE,
    )
    no_edit = re.search(
        r"\bdo\s+not\s+(?:write|create|modify|edit)\b",
        followup,
        flags=re.IGNORECASE,
    )

    if run_existing and no_edit:
        return followup

    return active + "\n" + followup


class _CompletedRepositoryExecution(str):
    """String reply carrying grounded completed-execution evidence."""


_mode6_failure_driven_controller = None


def _mode6_reusable_executable_capability_class(
    request,
) -> str | None:
    """
    Derive the bounded reusable-executable capability class for a later
    Mode-6 request.

    This is recognition only.  It grants no execution or mutation authority.
    The trusted store and promoted-capability executor remain authoritative.
    """

    import re

    text = str(request or "").strip()

    if not text:
        return None

    # Trusted reuse is an authority-bearing shortcut.  Require an explicit
    # reuse verb followed by explicit reusable-capability intent; an ordinary
    # "run foo.py" request must continue through the normal provider path.
    reuse_intent = re.search(
        r"\b(?:use|run|execute)\b"
        r".{0,120}?"
        r"\breusable\b",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if reuse_intent is None:
        return None

    # Development intent is not trusted reuse even if the request also uses
    # the word "reusable".
    if re.search(
        r"\b(?:create|implement|write|develop|build)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return None

    # Inspect complete Python references rather than searching directly for a
    # safe-looking basename. Otherwise "../foo.py" or "sub/foo.py" could be
    # silently reduced to "foo.py" and select unintended trusted authority.
    python_references = re.findall(
        r"[A-Za-z0-9_.\\/-]+\.py",
        text,
        flags=re.IGNORECASE,
    )

    # More than one Python reference is ambiguous. Do not guess which
    # trusted capability the user intended.
    if len(python_references) != 1:
        return None

    program = python_references[0]

    # The trusted capability class is restricted to one safe basename.
    if (
        "/" in program
        or "\\" in program
        or ".." in program
        or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*\.py",
            program,
            flags=re.IGNORECASE,
        )
        is None
    ):
        return None

    return f"executable.{program}"



def _execute_mode6_promoted_capability(
    candidate,
    request,
    *,
    workspace,
) -> bool:
    """
    Execute one already-trusted Mode-6 promoted executable.

    This boundary does not develop, promote, acquire a provider, or recurse
    through repository execution.  It only verifies that the exact promoted
    bytes are still present and executes the host-derived verification
    contract through the RSI verification sandbox.
    """

    import re
    import sys

    from sophyane.rsi import verification
    from sophyane.rsi.sandbox import SandboxUnavailable

    if not isinstance(candidate, dict):
        return False

    if candidate.get("status") != "TRUSTED_PROMOTED":
        return False

    capability_class = str(
        candidate.get("capability_class", "") or ""
    ).strip()

    prefix = "executable."

    if not capability_class.startswith(prefix):
        return False

    program = capability_class[len(prefix):].strip()

    if (
        not program
        or "/" in program
        or "\\" in program
        or program in {".", ".."}
        or not program.endswith(".py")
    ):
        return False

    files = candidate.get("files")

    if not isinstance(files, dict):
        return False

    # The trusted artifact is intentionally one-file bounded.
    if set(files) != {program}:
        return False

    promoted_text = files.get(program)

    if not isinstance(promoted_text, str):
        return False

    root = Path(workspace).expanduser().resolve()

    program_path = (root / program).resolve()

    try:
        program_path.relative_to(root)
    except ValueError:
        return False

    if not program_path.is_file():
        return False

    # Retry only the exact bytes that crossed trusted promotion.  A later
    # workspace modification must not inherit the old promotion decision.
    try:
        if program_path.read_text() != promoted_text:
            return False
    except (OSError, UnicodeError):
        return False

    text = str(request or "")

    input_match = re.search(
        r"`?([A-Za-z0-9_.-]+\.sphy)`?",
        text,
        flags=re.IGNORECASE,
    )

    expected_match = re.search(
        r"(?:matches?|compare(?:d)?(?:\s+against|\s+with)?|"
        r"verify.{0,80}?)\s+"
        r"`?([A-Za-z0-9_.-]+\.txt)`?",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if input_match is None or expected_match is None:
        return False

    input_name = input_match.group(1)
    expected_name = expected_match.group(1)

    input_path = (root / input_name).resolve()
    expected_path = (root / expected_name).resolve()

    try:
        input_path.relative_to(root)
        expected_path.relative_to(root)
    except ValueError:
        return False

    if (
        not input_path.is_file()
        or not expected_path.is_file()
    ):
        return False

    try:
        expected_bytes = expected_path.read_bytes()
    except OSError:
        return False

    try:
        result = verification.run_command(
            (
                sys.executable,
                program,
                input_name,
            ),
            root,
            timeout=60,
        )
    except SandboxUnavailable:
        # Production remains fail-closed when the RSI execution sandbox is
        # unavailable.  Promotion alone is never retry success.
        return False

    if result.exit_code != 0:
        return False

    try:
        actual_bytes = result.output.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        return False

    return actual_bytes == expected_bytes



def _mode6_capability_development_controller(
    *,
    workspace: Path | None = None,
):
    """Return the shared failure-driven controller for this Mode-6 process."""

    global _mode6_failure_driven_controller

    resolved_workspace = (
        workspace.resolve()
        if workspace is not None
        else None
    )

    if _mode6_failure_driven_controller is None:
        from sophyane.failure_driven_capability import (
            CapabilityDevelopmentController,
        )

        # Host-owned bridge between independent verification and the
        # distinct promotion graph node.  Worker/provider fields never
        # populate this receipt.
        verified_candidates = {}

        # Host-owned provider provenance from the CodingRouter boundary.
        # candidate["provider"] is descriptive/cross-check metadata only;
        # it cannot independently establish promotion authority.
        worker_candidate_providers = {}

        # Host-owned promotion provenance.  The generic reusable store is
        # capability-class keyed, but Mode-6 promotion authority is scoped
        # to the workspace in which the trusted broker accepted the bytes.
        #
        # Candidate/provider fields cannot populate or modify this mapping.
        trusted_capability_workspaces = {}

        def mode6_worker(role, context):
            # Only implementation requires a coding proposal.  The remaining
            # graph roles are evidence/planning stages and do not gain a
            # second provider or mutation boundary here.
            if role != "implementation":
                return {
                    "role": role,
                    "proposal": "mode6-host-stage",
                }

            bound_workspace = getattr(
                _mode6_failure_driven_controller,
                "mode6_workspace",
                None,
            )

            if bound_workspace is None:
                return {
                    "status": "DEFERRED_NO_WORKSPACE",
                    "provider": "",
                    "files": {},
                    "failovers": (),
                }

            from sophyane.rsi.authority import Operation
            from sophyane.rsi.availability import AvailabilityStore
            from sophyane.rsi.coding_provider import CodingRouter

            request = str(context.get("request", ""))
            capability_class = str(
                context.get("capability_class", "")
            )

            prompt = (
                "Propose implementation bytes only for this missing "
                "reusable capability. Do not execute commands, mutate "
                "the workspace, approve, verify, or promote anything.\n\n"
                f"Capability class: {capability_class}\n"
                f"Original request:\n{request}"
            )

            router = CodingRouter(
                AvailabilityStore(),
                operation=Operation.ORDINARY_WORKSPACE_MUTATION,
            )

            result = router.request(
                prompt,
                bound_workspace,
            )

            candidate = {
                "status": result.status,
                "provider": result.provider,
                "files": dict(result.files),
                "failovers": tuple(result.failovers),
            }

            provider = str(result.provider or "").strip()

            if candidate["status"] == "SUCCESS" and provider:
                worker_candidate_providers[id(candidate)] = {
                    "candidate": candidate,
                    "provider": provider,
                    "workspace": bound_workspace,
                }

            return candidate

        def mode6_verifier(candidate, request):
            """
            Independently verify a bounded Mode-6 implementation proposal.

            The provider supplies candidate bytes only.  Mutation scope,
            verification argv, expected output, and the execution location
            are selected by the host from the explicit request/workspace
            contract.
            """

            import re
            import sys
            import tempfile

            from sophyane.rsi.candidate_workspace import (
                CandidateWorkspace,
            )
            from sophyane.rsi import verification

            bound_workspace = getattr(
                _mode6_failure_driven_controller,
                "mode6_workspace",
                None,
            )

            if bound_workspace is None:
                return False

            if not isinstance(candidate, dict):
                return False

            if candidate.get("status") != "SUCCESS":
                return False

            files = candidate.get("files")

            if not isinstance(files, dict) or not files:
                return False

            provider_receipt = worker_candidate_providers.get(
                id(candidate)
            )

            if not isinstance(provider_receipt, dict):
                return False

            provider = str(
                provider_receipt.get("provider", "")
            ).strip()

            if (
                provider_receipt.get("candidate") is not candidate
                or provider_receipt.get("workspace")
                != bound_workspace
                or not provider
                or str(candidate.get("provider", "")).strip()
                != provider
            ):
                return False

            text = str(request or "")

            # Host-owned scope: for the currently established Mode-6
            # contract, the request itself must explicitly name the Python
            # program to create.
            program_match = re.search(
                r"\b(?:create|write|implement)\b"
                r".{0,160}?"
                r"\b(?:python\s+program\s+)?"
                r"`?([A-Za-z0-9_.-]+\.py)`?",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )

            if program_match is None:
                return False

            program = program_match.group(1)

            # Provider output cannot expand its own mutation authority.
            if set(files) != {program}:
                return False

            # The verification input and oracle must already exist in the
            # primary workspace and must be explicitly named by the request.
            input_match = re.search(
                r"`?([A-Za-z0-9_.-]+\.sphy)`?",
                text,
                flags=re.IGNORECASE,
            )

            expected_match = re.search(
                r"(?:matches?|compare(?:d)?(?:\s+against|\s+with)?|"
                r"verify.{0,80}?)\s+"
                r"`?([A-Za-z0-9_.-]+\.txt)`?",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )

            if input_match is None or expected_match is None:
                return False

            input_name = input_match.group(1)
            expected_name = expected_match.group(1)

            input_path = bound_workspace / input_name
            expected_path = bound_workspace / expected_name

            if (
                not input_path.is_file()
                or not expected_path.is_file()
            ):
                return False

            expected_bytes = expected_path.read_bytes()

            # Candidate root is host-created outside the primary repository.
            # preview() applies only the already host-authorized path and
            # performs the candidate path/link/trust-root checks.
            with tempfile.TemporaryDirectory(
                prefix="sophyane-mode6-candidates-",
            ) as candidate_parent:
                isolated = CandidateWorkspace(
                    bound_workspace,
                    Path(candidate_parent),
                ).create()

                try:
                    isolated.preview(
                        files,
                        {program},
                    )

                    result = verification.run_command(
                        (
                            sys.executable,
                            program,
                            input_name,
                        ),
                        isolated.path,
                        timeout=60,
                    )

                    if result.exit_code != 0:
                        return False

                    try:
                        actual_bytes = result.output.encode("utf-8")
                    except (AttributeError, UnicodeEncodeError):
                        return False

                    if actual_bytes != expected_bytes:
                        return False

                    # Verification remains non-mutating.  Preserve only a
                    # host-owned receipt for the exact isolated bytes that
                    # passed the host-selected verification command/oracle.
                    verified_fingerprint = isolated.diff().fingerprint

                    consumed_provider_receipt = (
                        worker_candidate_providers.pop(
                            id(candidate),
                            None,
                        )
                    )

                    if (
                        consumed_provider_receipt
                        is not provider_receipt
                    ):
                        return False

                    verified_candidates[id(candidate)] = {
                        "candidate": candidate,
                        "fingerprint": verified_fingerprint,
                        "program": program,
                        "provider": provider,
                        "request": text,
                        "workspace": bound_workspace,
                    }

                    return True
                finally:
                    isolated.close()

        def mode6_promoter(
            candidate,
            request,
            capability_class,
        ):
            import tempfile

            from sophyane.rsi.candidate_workspace import (
                CandidateWorkspace,
            )
            from sophyane.rsi.pre_verifier import (
                VerificationEvidence,
            )

            receipt = verified_candidates.pop(
                id(candidate),
                None,
            )

            if receipt is None:
                return None

            # Identity prevents a different candidate object from consuming
            # another proposal's successful verification receipt.
            if receipt.get("candidate") is not candidate:
                return None

            bound_workspace = getattr(
                _mode6_failure_driven_controller,
                "mode6_workspace",
                None,
            )

            if bound_workspace is None:
                return None

            if receipt.get("workspace") != bound_workspace:
                return None

            if receipt.get("request") != str(request or ""):
                return None

            if not isinstance(candidate, dict):
                return None

            if candidate.get("status") != "SUCCESS":
                return None

            files = candidate.get("files")

            if not isinstance(files, dict) or not files:
                return None

            program = str(receipt.get("program", "") or "")
            provider = str(receipt.get("provider", "") or "")
            verified_fingerprint = str(
                receipt.get("fingerprint", "") or ""
            )

            if (
                not program
                or not provider
                or not verified_fingerprint
            ):
                return None

            # Host-owned mutation scope comes from verification, never from
            # candidate['allowed_paths'] or other worker/provider claims.
            if set(files) != {program}:
                return None

            with tempfile.TemporaryDirectory(
                prefix="sophyane-mode6-promotion-",
            ) as candidate_parent:
                isolated = CandidateWorkspace(
                    bound_workspace,
                    Path(candidate_parent),
                ).create()

                try:
                    isolated.preview(
                        files,
                        {program},
                    )

                    current_fingerprint = (
                        isolated.diff().fingerprint
                    )

                    # Close the verifier -> promoter TOCTOU gap: only bytes
                    # identical to the independently verified snapshot may
                    # reach the trusted broker.
                    if (
                        current_fingerprint
                        != verified_fingerprint
                    ):
                        return None

                    evidence = VerificationEvidence(
                        True,
                        verified_fingerprint,
                    )

                    isolated.promote(
                        provider,
                        evidence,
                        {program},
                    )

                    isolated.accept_promotion()

                    # Promotion authority is host-owned and workspace-scoped.
                    # Record it only after the trusted broker transaction has
                    # succeeded and this CandidateWorkspace accepted it.
                    trusted_capability_workspaces[
                        capability_class
                    ] = bound_workspace

                    # The generic controller stores this returned artifact.
                    # Keep it bounded to the exact trusted promoted bytes and
                    # omit worker self-approval/promotion claims.
                    return {
                        "status": "TRUSTED_PROMOTED",
                        "provider": provider,
                        "capability_class": capability_class,
                        "files": {
                            program: files[program],
                        },
                        "fingerprint": verified_fingerprint,
                    }
                finally:
                    isolated.close()

        _mode6_failure_driven_controller = (
            CapabilityDevelopmentController(
                worker=mode6_worker,
                verifier=mode6_verifier,
                promoter=mode6_promoter,
            )
        )

        _mode6_failure_driven_controller.mode6_trusted_workspaces = (
            trusted_capability_workspaces
        )

    _mode6_failure_driven_controller.mode6_workspace = (
        resolved_workspace
    )

    return _mode6_failure_driven_controller


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
    from sophyane.rsi.authority import Operation

    request = str(text or "").strip()

    if not request:
        raise ValueError(
            "repository execution request must be non-empty"
        )

    # MODE6_LLM_FIRST_AUTHORITY_V1
    #
    # The genuine user turn has already crossed the selected intelligence
    # boundary before an actionable mission reaches this function.
    #
    # Reuse Sophyane's existing verified execution capabilities before
    # acquiring another provider resource. This grants no new authority:
    # the unified kernel retains its existing capability policy, workspace
    # boundary, execution, verification, and evidence semantics.
    from sophyane.capability_executors import (
        execute_deterministic_capability,
    )

    deterministic_result = execute_deterministic_capability(
        request,
        workspace=workspace,
    )

    if deterministic_result is not None:
        if deterministic_result.ok:
            return _CompletedRepositoryExecution(
                "Verified existing capability completed the request.\n"
                f"Capability: {deterministic_result.capability_id}\n"
                f"{deterministic_result.text}"
            )

        # The deterministic capability claimed and attempted this request.
        # Do not fall through into another executor: that could repeat a
        # side-effectful operation.  This is deliberately not marked as a
        # completed mission, so the conversation may retain it for an
        # explicit user-directed continuation.
        return (
            "Existing deterministic capability attempted the request but "
            "verification did not succeed.\n"
            f"Capability: {deterministic_result.capability_id}\n"
            f"{deterministic_result.text}"
        )

    # No deterministic capability claimed the mission.

    # MODE6_TRUSTED_PROMOTED_REUSE_V1
    # This reuse path runs before provider/adaptive workspace setup.
    # Resolve the already-authorized function workspace locally.
    reuse_workspace = (
        workspace.resolve()
        if workspace is not None
        else None
    )

    #
    # This function is downstream of the Mode-6 intelligence boundary.
    # Before spending another repository provider request, recognize only the
    # bounded reusable-executable request form and ask the shared trusted
    # capability store whether that exact class can satisfy this request.
    #
    # Store presence alone is never completion.  execute_or_reuse() must run
    # the trusted promoted artifact and independently verify this request.
    reuse_capability_class = (
        _mode6_reusable_executable_capability_class(request)
    )

    if reuse_capability_class is not None:
        reuse_controller = (
            _mode6_capability_development_controller(
                workspace=reuse_workspace,
            )
        )

        trusted_workspaces = getattr(
            reuse_controller,
            "mode6_trusted_workspaces",
            {},
        )

        trusted_workspace = trusted_workspaces.get(
            reuse_capability_class
        )

        reuse_result = None

        if (
            reuse_workspace is not None
            and trusted_workspace == reuse_workspace
        ):
            reuse_result = reuse_controller.execute_or_reuse(
                request=request,
                capability_class=reuse_capability_class,
                execute=(
                    lambda candidate, reuse_request:
                    _execute_mode6_promoted_capability(
                        candidate,
                        reuse_request,
                        workspace=reuse_workspace,
                    )
                ),
            )

        if (
            reuse_result is not None
            and getattr(reuse_result, "reused", False) is True
        ):
            if (
                getattr(
                    reuse_result,
                    "original_outcome_verified",
                    False,
                )
                is True
            ):
                return _CompletedRepositoryExecution(
                    "Verified trusted promoted capability completed "
                    "the request.\n"
                    f"Capability: {reuse_capability_class}"
                )

            # A trusted promoted capability was selected and attempted this
            # request, but independent outcome verification failed.  Do not
            # fall through to another executor: repeating a side-effectful
            # operation could duplicate effects.  This deliberately remains
            # non-completed so an explicit continuation can decide what to do.
            return (
                "Trusted promoted capability attempted the request but "
                "verification did not succeed.\n"
                f"Capability: {reuse_capability_class}"
            )

    # No verified trusted capability completed the mission.
    # Continue through the existing provider/adaptive execution path.

    # The first semantic turn uses the provider API's non-mutating safe
    # authority. Resolve repository operation only after that response.
    operation = Operation.READ_ONLY_OPERATION

    from sophyane.main import load_runtime_config

    provider = create_provider(
        load_runtime_config()
        if os.environ.get("SOPHYANE_SESSION_MODE", "").strip().lower() == "human_conversation"
        else load_config()
    )

    # MODE6_PROVIDER_ATTRIBUTION_V1
    # Preserve the successful provider selected for every repository-execution
    # provider call without exposing availability/authentication diagnostics.
    from sophyane.providers.human_conversation import HumanConversationProvider

    if isinstance(provider, HumanConversationProvider):
        provider.execution_provider_evidence = []
        provider.execution_provider_route_evidence = []

    system_prompt = (
        "You are Sophyane's repository execution provider. "
        "Follow the supplied execution contract exactly. "
        "Return executable JSON actions only when requested. "
        "Do not claim an action succeeded before the runtime verifies it."
    )

    def ask(prompt: str) -> str:
        if isinstance(provider, HumanConversationProvider):
            response = provider.generate(
                str(prompt),
                system_prompt,
                operation=operation,
            )
            selected_provider = str(
                getattr(
                    provider,
                    "last_provider",
                    "",
                )
                or ""
            ).strip()
            if selected_provider:
                provider.execution_provider_evidence.append(
                    selected_provider
                )
            provider_route = tuple(
                getattr(
                    provider,
                    "last_provider_route",
                    (),
                )
                or ()
            )
            if provider_route:
                provider.execution_provider_route_evidence.append(
                    provider_route
                )
            return response
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

    _fresh_present = "SOPHYANE_CODEX_FRESH" in os.environ
    _fresh_value = os.environ.get("SOPHYANE_CODEX_FRESH")
    os.environ["SOPHYANE_CODEX_FRESH"] = "1"
    try:
        initial_text = ask(
            initial_prompt
        )
    finally:
        if _fresh_present:
            os.environ["SOPHYANE_CODEX_FRESH"] = _fresh_value
        else:
            os.environ.pop("SOPHYANE_CODEX_FRESH", None)

    # Only now resolve the guarded execution authority from the original
    # request; the same provider instance is reused for follow-up turns.
    operation = _repository_operation_for_request(request)

    # A local-GGUF first response was obtained under read-only authority.
    # It is never promoted to source-mutation authority; obtain a fresh
    # response after operation classification through the protected cascade.
    if (
        operation is Operation.SOPHYANE_SOURCE_MUTATION
        and isinstance(initial_text, str)
        and getattr(initial_text, "provider_id", "") == "local_gguf"
    ):
        initial_text = ask(
            execution_prefix_for_repair(request)
            + "\n\nThe protected source mutation operation is now authorized only for Codex or NIFDU. Return one executable action."
        )

    resolved_workspace = (
        workspace.resolve()
        if workspace is not None
        else None
    )

    result = run_adaptive_loop(
        initial_text=initial_text,
        original_request=request,
        ask=ask,
        workspace=resolved_workspace,
        max_steps=16,
        operation=operation,
    )

    # MODE6_FAILURE_DRIVEN_HANDOFF_V1
    #
    # Classification authority belongs to adaptive execution.  This
    # boundary must not infer a capability gap from arbitrary failures.
    # It only consumes an already-authoritative missing-capability result.
    from sophyane.failure_driven_capability import (
        FailureClassification,
    )

    failure_classification = getattr(
        result,
        "failure_classification",
        None,
    )
    capability_class = str(
        getattr(
            result,
            "capability_class",
            "",
        )
        or ""
    ).strip()

    if (
        failure_classification
        is FailureClassification.MISSING_REUSABLE_CAPABILITY
        and capability_class
    ):
        development_result = (
            _mode6_capability_development_controller(
                workspace=resolved_workspace,
            ).handle_failure(
                request=request,
                failure=result,
                classification=failure_classification,
                capability_class=capability_class,
                execute_original=(
                    lambda candidate, original_request:
                    _execute_mode6_promoted_capability(
                        candidate,
                        original_request,
                        workspace=resolved_workspace,
                    )
                ),
            )
        )

        # Promotion is not completion.  Only the controller's independently
        # verified original-request retry may convert this first request into
        # a completed repository execution.
        if (
            getattr(
                development_result,
                "retry_original_request",
                False,
            )
            is True
        ):
            return _CompletedRepositoryExecution(
                str(request)
            )

    # MODE6_PROVIDER_EVIDENCE_OUTPUT_V1
    # Surface only successful provider routing. Availability/authentication
    # diagnostics remain internal to the provider cascade.
    if isinstance(provider, HumanConversationProvider):
        provider_evidence = tuple(
            provider.execution_provider_evidence
        )
        if provider_evidence:
            result = (
                str(result)
                + "\n\nProvider evidence: "
                + " -> ".join(provider_evidence)
            )

        provider_routes = tuple(
            getattr(
                provider,
                "execution_provider_route_evidence",
                (),
            )
            or ()
        )
        if provider_routes:
            route_lines = [
                "Provider route "
                + str(index)
                + ": "
                + " -> ".join(route)
                for index, route in enumerate(
                    provider_routes,
                    start=1,
                )
            ]
            result = (
                str(result)
                + "\n\n"
                + "\n".join(route_lines)
            )

    return result

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



def _handoff_turn_improvement(
    result,
) -> dict[str, object]:
    """Record optional Mode-6 improvement evidence without executing RSI."""

    observation = getattr(
        result,
        "improvement_observation",
        None,
    )

    if observation is None:
        return {
            "ok": True,
            "recorded": False,
            "reason": "no_observation",
        }

    return record_mode6_improvement_observation(
        observation
    )


def _mode6_runtime_state(
    *,
    execution_context_active: bool = False,
) -> dict[str, object]:
    """Return deterministic current Mode-6 runtime facts."""

    return {
        "interactive_sessions": 1,
        "background_agents_running": 0,
        "current_state": "idle_waiting_for_input",
        "repository_execution": {
            "context_retained": bool(
                execution_context_active
            ),
            "job_active": False,
        },
        "provider_entries_are_capabilities": True,
    }

from sophyane.rsi.supervisor import runtime_session as _rsi_runtime_session

@_rsi_runtime_session
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
            result = _execute_repository_request(
                args.once
            )

            print(
                result
            )

            if not isinstance(
                result,
                _CompletedRepositoryExecution,
            ):
                return 1
        else:
            result = conversation_turn(
                args.once,
                trusted_runtime=
                    _mode6_runtime_state(),
            )

            _handoff_turn_improvement(
                result
            )

            print(
                result.reply
            )

        return 0

    print(
        "Sophyane"
    )

    print(
        "────────"
    )

    print(
        "Hello. I'm ready."
    )

    print(
        "\nWhat would you like us to accomplish?\n"
    )

    active_execution_request: str | None = None
    conversation_session = Mode6ConversationSession()

    while True:
        try:
            value = _read_atomic_submission(
                "\n> "
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
                    recent_turns=
                        conversation_session.recent_turns(),
                    trusted_runtime=
                        _mode6_runtime_state(
                            execution_context_active=(
                                active_execution_request
                                is not None
                            ),
                        ),
                )

                _handoff_turn_improvement(
                    result
                )

                reply = result.reply

                conversation_session.append_user(
                    text
                )
                conversation_session.append_assistant(
                    reply
                )

            elif active_execution_request is not None:
                execution_request = (
                    _continue_execution_request(
                        text,
                        active_request=
                            active_execution_request,
                    )
                )

                reply = _execute_repository_request(
                    execution_request,
                    workspace=_requested_execution_workspace(
                        execution_request
                    ),
                )

                active_execution_request = (
                    None
                    if isinstance(
                        reply,
                        _CompletedRepositoryExecution,
                    )
                    else execution_request
                )

            else:
                result = conversation_turn(
                    text,
                    recent_turns=
                        conversation_session.recent_turns(),
                    trusted_runtime=
                        _mode6_runtime_state(
                            execution_context_active=(
                                active_execution_request
                                is not None
                            ),
                        ),
                )

                _handoff_turn_improvement(
                    result
                )

                disposition = getattr(
                    result,
                    "semantic_disposition",
                    None,
                )

                if disposition == "actionable_mission":
                    # Routing intent is untrusted. The executor still
                    # resolves Operation and enforces existing guarded
                    # authority, admission, sandbox, and verification.
                    reply = _execute_repository_request(
                        text,
                        workspace=_requested_execution_workspace(
                            text
                        ),
                    )
                    active_execution_request = (
                        None
                        if isinstance(
                            reply,
                            _CompletedRepositoryExecution,
                        )
                        else text
                    )
                else:
                    # Missing or malformed intent remains conversational.
                    reply = result.reply

                conversation_session.append_user(
                    text
                )
                conversation_session.append_assistant(
                    reply
                )

            print(
                "\nSophyane:",
                reply,
            )

        except Exception as exc:
            # SOPHYANE_TASK001_TEMP_TRACEBACK_PROBE
            import traceback
            with (Path.home() / ".cache" / "sophyane-task001-traceback.log").open(
                "a", encoding="utf-8"
            ) as trace_file:
                traceback.print_exc(file=trace_file)
            print(
                "\nSophyane error:",
                type(exc).__name__
                + ": "
                + str(exc),
            )



def _repository_operation_for_request(request: str):
    """Map repository intent to the narrowest authority operation."""
    from sophyane.request_classification import (
        RepositoryCapability,
        classify_repository_capability,
    )
    from sophyane.rsi.authority import Operation

    text = " ".join(str(request or "").casefold().split())
    capability = classify_repository_capability(request)

    if capability is RepositoryCapability.READ_ONLY:
        return Operation.READ_ONLY_OPERATION

    if (
        "sophyane" in text
        or "rsi" in text
        or "source in this repository" in text
    ):
        return Operation.SOPHYANE_SOURCE_MUTATION

    if any(term in text for term in ("make file", "create a file", "leave me a note", "leave a note", "write a note", "note named")):
        return Operation.ORDINARY_WORKSPACE_MUTATION

    if capability is RepositoryCapability.MUTATION:
        if "src/sophyane" in text or "source" in text:
            return Operation.SOPHYANE_SOURCE_MUTATION
        return Operation.ORDINARY_WORKSPACE_MUTATION

    return Operation.READ_ONLY_OPERATION


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
