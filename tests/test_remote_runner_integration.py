from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from sophyane.graph_runtime import DurableStore
from sophyane.remote_runner_client import (
    AuthenticationError,
    RemoteEvidenceRejected,
    RemoteRunnerClient,
)
from sophyane.remote_runner_service import RunnerService, build_server


class RunningRunner:
    def __init__(self, service):
        self.service = service
        self.server = build_server(service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.service.close()


def test_real_http_lifecycle_signed_artifacts_resume_and_fixture_stays_blocked(tmp_path):
    secret = b"integration-key-with-at-least-32-bytes"
    calls = []

    def docker_fixture(source, manifest, cancel):
        calls.append(manifest["job_id"])
        return {
            "passed": True,
            "commands": [{"label": "fixture-only", "exit_code": 0}],
            "artifacts": {"fixture.txt": b"test runner output"},
        }

    project = tmp_path / "project"
    project.mkdir()
    (project / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (project / "main.py").write_text("print('application')\n", encoding="utf-8")
    durable = DurableStore(tmp_path / "client-checkpoint.sqlite")

    first = RunningRunner(RunnerService(
        tmp_path / "runner", "fixture-runner", secret,
        {"docker-compose-deployment": docker_fixture},
        environment_identity={"runner_id": "fixture-runner", "execution_class": "integration-fixture", "real_execution": False},
    ))
    client = RemoteRunnerClient(first.url, secret, "fixture-runner", durable_store=durable,
                                archive_dir=tmp_path / "archive", allow_insecure_loopback=True)
    try:
        submitted = client.submit("fixture-run", project, "docker-compose-deployment")
        job_id = submitted["job_id"]
        finished = client.wait(job_id, poll_interval=0.01, deadline_seconds=5,
                               checkpoint_key="fixture-run:docker-compose-deployment")
        assert finished["state"] == "COMPLETED"
        result, artifacts = client.retrieve(job_id)
        assert result["status"] == "COMPLETED"
        assert isinstance(result.get("signature"), str) and result["signature"]
        client.verify_result(
            result, expected_source_sha256=durable.get(
                "remote_deployment_jobs", "fixture-run:docker-compose-deployment"
            )["source_sha256"],
            require_trusted_environment=False,
        )
        assert result["source_sha256"] == durable.get(
            "remote_deployment_jobs", "fixture-run:docker-compose-deployment"
        )["source_sha256"]
        assert artifacts["fixture.txt"] == b"test runner output"
        tampered = dict(result)
        tampered["source_sha256"] = "0" * 64
        with pytest.raises(AuthenticationError, match="signature"):
            client.verify_result(tampered, require_trusted_environment=False)
        with pytest.raises(RemoteEvidenceRejected, match="not configured as a real authorized host"):
            client.verified_evidence_records(result, "evidence/result.json")
    finally:
        first.close()

    # A restarted server preserves the completed job; polling it does not replay the executor.
    second = RunningRunner(RunnerService(
        tmp_path / "runner", "fixture-runner", secret,
        {"docker-compose-deployment": docker_fixture},
        environment_identity={"runner_id": "fixture-runner", "execution_class": "integration-fixture", "real_execution": False},
    ))
    try:
        resumed = RemoteRunnerClient(second.url, secret, "fixture-runner", durable_store=durable,
                                     archive_dir=tmp_path / "archive", allow_insecure_loopback=True)
        assert resumed.status(job_id)["state"] == "COMPLETED"
        assert resumed.submit("fixture-run", project, "docker-compose-deployment")["job_id"] == job_id
        assert calls == [job_id]
    finally:
        second.close()


def test_authenticated_http_cancel_stops_a_running_job(tmp_path):
    secret = b"cancellation-test-key-at-least-32-bytes"
    started = threading.Event()

    def blocking_executor(source, manifest, cancel):
        started.set()
        cancel.wait(3)
        return {"passed": not cancel.is_set(), "commands": [{"label": "cancel-check", "exit_code": 1}]}

    project = tmp_path / "project"
    project.mkdir()
    (project / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    runner = RunningRunner(RunnerService(
        tmp_path / "runner-state", "cancel-fixture", secret,
        {"docker-compose-deployment": blocking_executor},
        environment_identity={"runner_id": "cancel-fixture", "execution_class": "integration-fixture", "real_execution": False},
    ))
    client = RemoteRunnerClient(runner.url, secret, "cancel-fixture",
                                durable_store=DurableStore(tmp_path / "cancel.sqlite"),
                                archive_dir=tmp_path / "cancel-archive", allow_insecure_loopback=True)
    try:
        submitted = client.submit("cancel-run", project, "docker-compose-deployment")
        assert started.wait(1)
        client.cancel(submitted["job_id"])
        final = client.wait(submitted["job_id"], poll_interval=0.01, deadline_seconds=5)
        assert final["state"] == "CANCELLED"
    finally:
        runner.close()


def test_remote_url_requires_tls_except_loopback_test_mode(tmp_path):
    store = DurableStore(tmp_path / "db.sqlite")
    with pytest.raises(ValueError, match="HTTPS"):
        RemoteRunnerClient("http://runner.example:9000", b"k" * 32, "runner", durable_store=store,
                           archive_dir=tmp_path / "archive", allow_insecure_loopback=True)
