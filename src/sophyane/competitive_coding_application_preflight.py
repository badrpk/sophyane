"""Read-only preflight for an approved competitive application."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sophyane.competitive_coding_approval import verify_competitive_approval
from sophyane.competitive_coding_phase2 import CompetitiveEvaluationResult
from sophyane.competitive_coding_ranking import rank_competitive_evaluation
from sophyane.evolution.target_evaluator import _patch_paths

__all__ = [
    "CompetitiveApplicationPreflightError",
    "CompetitiveApplicationPlan",
    "prepare_competitive_application",
]

_PAYLOAD_FIELDS = {
    "objective",
    "repository",
    "target_name",
    "source_head",
    "baseline_patch_sha256",
    "candidate_id",
    "candidate_patch_sha256",
    "trusted_evidence_digest",
}
_UNSUPPORTED_MARKERS = (
    b"new file mode ",
    b"deleted file mode ",
    b"old mode ",
    b"new mode ",
    b"rename from ",
    b"rename to ",
    b"copy from ",
    b"copy to ",
    b"similarity index ",
    b"dissimilarity index ",
    b"GIT binary patch",
    b"Binary files ",
    b"--- /dev/null",
    b"+++ /dev/null",
)


class CompetitiveApplicationPreflightError(RuntimeError):
    """An approved competitive patch is not safe and ready to apply."""


@dataclass(frozen=True)
class CompetitiveApplicationPlan:
    request_id: str
    approval_digest: str
    approval_payload: str
    repository: str
    source_head: str
    baseline_patch_sha256: str
    candidate_id: str
    candidate_patch: str
    candidate_patch_sha256: str
    changed_paths: tuple[str, ...]


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise CompetitiveApplicationPreflightError("Git inspection is unavailable") from exc


def _required_git(repository: Path, *arguments: str) -> bytes:
    result = _git(repository, *arguments)
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise CompetitiveApplicationPreflightError(
            "Git inspection failed" + (f": {message}" if message else "")
        )
    return result.stdout


def _files(repository: Path) -> tuple[tuple[str, bytes], ...]:
    records: list[tuple[str, bytes]] = []
    try:
        for root, directories, filenames in os.walk(repository, followlinks=False):
            root_path = Path(root)
            directories[:] = sorted(name for name in directories if name != ".git")
            for name in sorted(filenames):
                path = root_path / name
                mode = path.lstat().st_mode
                if stat.S_ISREG(mode):
                    records.append((path.relative_to(repository).as_posix(), path.read_bytes()))
    except OSError as exc:
        raise CompetitiveApplicationPreflightError("repository snapshot failed") from exc
    return tuple(sorted(records))


def _snapshot(repository: Path) -> tuple[str, bytes, tuple[tuple[str, bytes], ...]]:
    head = _required_git(repository, "rev-parse", "HEAD")
    try:
        decoded_head = head.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise CompetitiveApplicationPreflightError("repository HEAD is malformed") from exc
    status = _required_git(repository, "status", "--porcelain=v1", "-z")
    return decoded_head, status, _files(repository)


def _payload(value: object) -> dict[str, str]:
    if not isinstance(value, str) or not value:
        raise CompetitiveApplicationPreflightError("approval payload is invalid")
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CompetitiveApplicationPreflightError("approval payload is malformed") from exc
    if not isinstance(parsed, dict) or set(parsed) != _PAYLOAD_FIELDS:
        raise CompetitiveApplicationPreflightError("approval payload keys are invalid")
    if any(not isinstance(item, str) or not item for item in parsed.values()):
        raise CompetitiveApplicationPreflightError("approval payload bindings are invalid")
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if canonical != value:
        raise CompetitiveApplicationPreflightError("approval payload is not canonical")
    return parsed


def _validated_paths(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise CompetitiveApplicationPreflightError("candidate changed paths are invalid")
    normalized: list[str] = []
    for path in value:
        if not isinstance(path, str) or not path or "\\" in path:
            raise CompetitiveApplicationPreflightError("candidate changed path is invalid")
        pure = PurePosixPath(path)
        components = path.split("/")
        if (
            pure.is_absolute()
            or path in {".", ".."}
            or any(component in {"", ".", ".."} for component in components)
            or pure.as_posix() != path
        ):
            raise CompetitiveApplicationPreflightError("candidate changed path is not normalized")
        normalized.append(path)
    if len(normalized) != len(set(normalized)):
        raise CompetitiveApplicationPreflightError("candidate changed paths contain duplicates")
    return tuple(normalized)


def _textual_profile(patch: bytes) -> None:
    if b"/dev/null" in patch:
        raise CompetitiveApplicationPreflightError("patch uses /dev/null")
    for line in patch.splitlines():
        if any(line.startswith(marker) for marker in _UNSUPPORTED_MARKERS):
            raise CompetitiveApplicationPreflightError("patch uses an unsupported application profile")


def _tracked_regular_files(repository: Path, paths: tuple[str, ...]) -> None:
    for relative in paths:
        output = _required_git(repository, "ls-files", "--stage", "-z", "--", relative)
        records = [record for record in output.split(b"\0") if record]
        if len(records) != 1:
            raise CompetitiveApplicationPreflightError("affected path is not exactly one tracked file")
        metadata, separator, recorded = records[0].partition(b"\t")
        fields = metadata.split()
        try:
            recorded_path = recorded.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise CompetitiveApplicationPreflightError("tracked path is not strict UTF-8") from exc
        if not separator or len(fields) != 3 or fields[0] not in {b"100644", b"100755"}:
            raise CompetitiveApplicationPreflightError("affected path has an unsupported index entry")
        if fields[2] != b"0" or recorded_path != relative:
            raise CompetitiveApplicationPreflightError("affected path index binding is invalid")
        target = repository / relative
        try:
            mode = target.lstat().st_mode
        except OSError as exc:
            raise CompetitiveApplicationPreflightError("affected path is missing") from exc
        if not stat.S_ISREG(mode) or target.is_symlink():
            raise CompetitiveApplicationPreflightError("affected path is not a regular file")


def _prepare(
    evaluation: CompetitiveEvaluationResult,
    request_id: str,
    repository: Path,
    initial_head: str,
) -> CompetitiveApplicationPlan:
    try:
        verification = verify_competitive_approval(evaluation, request_id)
    except Exception as exc:
        raise CompetitiveApplicationPreflightError(f"approval verification failed: {exc}") from exc
    if (
        verification.approved is not True
        or verification.status != "approved"
        or verification.request_id != request_id
    ):
        raise CompetitiveApplicationPreflightError("approval is not exactly approved")
    try:
        ranking = rank_competitive_evaluation(evaluation)
    except Exception as exc:
        raise CompetitiveApplicationPreflightError(f"ranking validation failed: {exc}") from exc
    if ranking.status != "approval_required" or ranking.winner is None:
        raise CompetitiveApplicationPreflightError("ranking has no unique application winner")
    if (
        ranking.approval_payload != verification.approval_payload
        or ranking.approval_digest != verification.approval_digest
    ):
        raise CompetitiveApplicationPreflightError("approval and ranking bindings differ")
    payload = _payload(ranking.approval_payload)
    winner = ranking.winner
    if any(payload[key] != value for key, value in {
        "candidate_id": winner.candidate_id,
        "candidate_patch_sha256": winner.patch_sha256,
        "source_head": winner.source_head,
    }.items()):
        raise CompetitiveApplicationPreflightError("winner does not match canonical approval payload")
    if payload["repository"] != str(repository) or initial_head != payload["source_head"]:
        raise CompetitiveApplicationPreflightError("approved repository or source HEAD changed")
    if not isinstance(winner.patch, str) or not winner.patch:
        raise CompetitiveApplicationPreflightError("winner patch is empty or invalid")
    try:
        patch_bytes = winner.patch.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CompetitiveApplicationPreflightError("winner patch is not strict UTF-8") from exc
    if hashlib.sha256(patch_bytes).hexdigest() != winner.patch_sha256:
        raise CompetitiveApplicationPreflightError("winner patch digest mismatch")
    matches = [item for item in evaluation.candidates if item.candidate_id == winner.candidate_id]
    if len(matches) != 1:
        raise CompetitiveApplicationPreflightError("winner candidate is not unique in evaluation")
    selected = matches[0]
    if (
        selected.patch != winner.patch
        or selected.patch_sha256 != winner.patch_sha256
        or selected.source_head != winner.source_head
    ):
        raise CompetitiveApplicationPreflightError("evaluation candidate differs from ranked winner")
    changed_paths = _validated_paths(selected.changed_paths)
    _textual_profile(patch_bytes)

    descriptor = -1
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix="sophyane-preflight-", suffix=".patch")
        temporary_path = Path(temporary)
        try:
            temporary_path.resolve().relative_to(repository)
        except ValueError:
            pass
        else:
            raise CompetitiveApplicationPreflightError("temporary patch is inside repository")
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(patch_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            parsed_paths = _patch_paths(repository, temporary_path)
        except Exception as exc:
            raise CompetitiveApplicationPreflightError(f"patch path parsing failed: {exc}") from exc
        parsed = _validated_paths(parsed_paths)
        if set(parsed) != set(changed_paths) or len(parsed) != len(changed_paths):
            raise CompetitiveApplicationPreflightError("patch paths differ from candidate changed paths")
        _tracked_regular_files(repository, changed_paths)
        applicable = _git(repository, "apply", "--check", "--", str(temporary_path))
        if applicable.returncode:
            message = applicable.stderr.decode("utf-8", errors="replace").strip()
            raise CompetitiveApplicationPreflightError(
                "patch is not applicable" + (f": {message}" if message else "")
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    return CompetitiveApplicationPlan(
        request_id=request_id,
        approval_digest=ranking.approval_digest,
        approval_payload=ranking.approval_payload,
        repository=payload["repository"],
        source_head=payload["source_head"],
        baseline_patch_sha256=payload["baseline_patch_sha256"],
        candidate_id=winner.candidate_id,
        candidate_patch=winner.patch,
        candidate_patch_sha256=winner.patch_sha256,
        changed_paths=changed_paths,
    )


def prepare_competitive_application(
    evaluation: CompetitiveEvaluationResult,
    request_id: str,
) -> CompetitiveApplicationPlan:
    try:
        repository = Path(evaluation.repository).expanduser().resolve()
    except Exception as exc:
        raise CompetitiveApplicationPreflightError("evaluation repository is invalid") from exc
    initial = _snapshot(repository)
    try:
        return _prepare(evaluation, request_id, repository, initial[0])
    except CompetitiveApplicationPreflightError:
        raise
    except Exception as exc:
        raise CompetitiveApplicationPreflightError(f"application preflight failed: {exc}") from exc
    finally:
        final = _snapshot(repository)
        if final != initial:
            raise CompetitiveApplicationPreflightError("repository changed during application preflight")
