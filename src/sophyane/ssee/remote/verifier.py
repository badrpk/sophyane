"""Independent checks use host observations; guest-reported status is untrusted."""
from dataclasses import dataclass
import hashlib
import json
import re

@dataclass(frozen=True)
class VerifiedHostResult:
    accepted: bool
    reasons: tuple[str,...]
    artifact_sha256: str | None

def verify_host_result(*, expected_candidate_sha256, observed_candidate_sha256, artifact, qemu_seccomp, cgroup_limits, network_none, cleanup_complete, guest_report=None, max_artifact_bytes=1024*1024):
    reasons=[]
    if qemu_seccomp!=2: reasons.append("host did not observe QEMU Seccomp=2")
    if not isinstance(cgroup_limits,dict) or any(cgroup_limits.get(k) in (None,"max","infinity") for k in ("cpu.max","memory.max","pids.max")): reasons.append("finite per-job cgroup limits not observed")
    if network_none is not True: reasons.append("guest network isolation not observed")
    if cleanup_complete is not True: reasons.append("job cleanup incomplete")
    if not isinstance(artifact,bytes): reasons.append("artifact missing or invalid")
    elif len(artifact)>max_artifact_bytes: reasons.append("artifact exceeds host output cap")
    if observed_candidate_sha256!=expected_candidate_sha256: reasons.append("host-observed candidate digest mismatch")
    digest=hashlib.sha256(artifact).hexdigest() if isinstance(artifact,bytes) else None
    # Guest claims are deliberately not evidence of these host facts.
    return VerifiedHostResult(not reasons,tuple(reasons),digest)


@dataclass(frozen=True)
class VerifiedGitHubReport:
    """Integrity and identity result for a GitHub artifact report.

    This verifies bytes and bindings only. It does not attest to the GitHub
    runner, QEMU, or any security controls described by the report.
    """
    accepted: bool
    reasons: tuple[str, ...]
    report_sha256: str | None
    report: dict | None


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def verify_github_report(*, report_bytes, expected_report_sha256,
                         expected_head_sha, expected_run_id,
                         expected_workflow, expected_check_name,
                         max_report_bytes=1024 * 1024):
    """Verify a bounded report's digest and its exact GitHub run bindings."""
    reasons = []
    digest = None
    report = None
    if not isinstance(report_bytes, bytes) or len(report_bytes) > max_report_bytes:
        reasons.append("report missing or exceeds size limit")
    else:
        digest = hashlib.sha256(report_bytes).hexdigest()
        if not isinstance(expected_report_sha256, str) or not _SHA256.fullmatch(expected_report_sha256):
            reasons.append("expected report digest is invalid")
        elif digest != expected_report_sha256:
            reasons.append("report digest mismatch")
        try:
            def reject_duplicate_keys(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate JSON key")
                    result[key] = value
                return result
            report = json.loads(report_bytes.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
            if not isinstance(report, dict):
                raise ValueError("report root must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            report = None
            reasons.append("report is not valid UTF-8 JSON object")
    if report is not None:
        expected = {
            "head_sha": expected_head_sha,
            "run_id": expected_run_id,
            "workflow": expected_workflow,
            "check_name": expected_check_name,
        }
        for key, value in expected.items():
            if report.get(key) != value:
                reasons.append(f"report {key} binding mismatch")
        if report.get("conclusion") != "success":
            reasons.append("report conclusion is not success")
        if report.get("schema_version") != 1:
            reasons.append("unsupported report schema")
    return VerifiedGitHubReport(not reasons, tuple(reasons), digest, report)
