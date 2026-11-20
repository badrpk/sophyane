from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
import time

from sophyane.remote_execution import VERIFICATION_CHECKS, archive_project
from sophyane.remote_runner_service import RunnerService


def _request(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("app = True\n", encoding="utf-8")
    archive, source = archive_project(project)
    manifest = {
        "job_id": "job-" + "a" * 32,
        "kind": "docker-compose-deployment",
        "requirement_ids": ["REQ-008"],
        "source_sha256": source["source_sha256"],
        "archive_sha256": source["archive_sha256"],
        "verification_checks": VERIFICATION_CHECKS["docker-compose-deployment"],
    }
    return {"manifest": manifest, "archive_b64": base64.b64encode(archive).decode()}


def test_job_submission_is_idempotent_and_result_contains_hashed_artifacts(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def executor(source, manifest, cancel):
        started.set()
        release.wait(2)
        return {"passed": True, "commands": [{"label": "fixture", "exit_code": 0}],
                "artifacts": {"result.json": b"fixture-output"}}

    service = RunnerService(tmp_path / "state", "fixture", b"x" * 32,
                            {"docker-compose-deployment": executor})
    body = _request(tmp_path)
    submitted = service.submit(body)
    assert submitted["state"] in {"QUEUED", "RUNNING"}
    assert started.wait(1)
    assert service.submit(body)["job_id"] == submitted["job_id"]
    release.set()
    for _ in range(100):
        status = service.get(submitted["job_id"])
        if status["state"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.02)
    assert status["state"] == "COMPLETED"
    assert status["result"]["artifacts"]["result.json"]
    assert service.artifact(submitted["job_id"])
    service.close()


def test_job_id_cannot_be_reused_for_different_archive(tmp_path):
    service = RunnerService(tmp_path / "state", "fixture", b"x" * 32,
                            {"docker-compose-deployment": lambda *_: {"passed": True}})
    body = _request(tmp_path)
    service.submit(body)
    changed = {**body, "archive_b64": base64.b64encode(b"other archive").decode()}
    try:
        service.submit(changed)
    except ValueError as error:
        assert "hash" in str(error)
    else:
        raise AssertionError("altered archive was accepted")
    service.close()


def test_cancel_signals_running_executor_and_persists_cancelled_state(tmp_path):
    started = threading.Event()

    def executor(source, manifest, cancel):
        started.set()
        cancel.wait(3)
        return {"passed": not cancel.is_set(), "commands": [{"label": "cancelled", "exit_code": 1}],
                "error": "cancelled"}

    service = RunnerService(tmp_path / "state", "fixture", b"x" * 32,
                            {"docker-compose-deployment": executor})
    request = _request(tmp_path)
    submitted = service.submit(request)
    assert started.wait(1)
    service.cancel(submitted["job_id"])
    for _ in range(100):
        status = service.get(submitted["job_id"])
        if status["state"] == "CANCELLED":
            break
        time.sleep(0.02)
    assert status["state"] == "CANCELLED"
    service.close()


def test_restart_resumes_queued_job_but_marks_inflight_job_interrupted(tmp_path):
    state_root = tmp_path / "state"
    initial = RunnerService(state_root, "fixture", b"x" * 32,
                            {"docker-compose-deployment": lambda *_: {"passed": True}})
    initial.close()
    request = _request(tmp_path)
    manifest = request["manifest"]
    canonical_request = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    request_hash = hashlib.sha256(canonical_request).hexdigest()
    now = time.time()
    with sqlite3.connect(state_root / "runner.sqlite") as db:
        db.execute("INSERT INTO jobs(job_id,request_hash,manifest,state,created,updated,request) VALUES(?,?,?,?,?,?,?)",
                   (manifest["job_id"], request_hash, json.dumps(manifest), "QUEUED", now, now,
                    json.dumps(request, sort_keys=True).encode()))
        inflight_id = "job-" + "c" * 32
        db.execute("INSERT INTO jobs(job_id,request_hash,manifest,state,created,updated) VALUES(?,?,?,?,?,?)",
                   (inflight_id, "f" * 64, json.dumps({**manifest, "job_id": inflight_id}),
                    "RUNNING", now, now))

    calls = []
    recovered = RunnerService(state_root, "fixture", b"x" * 32,
                              {"docker-compose-deployment": lambda *_: calls.append("executed") or {"passed": True}})
    for _ in range(100):
        queued_status = recovered.get(manifest["job_id"])
        if queued_status["state"] == "COMPLETED":
            break
        time.sleep(0.02)
    assert queued_status["state"] == "COMPLETED"
    assert recovered.get(inflight_id)["state"] == "INTERRUPTED"
    assert calls == ["executed"]
    recovered.close()
