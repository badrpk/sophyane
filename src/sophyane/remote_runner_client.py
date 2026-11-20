"""Sophyane client and evidence bridge for authorized remote deployment runners."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from datetime import datetime

from sophyane.remote_execution import (
    AuthenticationError, RequestAuthenticator, VERIFICATION_CHECKS, archive_project, sha256,
)


class RemoteRunnerError(RuntimeError):
    pass


class RemoteEvidenceRejected(RemoteRunnerError):
    pass


REQUIRED_CHECKS = {
    "docker-compose-deployment": {
        "REQ-008": {
            "compose-inspect", "compose-config", "compose-build", "compose-up", "api-health", "compose-health-status",
            "database-persistence-seed", "compose-api-restart", "api-after-restart",
            "compose-down-preserve-volume", "compose-up-after-restart",
            "database-persistence-check", "api-after-compose-restart", "postgres-volume-persistence",
            "compose-cleanup-remove-owned-volumes",
        },
    },
    "qemu-fastapi-deployment": {
        "REQ-014": {"qemu-overlay-create", "qemu-boot", "guest-fastapi-health-from-host",
                    "guest-api-auth-enforcement-from-host", "guest-9p-mounts",
                    "ubuntu-boot-complete", "guest-ssh-authenticated", "guest-fastapi-listening",
                    "guest-cloud-init-complete", "guest-dependencies-installed",
                    "guest-database-migrations", "guest-saas-tests"},
        "REQ-018": {"qemu-boot", "guest-cloud-init-complete", "guest-dependencies-installed",
                    "guest-9p-mounts", "ubuntu-boot-complete", "guest-ssh-authenticated",
                    "guest-dependencies-and-migration", "guest-database-migrations", "guest-saas-tests"},
    },
}
EXPECTED_REQUIREMENTS = {
    "docker-compose-deployment": ["REQ-008"],
    "qemu-fastapi-deployment": ["REQ-014", "REQ-018"],
}
EXPECTED_EXECUTION_CLASSES = {
    "docker-compose-deployment": "docker-host",
    "qemu-fastapi-deployment": "qemu-host",
}


class RemoteRunnerClient:
    def __init__(
        self, base_url: str, secret: bytes, runner_id: str, *, durable_store: Any,
        archive_dir: str | Path, ca_file: str | Path | None = None,
        allow_insecure_loopback: bool = False, request_timeout: float = 30,
    ) -> None:
        parsed = urlsplit(base_url)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (allow_insecure_loopback and parsed.scheme == "http" and loopback):
            raise ValueError("remote runner URLs must use HTTPS; HTTP is allowed only for loopback tests")
        if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("invalid runner base URL")
        if parsed.path not in {"", "/"}:
            raise ValueError("runner URL must not contain a path prefix")
        if not runner_id:
            raise ValueError("expected runner_id is required")
        self.base_url = base_url.rstrip("/")
        self.runner_id, self.store = runner_id, durable_store
        self.archive_dir = Path(archive_dir).resolve()
        self.archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.archive_dir, 0o700)
        self.auth = RequestAuthenticator(secret)
        self.timeout = request_timeout
        self.ssl_context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.allow_insecure_loopback = allow_insecure_loopback

    def _request(self, method: str, path: str, body: bytes = b"") -> tuple[int, bytes]:
        headers = self.auth.sign(method, path, body)
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=body if method in {"POST", "PUT"} else None,
                                         headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context)
        except urllib.error.HTTPError as error:
            response = error
        try:
            payload = response.read(160 * 1024 * 1024)
            signature = response.headers.get("X-Sophyane-Response-Signature", "")
            self.auth.verify_response(response.status, path, payload, signature)
            return int(response.status), payload
        finally:
            response.close()

    def _json_request(self, method: str, path: str, value: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() if value is not None else b""
        status, response = self._request(method, path, body)
        try:
            decoded = json.loads(response)
        except (ValueError, UnicodeError) as error:
            raise RemoteRunnerError("runner returned invalid JSON") from error
        if not 200 <= status < 300:
            raise RemoteRunnerError(f"runner HTTP {status}: {decoded.get('error', 'request failed')}")
        if not isinstance(decoded, dict):
            raise RemoteRunnerError("runner response is not an object")
        return decoded

    def submit(self, run_id: str, project: str | Path, kind: str) -> dict[str, Any]:
        if kind not in EXPECTED_REQUIREMENTS:
            raise ValueError("unsupported remote job kind")
        archive, source = archive_project(project)
        checkpoint_key = f"{run_id}:{kind}"
        prior = self.store.get("remote_deployment_jobs", checkpoint_key)
        if prior:
            if prior.get("source_sha256") != source["source_sha256"]:
                raise RemoteRunnerError("remote job already checkpointed for a different source snapshot")
            job_id = prior["job_id"]
            try:
                return self.status(job_id, checkpoint_key=checkpoint_key)
            except RemoteRunnerError as error:
                if "HTTP 404" not in str(error):
                    raise
                # The client may have checkpointed before a lost initial POST. The
                # stable job ID and server-side request digest make this retry safe.
        stable_id = hashlib.sha256(f"{run_id}\0{kind}\0{source['source_sha256']}".encode()).hexdigest()[:32]
        job_id = "job-" + stable_id
        manifest = {
            "job_id": job_id, "kind": kind,
            "requirement_ids": EXPECTED_REQUIREMENTS[kind],
            "source_sha256": source["source_sha256"], "archive_sha256": source["archive_sha256"],
            "verification_checks": VERIFICATION_CHECKS[kind],
        }
        archive_path = self.archive_dir / f"{job_id}.tar.gz"
        temporary = archive_path.with_suffix(".partial")
        temporary.write_bytes(archive)
        os.chmod(temporary, 0o600)
        temporary.replace(archive_path)
        checkpoint = {"run_id": run_id, "job_id": job_id, "kind": kind,
                      "requirement_ids": EXPECTED_REQUIREMENTS[kind],
                      "source_sha256": source["source_sha256"], "archive_sha256": source["archive_sha256"],
                      "archive_path": str(archive_path), "state": "SUBMITTING", "runner_id": self.runner_id}
        self.store.put("remote_deployment_jobs", checkpoint_key, checkpoint)
        body = {"manifest": manifest, "archive_b64": base64.b64encode(archive).decode("ascii")}
        response = self._json_request("POST", "/v1/jobs", body)
        self._save_checkpoint(checkpoint_key, {**checkpoint, "state": response.get("state", "QUEUED")})
        return response

    def _save_checkpoint(self, key: str, value: dict[str, Any]) -> None:
        self.store.put("remote_deployment_jobs", key, value)

    def status(self, job_id: str, *, checkpoint_key: str | None = None) -> dict[str, Any]:
        self._validate_job_id(job_id)
        response = self._json_request("GET", f"/v1/jobs/{job_id}")
        if checkpoint_key:
            prior = self.store.get("remote_deployment_jobs", checkpoint_key)
            if prior:
                self._save_checkpoint(checkpoint_key, {**prior, "state": response.get("state"), "updated_at": response.get("updated_at")})
        return response

    def cancel(self, job_id: str) -> dict[str, Any]:
        self._validate_job_id(job_id)
        return self._json_request("POST", f"/v1/jobs/{job_id}/cancel", {})

    def wait(self, job_id: str, *, poll_interval: float = 1, deadline_seconds: float = 1800,
             checkpoint_key: str | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            result = self.status(job_id, checkpoint_key=checkpoint_key)
            if result.get("state") in {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}:
                return result
            time.sleep(max(0, poll_interval))
        raise TimeoutError(f"remote job {job_id} did not finish within {deadline_seconds}s")

    def retrieve(self, job_id: str) -> tuple[dict[str, Any], dict[str, bytes]]:
        self._validate_job_id(job_id)
        status = self.status(job_id)
        result = status.get("result")
        if not isinstance(result, dict):
            raise RemoteRunnerError("remote job has no signed result")
        self.verify_result(result, require_trusted_environment=False)
        path = f"/v1/jobs/{job_id}/artifacts"
        response_status, raw_bundle = self._request("GET", path)
        if response_status != 200:
            raise RemoteRunnerError(f"artifact retrieval failed with HTTP {response_status}")
        if sha256(raw_bundle) != result.get("artifact_bundle_sha256"):
            raise AuthenticationError("artifact bundle hash does not match signed result")
        try:
            encoded = json.loads(raw_bundle)
            artifacts = {name: base64.b64decode(item["base64"], validate=True)
                         for name, item in encoded.items()}
        except (ValueError, KeyError, TypeError) as error:
            raise RemoteRunnerError("malformed artifact bundle") from error
        hashes = {name: sha256(data) for name, data in artifacts.items()}
        if hashes != result.get("artifacts"):
            raise AuthenticationError("artifact content hash does not match signed result")
        return result, artifacts

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        if not re.fullmatch(r"job-[a-f0-9]{8,64}", str(job_id)):
            raise ValueError("invalid remote job ID")

    def verify_result(self, result: dict[str, Any], *, expected_source_sha256: str | None = None,
                      require_trusted_environment: bool = True) -> None:
        if result.get("schema") != "sophyane.runner-result.v1":
            raise AuthenticationError("unsupported remote result schema")
        if result.get("runner_id") != self.runner_id:
            raise AuthenticationError("result runner identity mismatch")
        signature = result.get("signature")
        unsigned = dict(result)
        unsigned.pop("signature", None)
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        self.auth.verify_response(200, f"/v1/jobs/{result.get('job_id')}/result", canonical,
                                  signature, enforce_freshness=False)
        if expected_source_sha256 and result.get("source_sha256") != expected_source_sha256:
            raise AuthenticationError("result source digest mismatch")
        if not isinstance(result.get("finished_at"), str) or not isinstance(result.get("commands"), list):
            raise AuthenticationError("result lacks timestamp or command evidence")
        try:
            finished = datetime.fromisoformat(result["finished_at"].replace("Z", "+00:00"))
            started = datetime.fromisoformat(result["started_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError, KeyError) as error:
            raise AuthenticationError("result timestamps are invalid") from error
        if finished < started:
            raise AuthenticationError("result finished before it started")
        if result.get("status") not in {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}:
            raise AuthenticationError("invalid terminal execution status")
        if result.get("kind") not in EXPECTED_REQUIREMENTS or result.get("verification_checks") != VERIFICATION_CHECKS[result["kind"]]:
            raise AuthenticationError("result verification manifest is invalid")
        environment = result.get("environment")
        expected_class = EXPECTED_EXECUTION_CLASSES.get(result.get("kind"))
        if not isinstance(environment, dict) or environment.get("runner_id") != self.runner_id:
            raise AuthenticationError("result environment identity mismatch")
        if require_trusted_environment and (
            environment.get("execution_class") != expected_class or environment.get("real_execution") is not True
        ):
            raise RemoteEvidenceRejected("runner environment is not configured as a real authorized host")

    def verified_evidence_records(self, result: dict[str, Any], artifact_path: str) -> list[dict[str, Any]]:
        self.verify_result(result)
        if result.get("status") != "COMPLETED":
            raise RemoteEvidenceRejected("remote deployment did not complete successfully")
        kind = result["kind"]
        command_rows = result["commands"]
        by_label: dict[str, dict[str, Any]] = {}
        for row in command_rows:
            if isinstance(row, dict) and isinstance(row.get("label"), str):
                by_label[row["label"]] = row
        requirements = result.get("requirement_ids")
        if requirements != EXPECTED_REQUIREMENTS[kind]:
            raise AuthenticationError("result requirement binding does not match job kind")
        records = []
        for requirement_id in requirements:
            required = REQUIRED_CHECKS[kind][requirement_id]
            missing = required - set(by_label)
            failures = [label for label in required if label in by_label and (
                by_label[label].get("exit_code") != 0 or by_label[label].get("timed_out") or by_label[label].get("cancelled")
            )]
            for label in required & set(by_label):
                try:
                    datetime.fromisoformat(str(by_label[label]["timestamp"]).replace("Z", "+00:00"))
                except (ValueError, KeyError, TypeError):
                    failures.append(label)
            if missing or failures:
                raise RemoteEvidenceRejected(f"{requirement_id} checks incomplete; missing={sorted(missing)}, failed={sorted(failures)}")
            records.append({
                "requirement_id": requirement_id, "status": "PASS", "test_command":
                    f"authenticated remote {kind} job {result['job_id']} on runner {self.runner_id}",
                "exit_code": 0, "artifact_path": artifact_path,
                "timestamp": result["finished_at"],
                "summary": f"Remote {kind} checks passed on {self.runner_id}; signed result {result['signature']}",
            })
        return records

    def attach_to_runtime(self, runtime: Any, result: dict[str, Any], artifacts: dict[str, bytes]) -> dict[str, Any]:
        """Persist verified artifacts and reconcile with the existing root contract."""
        self.verify_result(result)
        if result.get("status") != "COMPLETED":
            raise RemoteEvidenceRejected("only successful remote jobs can attach PASS evidence")
        run_id = str(getattr(runtime, "_active_run_id", "") or "")
        checkpoint_key = f"{run_id}:{result['kind']}"
        checkpoint = self.store.get("remote_deployment_jobs", checkpoint_key) if run_id else None
        if not checkpoint or checkpoint.get("job_id") != result.get("job_id"):
            raise RemoteEvidenceRejected("result is not bound to this durable run's remote job checkpoint")
        if checkpoint.get("runner_id") != self.runner_id or checkpoint.get("source_sha256") != result.get("source_sha256"):
            raise AuthenticationError("remote result does not match its durable dispatch checkpoint")
        root = Path(runtime.workspace).resolve()
        _, current_source = archive_project(root)
        if current_source["source_sha256"] != result.get("source_sha256"):
            raise AuthenticationError("remote result was produced from a different project snapshot")
        evidence_dir = root
        for component in ("evidence", "remote-runs", result["job_id"]):
            evidence_dir = evidence_dir / component
            if evidence_dir.is_symlink():
                raise AuthenticationError("remote evidence directory cannot traverse a symlink")
            evidence_dir.mkdir(exist_ok=True)
            if not evidence_dir.is_dir():
                raise AuthenticationError("remote evidence path is not a directory")
        os.chmod(evidence_dir, 0o700)
        for name, data in artifacts.items():
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", name):
                raise AuthenticationError("unsafe artifact name")
            self._write_evidence_file(evidence_dir / name, data)
        result_path = evidence_dir / "signed-result.json"
        self._write_evidence_file(result_path, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
        records = self.verified_evidence_records(result, result_path.relative_to(root).as_posix())
        return runtime.integrate_independent_evidence(records)

    @staticmethod
    def _write_evidence_file(target: Path, content: bytes) -> None:
        if target.is_symlink():
            raise AuthenticationError("remote evidence file cannot be a symlink")
        if target.exists():
            if not target.is_file() or target.read_bytes() != content:
                raise AuthenticationError("existing remote evidence file differs from signed result")
            return
        temporary = target.with_name(target.name + ".partial")
        if temporary.exists() or temporary.is_symlink():
            raise AuthenticationError("remote evidence temporary path already exists")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
