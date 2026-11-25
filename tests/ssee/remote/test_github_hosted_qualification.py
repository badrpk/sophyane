import hashlib
import json
from pathlib import Path
import zipfile
from io import BytesIO

import pytest

from sophyane.ssee.remote.github_hosted import (
    ARTIFACT_NAME,
    IMAGE,
    WORKFLOW_PATH,
    GitHubHostedQualificationClient,
    GitHubSSEEError,
    HostedQualificationError,
    QualificationRequest,
    build_candidate_command,
    verify_hosted_report,
)
from tools.ssee_hosted_qualification import candidate_path_for


def _report(**overrides):
    value = {
        "schema_version": 1,
        "request_id": "9e32ca2c-73bc-44fd-a0be-f2b3a355416a",
        "candidate_sha": "a" * 40,
        "workflow_sha": "b" * 40,
        "workflow_path": ".github/workflows/ssee-hosted-qualification.yml",
        "run_id": 123,
        "execution_class": "python_jsonl_v1",
        "fixture": "pass",
        "candidate_status": "accepted",
        "expected_fixture_outcome_observed": True,
        "isolation": {
            "runner_os": "Linux",
            "runner_arch": "X64",
            "runner_kind": "github-hosted-ephemeral-vm",
            "runner_image": "ubuntu-24.04",
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
        },
        "tests": {"passed": 4, "failed": 0, "timed_out": 0},
        "candidate_file_sha256": "e" * 64,
        "case_evidence": [{"status": "passed", "passed": True, "timed_out": False,
                           "output_sha256": "d" * 64} for _ in range(4)],
        "output_sha256": "d" * 64,
    }
    value.update(overrides)
    return value


def test_report_verification_binds_candidate_workflow_run_and_observed_isolation():
    raw = json.dumps(_report(), sort_keys=True, separators=(",", ":")).encode()
    verified = verify_hosted_report(
        raw, expected_request_id="9e32ca2c-73bc-44fd-a0be-f2b3a355416a",
        expected_candidate_sha="a" * 40, expected_workflow_sha="b" * 40,
        expected_run_id=123,
    )
    assert verified["candidate_status"] == "accepted"


@pytest.mark.parametrize("change", [
    {"candidate_sha": "e" * 40},
    {"workflow_sha": "f" * 40},
    {"run_id": 124},
    {"workflow_path": ".github/workflows/untrusted.yml"},
    {"isolation": {"network_mode": "bridge"}},
])
def test_report_rejects_wrong_identity_or_missing_isolation(change):
    with pytest.raises(HostedQualificationError):
        verify_hosted_report(
            json.dumps(_report(**change)).encode(),
            expected_request_id="9e32ca2c-73bc-44fd-a0be-f2b3a355416a",
            expected_candidate_sha="a" * 40, expected_workflow_sha="b" * 40,
            expected_run_id=123,
        )


def test_duplicate_json_keys_are_rejected():
    raw = b'{"candidate_sha":"' + b"a" * 40 + b'","candidate_sha":"' + b"a" * 40 + b'"}'
    with pytest.raises(HostedQualificationError):
        verify_hosted_report(raw, expected_request_id="r", expected_candidate_sha="a" * 40,
                             expected_workflow_sha="b" * 40, expected_run_id=123)


def test_builtin_fixtures_are_read_from_trusted_workflow_checkout(tmp_path):
    candidate = tmp_path / "candidate"
    trusted = tmp_path / "trusted"
    (candidate / "qualification_fixtures").mkdir(parents=True)
    (trusted / "qualification_fixtures").mkdir(parents=True)
    (candidate / "qualification_fixtures/pass.py").write_text("# candidate-controlled")
    (trusted / "qualification_fixtures/pass.py").write_text("# trusted")
    assert candidate_path_for(candidate, "pass", trusted).read_text() == "# trusted"


def test_candidate_report_status_and_fixture_counts_are_consistent():
    value = _report(candidate_status="rejected", tests={"passed": 3, "failed": 1, "timed_out": 0},
                    case_evidence=[{"status": "passed" if index < 3 else "test_failed",
                                    "passed": index < 3, "timed_out": False,
                                    "output_sha256": "d" * 64} for index in range(4)])
    with pytest.raises(HostedQualificationError):
        verify_hosted_report(json.dumps(value).encode(),
            expected_request_id="9e32ca2c-73bc-44fd-a0be-f2b3a355416a",
            expected_candidate_sha="a" * 40, expected_workflow_sha="b" * 40,
            expected_run_id=123)


def test_workflow_is_dispatch_only_and_uses_fixed_trusted_workflow_source():
    workflow = Path(__file__).parents[3] / ".github/workflows/ssee-hosted-qualification.yml"
    source = workflow.read_text()
    assert "workflow_dispatch:" in source
    assert "pull_request_target" not in source
    assert "permissions:\n  contents: read" in source
    assert "persist-credentials: false" in source
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in source
    assert "actions/upload-artifact@65c4c4a1ddee5b72f698fdd19549f0f0fb45cf08" in source


def test_candidate_container_command_has_no_network_or_host_credentials():
    command = build_candidate_command(
        docker="docker", image="example/image@sha256:" + "c" * 64,
        candidate_file="/tmp/candidate.py", container_name="ssee-test-123",
    )
    joined = " ".join(command)
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--pids-limit=32" in command
    assert "--memory=268435456" in command
    assert "--cpus=0.5" in command
    assert "--security-opt=no-new-privileges" in command
    assert not any("GITHUB_TOKEN" in part or "SSH_AUTH_SOCK" in part for part in command)
    assert "python" in joined


def test_qualification_request_requires_immutable_commit_and_uuid():
    request = QualificationRequest(candidate_sha="a" * 40)
    assert len(request.request_id) == 36
    with pytest.raises(ValueError):
        QualificationRequest(candidate_sha="main")


def test_artifact_report_integrity_checks_expected_digest():
    report = json.dumps(_report(), sort_keys=True, separators=(",", ":")).encode()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("qualification-report.json", report)
        archive.writestr("qualification-report.sha256", hashlib.sha256(report).hexdigest())
    from sophyane.ssee.remote.github_hosted import read_hosted_report_artifact
    assert read_hosted_report_artifact(buffer.getvalue()) == report
    with pytest.raises(HostedQualificationError):
        read_hosted_report_artifact(buffer.getvalue(), expected_zip_sha256="0" * 64)


def _client():
    return GitHubHostedQualificationClient("badrpk", "sophyane", "test-token")


def _run(request_id, *, status="completed", conclusion="success"):
    return {
        "id": 123,
        "display_title": "SSEE hosted qualification " + request_id,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": "b" * 40,
        "path": WORKFLOW_PATH,
        "status": status,
        "conclusion": conclusion,
    }


def test_dispatch_requires_protected_main_and_pinned_workflow_sha():
    client = _client()
    calls = []

    def api(method, path, *, body=None):
        calls.append((method, path, body))
        if path == "/branches/main/protection":
            return {"required_pull_request_reviews": {"required_approving_review_count": 1},
                    "enforce_admins": {"enabled": True}}
        if path == "/git/ref/heads/main":
            return {"object": {"sha": "b" * 40}}
        if method == "POST":
            return None
        raise AssertionError(path)

    client._api = api
    request = client.dispatch("a" * 40, expected_workflow_sha="b" * 40, fixture="pass")
    assert request["candidate_sha"] == "a" * 40
    assert request["workflow_sha"] == "b" * 40
    dispatch = calls[-1]
    assert dispatch[0] == "POST"
    assert dispatch[2]["ref"] == "main"
    assert dispatch[2]["inputs"]["candidate_sha"] == "a" * 40
    assert dispatch[2]["inputs"]["request_id"] == request["request_id"]


def test_dispatch_refuses_unprotected_main_before_workflow_dispatch():
    client = _client()
    calls = []

    def api(method, path, *, body=None):
        calls.append((method, path))
        if path == "/branches/main/protection":
            raise GitHubSSEEError("HTTP 404")
        raise AssertionError("must fail before other calls")

    client._api = api
    with pytest.raises(HostedQualificationError, match="not protected"):
        client.dispatch("a" * 40, expected_workflow_sha="b" * 40)
    assert calls == [("GET", "/branches/main/protection")]


def test_status_polling_binds_run_to_request_and_trusted_workflow_sha():
    client = _client()
    request_id = "9e32ca2c-73bc-44fd-a0be-f2b3a355416a"
    client._api = lambda method, path, **kwargs: {"total_count": 1,
        "workflow_runs": [_run(request_id)]}
    result = client.status({"request_id": request_id, "workflow_sha": "b" * 40},
                           timeout_seconds=1, poll_seconds=1)
    assert result["id"] == 123


def test_status_rejects_run_from_untrusted_workflow_ref():
    client = _client()
    request_id = "9e32ca2c-73bc-44fd-a0be-f2b3a355416a"
    wrong = _run(request_id)
    wrong["head_sha"] = "c" * 40
    client._api = lambda method, path, **kwargs: {"workflow_runs": [wrong]}
    with pytest.raises(HostedQualificationError, match="pinned trusted definition"):
        client.status({"request_id": request_id, "workflow_sha": "b" * 40},
                      timeout_seconds=1, poll_seconds=1)


def test_cancel_targets_only_the_exact_pending_request_run():
    client = _client()
    request_id = "9e32ca2c-73bc-44fd-a0be-f2b3a355416a"
    calls = []
    pending = _run(request_id, status="in_progress", conclusion=None)

    def api(method, path, *, body=None):
        calls.append((method, path))
        if method == "GET":
            return {"workflow_runs": [pending]}
        return None

    client._api = api
    result = client.cancel({"request_id": request_id, "workflow_sha": "b" * 40})
    assert result == {"run_id": 123, "status": "cancel_requested", "cancelled": True}
    assert calls[-1] == ("POST", "/actions/runs/123/cancel")


def test_retrieve_evidence_checks_artifact_provenance_and_report_bindings():
    client = _client()
    request_id = "9e32ca2c-73bc-44fd-a0be-f2b3a355416a"
    report = json.dumps(_report(), sort_keys=True, separators=(",", ":")).encode()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("qualification-report.json", report)
        archive.writestr("qualification-report.sha256", hashlib.sha256(report).hexdigest())
    raw_zip = buffer.getvalue()
    artifact_digest = hashlib.sha256(raw_zip).hexdigest()
    run = _run(request_id)

    def api(method, path, *, body=None):
        if "/runs?" in path:
            return {"total_count": 1, "workflow_runs": [run]}
        if path == "/actions/runs/123/artifacts?per_page=100":
            return {"total_count": 1, "artifacts": [{
                "id": 991, "name": ARTIFACT_NAME, "expired": False,
                "digest": "sha256:" + artifact_digest,
            }]}
        raise AssertionError(path)

    client._api = api
    client._download_artifact = lambda run_id, artifact_id, digest: raw_zip
    evidence = client.retrieve_evidence(
        {"request_id": request_id, "candidate_sha": "a" * 40,
         "workflow_sha": "b" * 40}, run)
    assert evidence["report"]["candidate_status"] == "accepted"
    assert evidence["candidate_output_trusted"] is False
    assert evidence["promotion_eligible"] is False
