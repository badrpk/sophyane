"""Durable, terminal consumption of approved competitive evaluations."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from sophyane.competitive_coding_approval import verify_competitive_approval
from sophyane.competitive_coding_phase2 import CompetitiveEvaluationResult

__all__ = [
    "CompetitiveConsumptionError",
    "CompetitiveApprovalClaim",
    "claim_competitive_approval",
    "get_competitive_approval_claim",
]

_SCHEMA_VERSION = 1
_LEDGER_NAME = "claims.json"
_LOCK_NAME = "ledger.lock"
_CLAIM_FIELDS = {
    "request_id",
    "state",
    "approval_digest",
    "approval_payload",
    "repository",
    "source_head",
    "baseline_patch_sha256",
    "candidate_id",
    "candidate_patch_sha256",
    "trusted_evidence_digest",
}
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


class CompetitiveConsumptionError(RuntimeError):
    """An approval cannot be safely claimed or its ledger cannot be trusted."""


@dataclass(frozen=True)
class CompetitiveApprovalClaim:
    request_id: str
    state: str
    approval_digest: str
    approval_payload: str
    repository: str
    source_head: str
    baseline_patch_sha256: str
    candidate_id: str
    candidate_patch_sha256: str
    trusted_evidence_digest: str


def _default_ledger_dir() -> Path:
    return Path.home() / ".local" / "state" / "sophyane" / "competitive-approval-claims"


def _directory(ledger_dir: Path | None) -> Path:
    directory = _default_ledger_dir() if ledger_dir is None else Path(ledger_dir)
    return directory.expanduser()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: str) -> str:
    try:
        encoded = payload.encode("utf-8", errors="strict")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise CompetitiveConsumptionError("approval payload is not strict UTF-8") from exc
    return hashlib.sha256(encoded).hexdigest()


def _payload(value: object) -> dict[str, str]:
    if not isinstance(value, str) or not value:
        raise CompetitiveConsumptionError("approval payload must be non-empty canonical JSON")
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CompetitiveConsumptionError("approval payload is malformed") from exc
    if not isinstance(parsed, dict) or set(parsed) != _PAYLOAD_FIELDS:
        raise CompetitiveConsumptionError("approval payload keys are invalid")
    if any(not isinstance(item, str) or not item for item in parsed.values()):
        raise CompetitiveConsumptionError("approval payload bindings must be non-empty strings")
    if _canonical(parsed) != value:
        raise CompetitiveConsumptionError("approval payload is not canonical JSON")
    return parsed


def _claim_from_record(record: object) -> CompetitiveApprovalClaim:
    if not isinstance(record, dict) or set(record) != _CLAIM_FIELDS:
        raise CompetitiveConsumptionError("ledger claim record is malformed")
    if any(not isinstance(record[key], str) or not record[key] for key in _CLAIM_FIELDS):
        raise CompetitiveConsumptionError("ledger claim bindings are malformed")
    if record["state"] != "claimed":
        raise CompetitiveConsumptionError("ledger claim state is invalid")
    payload = _payload(record["approval_payload"])
    if _digest(record["approval_payload"]) != record["approval_digest"]:
        raise CompetitiveConsumptionError("ledger approval digest mismatch")
    for key in _PAYLOAD_FIELDS - {"objective", "target_name"}:
        if payload[key] != record[key]:
            raise CompetitiveConsumptionError("ledger approval binding mismatch")
    return CompetitiveApprovalClaim(**record)


def _load_ledger(path: Path) -> list[CompetitiveApprovalClaim]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompetitiveConsumptionError("consumption ledger is malformed") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "claims"}:
        raise CompetitiveConsumptionError("consumption ledger structure is invalid")
    if value["schema_version"] != _SCHEMA_VERSION or isinstance(value["schema_version"], bool):
        raise CompetitiveConsumptionError("consumption ledger schema is unsupported")
    if not isinstance(value["claims"], list):
        raise CompetitiveConsumptionError("consumption ledger claims are malformed")
    claims = [_claim_from_record(record) for record in value["claims"]]
    identifiers = [claim.request_id for claim in claims]
    if len(identifiers) != len(set(identifiers)):
        raise CompetitiveConsumptionError("consumption ledger has duplicate request IDs")
    if identifiers != sorted(identifiers):
        raise CompetitiveConsumptionError("consumption ledger claim order is invalid")
    return claims


def _publish(directory: Path, ledger: Path, claims: list[CompetitiveApprovalClaim]) -> None:
    contents = (_canonical({
        "schema_version": _SCHEMA_VERSION,
        "claims": [asdict(claim) for claim in claims],
    }) + "\n").encode("utf-8", errors="strict")
    descriptor = -1
    temporary: str | None = None
    published = False
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".claims-", suffix=".tmp", dir=directory)
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
        raise CompetitiveConsumptionError("could not publish consumption ledger") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None and not published:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def claim_competitive_approval(
    evaluation: CompetitiveEvaluationResult,
    request_id: str,
    *,
    ledger_dir: Path | None = None,
) -> CompetitiveApprovalClaim:
    try:
        verification = verify_competitive_approval(evaluation, request_id)
    except Exception as exc:
        raise CompetitiveConsumptionError(f"competitive approval verification failed: {exc}") from exc
    if verification.approved is not True or verification.status != "approved":
        raise CompetitiveConsumptionError("competitive approval is not approved")
    if verification.request_id != request_id:
        raise CompetitiveConsumptionError("competitive approval request ID mismatch")
    payload = _payload(verification.approval_payload)
    if not isinstance(verification.approval_digest, str) or not verification.approval_digest:
        raise CompetitiveConsumptionError("competitive approval digest is invalid")
    if _digest(verification.approval_payload) != verification.approval_digest:
        raise CompetitiveConsumptionError("competitive approval digest mismatch")
    if not isinstance(request_id, str) or not request_id:
        raise CompetitiveConsumptionError("request_id must be a non-empty string")
    claim = CompetitiveApprovalClaim(
        request_id=request_id,
        state="claimed",
        approval_digest=verification.approval_digest,
        approval_payload=verification.approval_payload,
        repository=payload["repository"],
        source_head=payload["source_head"],
        baseline_patch_sha256=payload["baseline_patch_sha256"],
        candidate_id=payload["candidate_id"],
        candidate_patch_sha256=payload["candidate_patch_sha256"],
        trusted_evidence_digest=payload["trusted_evidence_digest"],
    )

    directory = _directory(ledger_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / _LOCK_NAME).open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            ledger = directory / _LEDGER_NAME
            claims = _load_ledger(ledger) if ledger.exists() else []
            existing = next((item for item in claims if item.request_id == request_id), None)
            if existing is not None:
                if existing == claim:
                    raise CompetitiveConsumptionError("competitive approval claim replay")
                raise CompetitiveConsumptionError("conflicting competitive approval claim")
            claims.append(claim)
            claims.sort(key=lambda item: item.request_id)
            _publish(directory, ledger, claims)
    except CompetitiveConsumptionError:
        raise
    except OSError as exc:
        raise CompetitiveConsumptionError("consumption ledger is unavailable") from exc
    return claim


def get_competitive_approval_claim(
    request_id: str,
    *,
    ledger_dir: Path | None = None,
) -> CompetitiveApprovalClaim | None:
    if not isinstance(request_id, str) or not request_id:
        raise CompetitiveConsumptionError("request_id must be a non-empty string")
    directory = _directory(ledger_dir)
    ledger = directory / _LEDGER_NAME
    lock_path = directory / _LOCK_NAME
    if not lock_path.exists() and not ledger.exists():
        return None
    try:
        with lock_path.open("rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            if not ledger.exists():
                return None
            claims = _load_ledger(ledger)
    except FileNotFoundError as exc:
        raise CompetitiveConsumptionError("consumption ledger lock is missing") from exc
    except CompetitiveConsumptionError:
        raise
    except OSError as exc:
        raise CompetitiveConsumptionError("consumption ledger is unavailable") from exc
    matches = [claim for claim in claims if claim.request_id == request_id]
    return matches[0] if matches else None
