"""Durable preparation journal for competitive application."""
from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath

from sophyane.competitive_coding_application_preflight import (
    CompetitiveApplicationPlan,
    prepare_competitive_application,
)
from sophyane.competitive_coding_phase2 import CompetitiveEvaluationResult

__all__ = [
    "CompetitiveApplicationTransactionError",
    "CompetitiveApplicationFileSnapshot",
    "CompetitiveApplicationTransaction",
    "prepare_competitive_application_transaction",
    "get_competitive_application_transaction",
]

_SCHEMA_VERSION = 1
_LEDGER_NAME = "transactions.json"
_LEDGER_LOCK_NAME = "transactions.lock"
_REPOSITORY_LOCKS = "repository-locks"
_PAYLOAD_FIELDS = {
    "objective", "repository", "target_name", "source_head",
    "baseline_patch_sha256", "candidate_id", "candidate_patch_sha256",
    "trusted_evidence_digest",
}
_TRANSACTION_FIELDS = {
    "request_id", "state", "approval_digest", "approval_payload", "repository",
    "source_head", "baseline_patch_sha256", "candidate_id", "candidate_patch",
    "candidate_patch_sha256", "changed_paths", "repository_status_base64",
    "repository_manifest_sha256", "files",
    "repository_integrity_sha256", "unaffected_repository_integrity_sha256",
    "unaffected_status_base64",
}
_FILE_FIELDS = {
    "path", "mode", "filesystem_mode", "sha256", "content_base64",
    "expected_filesystem_mode", "expected_sha256", "expected_content_base64",
}


class CompetitiveApplicationTransactionError(RuntimeError):
    """A competitive application transaction cannot be safely prepared."""


@dataclass(frozen=True)
class CompetitiveApplicationFileSnapshot:
    path: str
    mode: int
    filesystem_mode: int
    sha256: str
    content_base64: str
    expected_filesystem_mode: int
    expected_sha256: str
    expected_content_base64: str


@dataclass(frozen=True)
class CompetitiveApplicationTransaction:
    request_id: str
    state: str
    approval_digest: str
    approval_payload: str
    repository: str
    source_head: str
    baseline_patch_sha256: str
    candidate_id: str
    candidate_patch: str
    candidate_patch_sha256: str
    changed_paths: tuple[str, ...]
    repository_status_base64: str
    repository_manifest_sha256: str
    files: tuple[CompetitiveApplicationFileSnapshot, ...]
    repository_integrity_sha256: str
    unaffected_repository_integrity_sha256: str
    unaffected_status_base64: str


def _default_transaction_dir() -> Path:
    return Path.home() / ".local" / "state" / "sophyane" / "competitive-application-transactions"


def _directory(transaction_dir: Path | None) -> Path:
    return (_default_transaction_dir() if transaction_dir is None else Path(transaction_dir)).expanduser()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str):
        raise CompetitiveApplicationTransactionError("transaction base64 value is invalid")
    try:
        decoded = base64.b64decode(value.encode("ascii", errors="strict"), validate=True)
    except (UnicodeError, binascii.Error, ValueError) as exc:
        raise CompetitiveApplicationTransactionError("transaction base64 value is invalid") from exc
    if _base64(decoded) != value:
        raise CompetitiveApplicationTransactionError("transaction base64 value is not canonical")
    return decoded


def _path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CompetitiveApplicationTransactionError("transaction path is invalid")
    pure = PurePosixPath(value)
    parts = value.split("/")
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in parts) or pure.as_posix() != value:
        raise CompetitiveApplicationTransactionError("transaction path is not normalized")
    return value


def _git(repository: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository), *arguments), check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise CompetitiveApplicationTransactionError("Git inspection is unavailable") from exc
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CompetitiveApplicationTransactionError(
            "Git inspection failed" + (f": {detail}" if detail else "")
        )
    return completed.stdout


def _repository(repository_value: object) -> Path:
    try:
        repository = Path(repository_value).expanduser().resolve()
    except Exception as exc:
        raise CompetitiveApplicationTransactionError("repository path is invalid") from exc
    root = _git(repository, "rev-parse", "--show-toplevel")
    try:
        recorded = Path(root.decode("utf-8", errors="strict").strip()).resolve()
    except (UnicodeError, OSError) as exc:
        raise CompetitiveApplicationTransactionError("repository identity is invalid") from exc
    if recorded != repository:
        raise CompetitiveApplicationTransactionError("repository identity mismatch")
    return repository


def _repository_files(repository: Path) -> tuple[tuple[str, bytes, int], ...]:
    files: list[tuple[str, bytes, int]] = []
    try:
        for root, directories, filenames in os.walk(repository, followlinks=False):
            directories[:] = sorted(name for name in directories if name != ".git")
            root_path = Path(root)
            for name in sorted(filenames):
                path = root_path / name
                path_stat = path.lstat()
                if stat.S_ISREG(path_stat.st_mode):
                    files.append((
                        path.relative_to(repository).as_posix(), path.read_bytes(),
                        stat.S_IMODE(path_stat.st_mode),
                    ))
    except OSError as exc:
        raise CompetitiveApplicationTransactionError("repository snapshot failed") from exc
    return tuple(sorted(files))


def _repository_proof(repository: Path) -> tuple[str, bytes, tuple[tuple[str, bytes, int], ...]]:
    try:
        head = _git(repository, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise CompetitiveApplicationTransactionError("repository HEAD is invalid") from exc
    status = _git(repository, "status", "--porcelain=v1", "-z")
    return head, status, _repository_files(repository)


def _manifest(files: tuple[tuple[str, bytes, int], ...]) -> str:
    mapping = {path: _sha256_bytes(content) for path, content, _ in files}
    return _sha256_bytes(_canonical(mapping).encode("utf-8", errors="strict"))


def _integrity(
    files: tuple[tuple[str, bytes, int], ...], *, excluded: frozenset[str] = frozenset(),
) -> str:
    mapping = {
        path: {"sha256": _sha256_bytes(content), "filesystem_mode": filesystem_mode}
        for path, content, filesystem_mode in files if path not in excluded
    }
    return _sha256_bytes(_canonical(mapping).encode("utf-8", errors="strict"))


def _unaffected_status(repository: Path, paths: tuple[str, ...]) -> bytes:
    validated = tuple(_path(path) for path in paths)
    exclusions = tuple(
        f":(top,exclude,literal){path}" for path in validated
    )
    return _git(repository, "status", "--porcelain=v1", "-z", "--", ".", *exclusions)


def _index_mode(repository: Path, relative: str) -> int:
    output = _git(repository, "ls-files", "--stage", "-z", "--", relative)
    records = [record for record in output.split(b"\0") if record]
    if len(records) != 1:
        raise CompetitiveApplicationTransactionError("affected path is not exactly one tracked file")
    metadata, separator, raw_path = records[0].partition(b"\t")
    fields = metadata.split()
    try:
        stored_path = raw_path.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CompetitiveApplicationTransactionError("index path is invalid") from exc
    if not separator or len(fields) != 3 or fields[0] not in {b"100644", b"100755"}:
        raise CompetitiveApplicationTransactionError("affected path index mode is unsupported")
    if fields[2] != b"0" or stored_path != relative:
        raise CompetitiveApplicationTransactionError("affected path index binding is invalid")
    return int(fields[0])


def _affected_files(repository: Path, paths: tuple[str, ...]) -> tuple[CompetitiveApplicationFileSnapshot, ...]:
    snapshots: list[CompetitiveApplicationFileSnapshot] = []
    for value in paths:
        relative = _path(value)
        mode = _index_mode(repository, relative)
        target = repository / relative
        try:
            path_stat = target.lstat()
            if not stat.S_ISREG(path_stat.st_mode) or target.is_symlink():
                raise CompetitiveApplicationTransactionError("affected path is not a regular file")
            filesystem_mode = stat.S_IMODE(path_stat.st_mode)
            content = target.read_bytes()
        except OSError as exc:
            raise CompetitiveApplicationTransactionError("affected path is unavailable") from exc
        snapshots.append(CompetitiveApplicationFileSnapshot(
            path=relative, mode=mode, filesystem_mode=filesystem_mode,
            sha256=_sha256_bytes(content), content_base64=_base64(content),
            expected_filesystem_mode=filesystem_mode, expected_sha256=_sha256_bytes(content),
            expected_content_base64=_base64(content),
        ))
    snapshots.sort(key=lambda item: item.path)
    if {item.path for item in snapshots} != set(paths) or len(snapshots) != len(paths):
        raise CompetitiveApplicationTransactionError("affected file snapshots do not match changed paths")
    return tuple(snapshots)


def _apply_disposable_patch(repository: Path, patch_path: Path, *, check: bool) -> None:
    arguments = ["git", "apply"]
    if check:
        arguments.append("--check")
    arguments.extend(("--", patch_path.name))
    try:
        completed = subprocess.run(
            arguments, cwd=repository, check=False,
            umask=0,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise CompetitiveApplicationTransactionError("disposable Git application is unavailable") from exc
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CompetitiveApplicationTransactionError(
            "disposable Git application failed" + (f": {detail}" if detail else "")
        )


def _expected_files(
    authoritative_repository: Path, transaction_directory: Path,
    files: tuple[CompetitiveApplicationFileSnapshot, ...], patch: bytes,
) -> tuple[CompetitiveApplicationFileSnapshot, ...]:
    disposable: Path | None = None
    try:
        disposable = Path(tempfile.mkdtemp(
            prefix=".post-image-", dir=transaction_directory,
        )).resolve()
        try:
            disposable.relative_to(authoritative_repository)
        except ValueError:
            pass
        else:
            raise CompetitiveApplicationTransactionError(
                "disposable repository is inside authoritative repository"
            )
        for item in files:
            target = disposable / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as stream:
                stream.write(_decode_base64(item.content_base64))
            target.chmod(item.filesystem_mode)
        _git(disposable, "init")
        _git(disposable, "config", "user.email", "transaction.invalid")
        _git(disposable, "config", "user.name", "Competitive Transaction")
        _git(disposable, "add", "--", *(item.path for item in files))
        _git(disposable, "commit", "-m", "pre-image")
        descriptor, patch_name = tempfile.mkstemp(prefix=".candidate-", suffix=".patch", dir=disposable)
        patch_path = Path(patch_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(patch)
        _apply_disposable_patch(disposable, patch_path, check=True)
        _apply_disposable_patch(disposable, patch_path, check=False)
        for item in files:
            target = disposable / item.path
            target_stat = target.lstat()
            if not stat.S_ISREG(target_stat.st_mode) or target.is_symlink():
                raise CompetitiveApplicationTransactionError("disposable post-image is not a regular file")
            target.chmod(item.filesystem_mode)
        patch_path.unlink()
        inventory = _repository_files(disposable)
        inventory_by_path = {path: (content, mode) for path, content, mode in inventory}
        expected_paths = {item.path for item in files}
        if set(inventory_by_path) != expected_paths:
            raise CompetitiveApplicationTransactionError("disposable post-image paths are inconsistent")
        expected: list[CompetitiveApplicationFileSnapshot] = []
        for item in files:
            target = disposable / item.path
            target_stat = target.lstat()
            if not stat.S_ISREG(target_stat.st_mode) or target.is_symlink():
                raise CompetitiveApplicationTransactionError("disposable post-image is not a regular file")
            content, filesystem_mode = inventory_by_path[item.path]
            if filesystem_mode != item.filesystem_mode:
                raise CompetitiveApplicationTransactionError("disposable post-image mode changed")
            expected.append(replace(
                item, expected_filesystem_mode=filesystem_mode,
                expected_sha256=_sha256_bytes(content),
                expected_content_base64=_base64(content),
            ))
        if all(item.expected_sha256 == item.sha256 for item in expected):
            raise CompetitiveApplicationTransactionError("candidate patch changes no affected file bytes")
        return tuple(expected)
    except CompetitiveApplicationTransactionError:
        raise
    except OSError as exc:
        raise CompetitiveApplicationTransactionError("disposable post-image construction failed") from exc
    finally:
        if disposable is not None:
            shutil.rmtree(disposable)


def _payload(value: object) -> dict[str, str]:
    if not isinstance(value, str) or not value:
        raise CompetitiveApplicationTransactionError("approval payload is invalid")
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CompetitiveApplicationTransactionError("approval payload is malformed") from exc
    if not isinstance(parsed, dict) or set(parsed) != _PAYLOAD_FIELDS:
        raise CompetitiveApplicationTransactionError("approval payload keys are invalid")
    if any(not isinstance(item, str) or not item for item in parsed.values()):
        raise CompetitiveApplicationTransactionError("approval payload bindings are invalid")
    if _canonical(parsed) != value:
        raise CompetitiveApplicationTransactionError("approval payload is not canonical")
    return parsed


def _file_from_record(value: object) -> CompetitiveApplicationFileSnapshot:
    if not isinstance(value, dict) or set(value) != _FILE_FIELDS:
        raise CompetitiveApplicationTransactionError("transaction file record is malformed")
    path = _path(value["path"])
    mode = value["mode"]
    if isinstance(mode, bool) or mode not in {100644, 100755}:
        raise CompetitiveApplicationTransactionError("transaction file mode is invalid")
    filesystem_mode = value["filesystem_mode"]
    if (isinstance(filesystem_mode, bool) or not isinstance(filesystem_mode, int)
            or not 0 <= filesystem_mode <= 0o777):
        raise CompetitiveApplicationTransactionError("transaction filesystem mode is invalid")
    content = _decode_base64(value["content_base64"])
    if not _valid_digest(value["sha256"]) or _sha256_bytes(content) != value["sha256"]:
        raise CompetitiveApplicationTransactionError("transaction file digest mismatch")
    expected_filesystem_mode = value["expected_filesystem_mode"]
    if (isinstance(expected_filesystem_mode, bool)
            or not isinstance(expected_filesystem_mode, int)
            or not 0 <= expected_filesystem_mode <= 0o777
            or expected_filesystem_mode != filesystem_mode):
        raise CompetitiveApplicationTransactionError("transaction expected filesystem mode is invalid")
    expected_content = _decode_base64(value["expected_content_base64"])
    if (not _valid_digest(value["expected_sha256"])
            or _sha256_bytes(expected_content) != value["expected_sha256"]):
        raise CompetitiveApplicationTransactionError("transaction expected file digest mismatch")
    return CompetitiveApplicationFileSnapshot(
        path, mode, filesystem_mode, value["sha256"], value["content_base64"],
        expected_filesystem_mode, value["expected_sha256"], value["expected_content_base64"],
    )


def _transaction_from_record(value: object) -> CompetitiveApplicationTransaction:
    if not isinstance(value, dict) or set(value) != _TRANSACTION_FIELDS:
        raise CompetitiveApplicationTransactionError("transaction record is malformed")
    string_fields = _TRANSACTION_FIELDS - {
        "changed_paths", "files", "repository_status_base64", "unaffected_status_base64",
    }
    if any(not isinstance(value[field], str) or not value[field] for field in string_fields):
        raise CompetitiveApplicationTransactionError("transaction bindings are malformed")
    if value["state"] != "prepared":
        raise CompetitiveApplicationTransactionError("transaction state is invalid")
    payload = _payload(value["approval_payload"])
    if not _valid_digest(value["approval_digest"]) or _sha256_bytes(value["approval_payload"].encode("utf-8", errors="strict")) != value["approval_digest"]:
        raise CompetitiveApplicationTransactionError("transaction approval digest mismatch")
    if not isinstance(value["candidate_patch"], str):
        raise CompetitiveApplicationTransactionError("transaction candidate patch is invalid")
    try:
        patch = value["candidate_patch"].encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CompetitiveApplicationTransactionError("transaction candidate patch is not strict UTF-8") from exc
    if not patch or not _valid_digest(value["candidate_patch_sha256"]) or _sha256_bytes(patch) != value["candidate_patch_sha256"]:
        raise CompetitiveApplicationTransactionError("transaction candidate patch digest mismatch")
    if not _valid_digest(value["repository_manifest_sha256"]):
        raise CompetitiveApplicationTransactionError("transaction manifest digest is invalid")
    if (not _valid_digest(value["repository_integrity_sha256"])
            or not _valid_digest(value["unaffected_repository_integrity_sha256"])):
        raise CompetitiveApplicationTransactionError("transaction integrity digest is invalid")
    _decode_base64(value["repository_status_base64"])
    _decode_base64(value["unaffected_status_base64"])
    if not isinstance(value["changed_paths"], list) or not value["changed_paths"]:
        raise CompetitiveApplicationTransactionError("transaction changed paths are invalid")
    changed_paths = tuple(_path(item) for item in value["changed_paths"])
    if len(changed_paths) != len(set(changed_paths)):
        raise CompetitiveApplicationTransactionError("transaction changed paths contain duplicates")
    if not isinstance(value["files"], list):
        raise CompetitiveApplicationTransactionError("transaction files are invalid")
    files = tuple(_file_from_record(item) for item in value["files"])
    if files and all(item.expected_sha256 == item.sha256 for item in files):
        raise CompetitiveApplicationTransactionError("transaction expected files are unchanged")
    file_paths = tuple(item.path for item in files)
    if file_paths != tuple(sorted(file_paths)) or set(file_paths) != set(changed_paths) or len(file_paths) != len(changed_paths):
        raise CompetitiveApplicationTransactionError("transaction file paths are inconsistent")
    for key in ("repository", "source_head", "baseline_patch_sha256", "candidate_id", "candidate_patch_sha256"):
        if payload[key] != value[key]:
            raise CompetitiveApplicationTransactionError("transaction approval binding mismatch")
    return CompetitiveApplicationTransaction(
        request_id=value["request_id"], state=value["state"], approval_digest=value["approval_digest"],
        approval_payload=value["approval_payload"], repository=value["repository"],
        source_head=value["source_head"], baseline_patch_sha256=value["baseline_patch_sha256"],
        candidate_id=value["candidate_id"], candidate_patch=value["candidate_patch"],
        candidate_patch_sha256=value["candidate_patch_sha256"], changed_paths=changed_paths,
        repository_status_base64=value["repository_status_base64"],
        repository_manifest_sha256=value["repository_manifest_sha256"], files=files,
        repository_integrity_sha256=value["repository_integrity_sha256"],
        unaffected_repository_integrity_sha256=value["unaffected_repository_integrity_sha256"],
        unaffected_status_base64=value["unaffected_status_base64"],
    )


def _load(path: Path) -> list[CompetitiveApplicationTransaction]:
    try:
        value = json.loads(path.read_bytes().decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompetitiveApplicationTransactionError("transaction ledger is malformed") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "transactions"}:
        raise CompetitiveApplicationTransactionError("transaction ledger structure is invalid")
    if value["schema_version"] != _SCHEMA_VERSION or isinstance(value["schema_version"], bool):
        raise CompetitiveApplicationTransactionError("transaction ledger schema is unsupported")
    if not isinstance(value["transactions"], list):
        raise CompetitiveApplicationTransactionError("transaction ledger records are invalid")
    transactions = [_transaction_from_record(item) for item in value["transactions"]]
    identifiers = [item.request_id for item in transactions]
    if len(identifiers) != len(set(identifiers)):
        raise CompetitiveApplicationTransactionError("transaction ledger has duplicate request IDs")
    if identifiers != sorted(identifiers):
        raise CompetitiveApplicationTransactionError("transaction ledger records are unsorted")
    return transactions


def _publish(directory: Path, ledger: Path, transactions: list[CompetitiveApplicationTransaction]) -> None:
    contents = (_canonical({
        "schema_version": _SCHEMA_VERSION,
        "transactions": [asdict(item) for item in transactions],
    }) + "\n").encode("utf-8", errors="strict")
    descriptor = -1
    temporary: str | None = None
    published = False
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".transactions-", suffix=".tmp", dir=directory)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, ledger)
        published = True
        try:
            directory_descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            pass
    except (OSError, UnicodeError, TypeError) as exc:
        raise CompetitiveApplicationTransactionError("transaction ledger publication failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None and not published:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _from_plan(plan: CompetitiveApplicationPlan, proof: tuple[str, bytes, tuple[tuple[str, bytes, int], ...]], repository: Path, transaction_directory: Path, unaffected_status: bytes) -> CompetitiveApplicationTransaction:
    if proof[0] != plan.source_head:
        raise CompetitiveApplicationTransactionError("repository HEAD differs from application plan")
    if plan.repository != str(repository):
        raise CompetitiveApplicationTransactionError("application plan repository mismatch")
    try:
        patch_bytes = plan.candidate_patch.encode("utf-8", errors="strict")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise CompetitiveApplicationTransactionError("candidate patch is not strict UTF-8") from exc
    if not patch_bytes or _sha256_bytes(patch_bytes) != plan.candidate_patch_sha256:
        raise CompetitiveApplicationTransactionError("candidate patch digest mismatch")
    files = _affected_files(repository, plan.changed_paths)
    proof_files = {path: (content, filesystem_mode) for path, content, filesystem_mode in proof[2]}
    if any(
        item.path not in proof_files
        or item.sha256 != _sha256_bytes(proof_files[item.path][0])
        or item.content_base64 != _base64(proof_files[item.path][0])
        or item.filesystem_mode != proof_files[item.path][1]
        for item in files
    ):
        raise CompetitiveApplicationTransactionError("affected files differ from repository snapshot")
    files = _expected_files(repository, transaction_directory, files, patch_bytes)
    return CompetitiveApplicationTransaction(
        request_id=plan.request_id, state="prepared", approval_digest=plan.approval_digest,
        approval_payload=plan.approval_payload, repository=plan.repository,
        source_head=plan.source_head, baseline_patch_sha256=plan.baseline_patch_sha256,
        candidate_id=plan.candidate_id, candidate_patch=plan.candidate_patch,
        candidate_patch_sha256=plan.candidate_patch_sha256, changed_paths=plan.changed_paths,
        repository_status_base64=_base64(proof[1]), repository_manifest_sha256=_manifest(proof[2]),
        files=files, repository_integrity_sha256=_integrity(proof[2]),
        unaffected_repository_integrity_sha256=_integrity(
            proof[2], excluded=frozenset(plan.changed_paths),
        ),
        unaffected_status_base64=_base64(unaffected_status),
    )


def prepare_competitive_application_transaction(
    evaluation: CompetitiveEvaluationResult,
    request_id: str,
    *,
    transaction_dir: Path | None = None,
) -> CompetitiveApplicationTransaction:
    repository = _repository(evaluation.repository)
    directory = _directory(transaction_dir)
    try:
        try:
            directory.resolve().relative_to(repository)
        except ValueError:
            pass
        else:
            raise CompetitiveApplicationTransactionError("transaction state is inside repository")
        directory.mkdir(parents=True, exist_ok=True)
        lock_directory = directory / _REPOSITORY_LOCKS
        lock_directory.mkdir(parents=True, exist_ok=True)
        repository_key = _sha256_bytes(str(repository).encode("utf-8", errors="strict"))
        repository_lock_path = lock_directory / f"{repository_key}.lock"
        try:
            repository_lock_path.resolve().relative_to(repository)
        except ValueError:
            pass
        else:
            raise CompetitiveApplicationTransactionError("repository lock is inside repository")
        with repository_lock_path.open("a+b") as repository_lock:
            fcntl.flock(repository_lock.fileno(), fcntl.LOCK_EX)
            initial = _repository_proof(repository)
            try:
                try:
                    plan = prepare_competitive_application(evaluation, request_id)
                except Exception as exc:
                    raise CompetitiveApplicationTransactionError(f"application preflight failed: {exc}") from exc
                proof = _repository_proof(repository)
                unaffected_status = _unaffected_status(repository, plan.changed_paths)
                if _repository_proof(repository) != proof:
                    raise CompetitiveApplicationTransactionError(
                        "repository changed while binding unaffected status"
                    )
                transaction = _from_plan(
                    plan, proof, repository, directory, unaffected_status,
                )
                if _repository_proof(repository) != initial:
                    raise CompetitiveApplicationTransactionError("repository changed during transaction preparation")
                ledger_lock_path = directory / _LEDGER_LOCK_NAME
                with ledger_lock_path.open("a+b") as ledger_lock:
                    fcntl.flock(ledger_lock.fileno(), fcntl.LOCK_EX)
                    ledger = directory / _LEDGER_NAME
                    transactions = _load(ledger) if ledger.exists() else []
                    existing = next((item for item in transactions if item.request_id == request_id), None)
                    if existing is not None:
                        if existing == transaction:
                            return existing
                        raise CompetitiveApplicationTransactionError("conflicting application transaction")
                    transactions.append(transaction)
                    transactions.sort(key=lambda item: item.request_id)
                    _publish(directory, ledger, transactions)
                return transaction
            finally:
                final = _repository_proof(repository)
                if final != initial:
                    raise CompetitiveApplicationTransactionError("repository changed during transaction preparation")
    except CompetitiveApplicationTransactionError:
        raise
    except (OSError, UnicodeError) as exc:
        raise CompetitiveApplicationTransactionError("transaction state is unavailable") from exc


def get_competitive_application_transaction(
    request_id: str,
    *,
    transaction_dir: Path | None = None,
) -> CompetitiveApplicationTransaction | None:
    if not isinstance(request_id, str) or not request_id:
        raise CompetitiveApplicationTransactionError("request_id must be a non-empty string")
    directory = _directory(transaction_dir)
    ledger = directory / _LEDGER_NAME
    lock_path = directory / _LEDGER_LOCK_NAME
    if not ledger.exists() and not lock_path.exists():
        return None
    try:
        with lock_path.open("rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            if not ledger.exists():
                return None
            transactions = _load(ledger)
    except FileNotFoundError as exc:
        raise CompetitiveApplicationTransactionError("transaction ledger lock is missing") from exc
    except CompetitiveApplicationTransactionError:
        raise
    except OSError as exc:
        raise CompetitiveApplicationTransactionError("transaction state is unavailable") from exc
    matches = [item for item in transactions if item.request_id == request_id]
    return matches[0] if matches else None
