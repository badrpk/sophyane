"""GitHub-hosted ephemeral candidate qualification client and evidence verifier.

This execution class is intentionally separate from the dedicated Linux SSEE
host. It validates a narrowly scoped Python JSON-lines job on an ephemeral
GitHub-hosted VM with an isolated Docker container; it does not authorize
arbitrary repository candidate execution or production promotion.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .github_client import GitHubSSEEClient, GitHubSSEEError

WORKFLOW_PATH = ".github/workflows/ssee-hosted-qualification.yml"
WORKFLOW_NAME = "SSEE hosted candidate qualification"
ARTIFACT_NAME = "ssee-hosted-qualification-report"
REPORT_NAME = "qualification-report.json"
DIGEST_NAME = "qualification-report.sha256"
IMAGE = "python:3.13.18-slim-bookworm@sha256:f0fa218d5b06f9b9235024fa061cde2cb141f726de52134471053d2d9b5324a3"
MAX_REPORT_BYTES = 128 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_PIN = re.compile(r"^[A-Za-z0-9._/:+-]+@sha256:[0-9a-f]{64}$")
_CONTAINER = re.compile(r"^ssee-[a-z0-9-]{1,60}$")
_REQUEST_TITLE = "SSEE hosted qualification "


class HostedQualificationError(GitHubSSEEError):
    """Hosted execution is unavailable or its evidence failed verification."""


@dataclass(frozen=True)
class QualificationRequest:
    candidate_sha: str
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        if not isinstance(self.candidate_sha, str) or not _SHA1.fullmatch(self.candidate_sha):
            raise ValueError("candidate_sha must be an immutable 40-character commit SHA")
        try:
            parsed = uuid.UUID(self.request_id)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("request_id must be a UUID") from None
        if str(parsed) != self.request_id:
            raise ValueError("request_id must use canonical UUID form")


def build_candidate_command(*, docker="docker", image=IMAGE,
                            candidate_file="/tmp/ssee-candidate.py",
                            container_name="ssee-candidate"):
    """Return fixed Docker argv; candidate content cannot supply options."""
    if not isinstance(image, str) or not _IMAGE_PIN.fullmatch(image):
        raise ValueError("candidate image must be pinned by SHA-256 digest")
    if not isinstance(candidate_file, str) or not candidate_file.startswith("/") or "\x00" in candidate_file:
        raise ValueError("candidate file must be an absolute path")
    if not isinstance(container_name, str) or not _CONTAINER.fullmatch(container_name):
        raise ValueError("invalid isolated container name")
    return [
        docker, "run", "--name", container_name,
        "--network=none", "--read-only", "--memory=268435456", "--cpus=0.5",
        "--pids-limit=32", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--security-opt=seccomp=default", "--user=65532:65532", "--ulimit=core=0",
        "--ulimit=nofile=64:64", "--mount",
        f"type=bind,src={candidate_file},dst=/candidate.py,readonly",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16777216",
        "--entrypoint", "python3", image, "-I", "/candidate.py",
    ]


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def verify_hosted_report(report_bytes: bytes, *, expected_request_id: str,
                         expected_candidate_sha: str, expected_workflow_sha: str,
                         expected_run_id: int) -> dict[str, Any]:
    """Verify bounded report identity and host-observed container policy."""
    if not isinstance(report_bytes, bytes) or not 0 < len(report_bytes) <= MAX_REPORT_BYTES:
        raise HostedQualificationError("qualification report missing or oversized")
    try:
        report = json.loads(report_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise HostedQualificationError("qualification report is invalid JSON") from None
    if not isinstance(report, dict):
        raise HostedQualificationError("qualification report root must be an object")
    expected = {
        "schema_version": 1,
        "request_id": expected_request_id,
        "candidate_sha": expected_candidate_sha,
        "workflow_sha": expected_workflow_sha,
        "workflow_path": WORKFLOW_PATH,
        "run_id": expected_run_id,
        "execution_class": "python_jsonl_v1",
    }
    for key, value in expected.items():
        if report.get(key) != value:
            raise HostedQualificationError(f"qualification report {key} binding mismatch")
    if not _SHA1.fullmatch(str(report.get("candidate_sha", ""))) or not _SHA1.fullmatch(str(report.get("workflow_sha", ""))):
        raise HostedQualificationError("qualification report commit identity is invalid")
    if report.get("candidate_status") not in {"accepted", "rejected"}:
        raise HostedQualificationError("qualification candidate status is malformed")
    isolation = report.get("isolation")
    if not isinstance(isolation, dict):
        raise HostedQualificationError("hosted isolation evidence is missing")
    required_isolation = {
        "runner_kind": "github-hosted-ephemeral-vm",
        "container_image": IMAGE,
        "network_mode": "none",
        "readonly_rootfs": True,
        "memory_bytes": 268435456,
        "cpu_nanos": 500000000,
        "pids_limit": 32,
        "cap_drop": ["ALL"],
        "no_new_privileges": True,
        "candidate_mounts_readonly": True,
        "candidate_env_allowlist_only": True,
        "credential_names_observed": [],
        "host_mounts_observed": [],
        "container_cleanup_verified": True,
        "network_probe_blocked": True,
    }
    for key, value in required_isolation.items():
        if isolation.get(key) != value:
            raise HostedQualificationError(f"hosted isolation evidence mismatch: {key}")
    if not isinstance(isolation.get("runner_image"), str) or not isolation["runner_image"]:
        raise HostedQualificationError("GitHub runner image identity is missing")
    tests = report.get("tests")
    if (not isinstance(tests, dict)
            or any(not isinstance(tests.get(name), int) or tests[name] < 0
                   for name in ("passed", "failed", "timed_out"))
            or tests["passed"] + tests["failed"] + tests["timed_out"] != 4):
        raise HostedQualificationError("independent test result counts are malformed")
    fixture = report.get("fixture")
    expected_counts = {
        "pass": (4, 0, 0), "fail": (0, 4, 0),
        "timeout": (0, 0, 4), "network": (0, 4, 0),
    }
    counts = (tests["passed"], tests["failed"], tests["timed_out"])
    expected_status = "accepted" if counts == (4, 0, 0) else "rejected"
    if report["candidate_status"] != expected_status:
        raise HostedQualificationError("candidate status does not match independent test counts")
    if fixture in expected_counts and counts != expected_counts[fixture]:
        raise HostedQualificationError("fixture result does not match its trusted expected outcome")
    if report.get("expected_fixture_outcome_observed") is not True:
        raise HostedQualificationError("trusted fixture outcome was not confirmed")
    records = report.get("case_evidence")
    if (not isinstance(records, list) or len(records) != 4
            or any(not isinstance(item, dict)
                   or item.get("status") not in {"passed", "test_failed", "timed_out", "output_limit", "process_failed"}
                   or not isinstance(item.get("passed"), bool)
                   or not isinstance(item.get("timed_out"), bool)
                   or not _SHA256.fullmatch(str(item.get("output_sha256", "")))
                   for item in records)):
        raise HostedQualificationError("per-case independent evidence is malformed")
    observed_counts = (
        sum(item["passed"] for item in records),
        sum(not item["passed"] and not item["timed_out"] for item in records),
        sum(item["timed_out"] for item in records),
    )
    if observed_counts != counts:
        raise HostedQualificationError("test summary does not match per-case evidence")
    if not _SHA256.fullmatch(str(report.get("candidate_file_sha256", ""))):
        raise HostedQualificationError("candidate file digest is invalid")
    if report.get("fixture") not in {"candidate", "pass", "fail", "timeout", "network"}:
        raise HostedQualificationError("qualification fixture is unknown")
    return report


def read_hosted_report_artifact(zip_bytes: bytes, *, expected_zip_sha256: str | None = None) -> bytes:
    if not isinstance(zip_bytes, bytes) or not 0 < len(zip_bytes) <= MAX_ARTIFACT_BYTES:
        raise HostedQualificationError("qualification artifact missing or oversized")
    if expected_zip_sha256 is not None and hashlib.sha256(zip_bytes).hexdigest() != expected_zip_sha256:
        raise HostedQualificationError("GitHub artifact ZIP digest mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            members = archive.infolist()
            if len(members) != 2 or {m.filename for m in members} != {REPORT_NAME, DIGEST_NAME}:
                raise HostedQualificationError("artifact must contain exactly report and SHA-256 sidecar")
            for member in members:
                mode = member.external_attr >> 16
                if (member.is_dir() or PurePosixPath(member.filename).is_absolute()
                        or ".." in PurePosixPath(member.filename).parts
                        or (mode & 0o170000) not in (0, 0o100000)
                        or member.file_size > MAX_REPORT_BYTES):
                    raise HostedQualificationError("artifact has unsafe or oversized member")
            report_bytes = archive.read(REPORT_NAME)
            digest = archive.read(DIGEST_NAME).decode("ascii").strip()
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        raise HostedQualificationError("qualification artifact ZIP is malformed") from None
    if not _SHA256.fullmatch(digest) or hashlib.sha256(report_bytes).hexdigest() != digest:
        raise HostedQualificationError("qualification report digest mismatch")
    return report_bytes


class GitHubHostedQualificationClient(GitHubSSEEClient):
    """Dispatch and verify the trusted workflow from a protected default branch."""

    def __init__(self, owner, repo, token, *, expected_default_branch="main", **kwargs):
        if expected_default_branch != "main":
            raise ValueError("hosted qualification currently requires the protected main branch")
        super().__init__(owner, repo, token, **kwargs)
        self.expected_default_branch = expected_default_branch

    def dispatch(self, candidate_sha: str, *, expected_workflow_sha: str,
                 fixture="candidate") -> dict[str, str]:
        request = QualificationRequest(candidate_sha)
        if not _SHA1.fullmatch(str(expected_workflow_sha)):
            raise ValueError("expected_workflow_sha must be a full commit SHA")
        if fixture not in {"candidate", "pass", "fail", "timeout", "network"}:
            raise ValueError("unsupported qualification fixture")
        try:
            protection = self._api("GET", f"/branches/{self.expected_default_branch}/protection")
        except GitHubSSEEError:
            raise HostedQualificationError("default branch is not protected") from None
        reviews = protection.get("required_pull_request_reviews") or {}
        admins = protection.get("enforce_admins") or {}
        if (not isinstance(reviews, dict) or reviews.get("required_approving_review_count", 0) < 1
                or not isinstance(admins, dict) or admins.get("enabled") is not True):
            raise HostedQualificationError("main protection must require review and apply to administrators")
        ref = self._api("GET", f"/git/ref/heads/{self.expected_default_branch}")
        actual_workflow_sha = ((ref.get("object") or {}).get("sha")
                               if isinstance(ref, dict) else None)
        if actual_workflow_sha != expected_workflow_sha:
            raise HostedQualificationError("protected workflow SHA changed before dispatch")
        self._api("POST", f"/actions/workflows/{WORKFLOW_PATH}/dispatches", body={
            "ref": self.expected_default_branch,
            "inputs": {"request_id": request.request_id,
                       "candidate_sha": request.candidate_sha,
                       "fixture": fixture},
        })
        return {"request_id": request.request_id, "candidate_sha": candidate_sha,
                "workflow_sha": expected_workflow_sha, "fixture": fixture,
                "workflow_path": WORKFLOW_PATH}

    def _find_run(self, request_id: str, expected_workflow_sha: str):
        try:
            uuid.UUID(request_id)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("request_id must be a UUID") from None
        result = self._api("GET", f"/actions/workflows/{WORKFLOW_PATH}/runs?branch={self.expected_default_branch}&event=workflow_dispatch&per_page=100")
        runs = result.get("workflow_runs", []) if isinstance(result, dict) else []
        if isinstance(result, dict) and result.get("total_count", len(runs)) > len(runs):
            raise HostedQualificationError("workflow run listing is paginated; refusing ambiguous selection")
        title = _REQUEST_TITLE + request_id
        matches = [run for run in runs if run.get("display_title") == title]
        if len(matches) > 1:
            raise HostedQualificationError("duplicate workflow runs match request id")
        if not matches:
            return None
        run = matches[0]
        run_path = run.get("path")
        valid_path = run_path in {
            WORKFLOW_PATH,
            WORKFLOW_PATH + "@refs/heads/" + self.expected_default_branch,
        }
        if (run.get("event") != "workflow_dispatch"
                or run.get("head_branch") != self.expected_default_branch
                or run.get("head_sha") != expected_workflow_sha
                or not valid_path):
            raise HostedQualificationError("workflow run is not bound to the pinned trusted definition")
        if not isinstance(run.get("id"), int):
            raise HostedQualificationError("workflow run ID is malformed")
        return run

    def status(self, request: dict, *, timeout_seconds=1800, poll_seconds=5):
        if not 1 <= timeout_seconds <= 7200 or not 1 <= poll_seconds <= 30:
            raise ValueError("invalid hosted qualification polling bounds")
        deadline = time.monotonic() + timeout_seconds
        while True:
            run = self._find_run(request["request_id"], request["workflow_sha"])
            if run:
                if run.get("status") == "completed":
                    return run
                if run.get("status") not in {"queued", "in_progress", "requested", "waiting", "pending"}:
                    raise HostedQualificationError("GitHub returned an unexpected workflow state")
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for GitHub-hosted qualification")
            time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))

    def cancel(self, request: dict):
        run = self._find_run(request["request_id"], request["workflow_sha"])
        if run is None:
            raise HostedQualificationError("qualification workflow run is not visible")
        if run.get("status") == "completed":
            return {"run_id": run["id"], "status": "completed", "cancelled": False}
        self._api("POST", f"/actions/runs/{run['id']}/cancel", body={})
        return {"run_id": run["id"], "status": "cancel_requested", "cancelled": True}

    def retrieve_evidence(self, request: dict, completed_run: dict):
        run = self._find_run(request["request_id"], request["workflow_sha"])
        if (run is None or completed_run.get("id") != run.get("id")
                or run.get("status") != "completed" or run.get("conclusion") != "success"):
            raise HostedQualificationError("workflow run is not a completed trusted qualification")
        listing = self._api("GET", f"/actions/runs/{run['id']}/artifacts?per_page=100")
        artifacts = listing.get("artifacts", []) if isinstance(listing, dict) else []
        if isinstance(listing, dict) and listing.get("total_count", len(artifacts)) > len(artifacts):
            raise HostedQualificationError("artifact listing is paginated; refusing ambiguous evidence")
        found = [item for item in artifacts if item.get("name") == ARTIFACT_NAME and not item.get("expired")]
        if len(found) != 1 or not isinstance(found[0].get("digest"), str):
            raise HostedQualificationError("expected one unexpired qualification artifact with digest")
        digest = found[0]["digest"]
        if not digest.startswith("sha256:") or not _SHA256.fullmatch(digest[7:]):
            raise HostedQualificationError("GitHub artifact ZIP digest is invalid")
        raw_zip = self._download_artifact(run["id"], found[0].get("id"), digest[7:])
        report_bytes = read_hosted_report_artifact(raw_zip, expected_zip_sha256=digest[7:])
        report = verify_hosted_report(
            report_bytes, expected_request_id=request["request_id"],
            expected_candidate_sha=request["candidate_sha"],
            expected_workflow_sha=request["workflow_sha"], expected_run_id=run["id"],
        )
        return {"report": report, "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                "artifact_sha256": digest[7:], "run_id": run["id"],
                "candidate_output_trusted": False, "promotion_eligible": False}
