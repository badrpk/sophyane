import hashlib
import io
import json
import zipfile

import pytest

from sophyane.ssee.remote.github_client import (
    GitHubSSEEClient,
    GitHubSSEEError,
    X70ApprovalRequired,
)
from sophyane.ssee.remote.verifier import verify_github_report


def _report_bytes(**overrides):
    report = {
        "schema_version": 1,
        "head_sha": "a" * 40,
        "run_id": 42,
        "workflow": ".github/workflows/ssee-verify.yml",
        "check_name": "SSEE offline QEMU verification",
        "conclusion": "success",
    }
    report.update(overrides)
    return json.dumps(report, sort_keys=True, separators=(",", ":")).encode()


def _zip_report(report, digest=None, extra=None):
    digest = digest or hashlib.sha256(report).hexdigest()
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("verification-report.json", report)
        archive.writestr("verification-report.sha256", digest)
        if extra:
            archive.writestr(extra, b"unexpected")
    return target.getvalue()


def test_verify_github_report_binds_digest_head_run_workflow_and_check():
    report = _report_bytes()
    result = verify_github_report(
        report_bytes=report,
        expected_report_sha256=hashlib.sha256(report).hexdigest(),
        expected_head_sha="a" * 40,
        expected_run_id=42,
        expected_workflow=".github/workflows/ssee-verify.yml",
        expected_check_name="SSEE offline QEMU verification",
    )
    assert result.accepted
    assert result.report_sha256 == hashlib.sha256(report).hexdigest()


@pytest.mark.parametrize("overrides", [
    {"head_sha": "b" * 40},
    {"run_id": 43},
    {"conclusion": "failure"},
    {"schema_version": 2},
])
def test_verify_github_report_rejects_wrong_binding_or_status(overrides):
    report = _report_bytes(**overrides)
    result = verify_github_report(
        report_bytes=report,
        expected_report_sha256=hashlib.sha256(report).hexdigest(),
        expected_head_sha="a" * 40,
        expected_run_id=42,
        expected_workflow=".github/workflows/ssee-verify.yml",
        expected_check_name="SSEE offline QEMU verification",
    )
    assert not result.accepted


def test_verify_github_report_rejects_digest_mismatch():
    result = verify_github_report(
        report_bytes=_report_bytes(), expected_report_sha256="0" * 64,
        expected_head_sha="a" * 40, expected_run_id=42,
        expected_workflow=".github/workflows/ssee-verify.yml",
        expected_check_name="SSEE offline QEMU verification",
    )
    assert not result.accepted
    assert "report digest mismatch" in result.reasons


def test_verify_github_report_rejects_duplicate_json_keys():
    report = b'{"schema_version":1,"schema_version":1}'
    result = verify_github_report(
        report_bytes=report, expected_report_sha256=hashlib.sha256(report).hexdigest(),
        expected_head_sha="a" * 40, expected_run_id=42,
        expected_workflow=".github/workflows/ssee-verify.yml",
        expected_check_name="SSEE offline QEMU verification",
    )
    assert not result.accepted


def test_report_zip_requires_exact_bounded_file_set():
    report = _report_bytes()
    parsed, digest = GitHubSSEEClient._read_report_zip(_zip_report(report))
    assert parsed == report
    assert digest == hashlib.sha256(report).hexdigest()
    with pytest.raises(GitHubSSEEError, match="exactly the report and digest"):
        GitHubSSEEClient._read_report_zip(_zip_report(report, extra="unexpected.txt"))


def test_x70_gate_halts_without_approval_and_rechecks_head():
    client = GitHubSSEEClient("owner", "repo", "test-token")
    client._api = lambda method, path, **kwargs: {"head": {"sha": "a" * 40}}
    evidence = {"run_id": 42, "report_sha256": "d" * 64,
                "report": {"head_sha": "a" * 40}}
    with pytest.raises(X70ApprovalRequired):
        client.request_x70_approval(
            pull_number=7, verified=evidence, approval_callback=lambda _: False)
    approved = client.request_x70_approval(
        pull_number=7, verified=evidence, approval_callback=lambda _: True)
    assert approved == {"pull_number": 7, "head_sha": "a" * 40,
                        "run_id": 42, "report_sha256": "d" * 64}


def test_x70_gate_rejects_changed_head():
    client = GitHubSSEEClient("owner", "repo", "test-token")
    client._api = lambda method, path, **kwargs: {"head": {"sha": "b" * 40}}
    with pytest.raises(GitHubSSEEError, match="head changed"):
        client.request_x70_approval(
            pull_number=7,
            verified={"run_id": 42, "report_sha256": "d" * 64,
                      "report": {"head_sha": "a" * 40}},
            approval_callback=lambda _: True,
        )
