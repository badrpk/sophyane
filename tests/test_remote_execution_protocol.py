from __future__ import annotations

import io
import tarfile

import pytest

from sophyane.remote_execution import (
    AuthenticationError,
    ReplayGuard,
    RequestAuthenticator,
    archive_project,
    extract_project_archive,
    validate_job_manifest,
    VERIFICATION_CHECKS,
)


def test_authentication_rejects_replayed_nonce(tmp_path):
    auth = RequestAuthenticator(b"k" * 32, clock=lambda: 1000)
    headers = auth.sign("POST", "/v1/jobs", b"{}", nonce="a" * 24)
    guard = ReplayGuard(tmp_path / "nonces.sqlite", clock=lambda: 1000)
    guard.verify("POST", "/v1/jobs", b"{}", headers, auth)
    with pytest.raises(AuthenticationError, match="replay"):
        guard.verify("POST", "/v1/jobs", b"{}", headers, auth)


def test_job_manifest_is_strict_and_names_fixed_executor():
    value = {
        "job_id": "job-12345678",
        "kind": "docker-compose-deployment",
        "requirement_ids": ["REQ-008"],
        "source_sha256": "a" * 64,
        "archive_sha256": "b" * 64,
        "verification_checks": VERIFICATION_CHECKS["docker-compose-deployment"],
    }
    assert validate_job_manifest(value)["job_id"] == value["job_id"]
    with pytest.raises(ValueError, match="unsupported job kind"):
        validate_job_manifest({**value, "kind": "shell"})
    with pytest.raises(ValueError, match="requirement"):
        validate_job_manifest({**value, "requirement_ids": ["REQ-999"]})


def test_project_archive_excludes_secrets_and_is_extractable(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("ok", encoding="utf-8")
    (source / ".env").write_text("secret", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".venv" / "secret").write_text("secret", encoding="utf-8")
    (source / ".sophyane-verify-venv").mkdir()
    (source / ".sophyane-verify-venv" / "large-secret").write_text("secret", encoding="utf-8")
    archive, manifest = archive_project(source)
    archive_again, _ = archive_project(source)
    assert archive_again == archive
    assert "app.py" in manifest["files"]
    assert ".env" not in manifest["files"]
    assert not any("sophyane-verify-venv" in name for name in manifest["files"])
    target = tmp_path / "target"
    extract_project_archive(archive, target)
    assert (target / "app.py").read_text() == "ok"
    assert not (target / ".env").exists()


def test_checkpoint_generated_traceability_and_remote_results_do_not_change_source_digest(tmp_path):
    (tmp_path / "app.py").write_text("app = True\n", encoding="utf-8")
    _, original = archive_project(tmp_path)
    (tmp_path / "TRACEABILITY.md").write_text("updated statuses\n", encoding="utf-8")
    remote = tmp_path / "evidence" / "remote-runs" / ("job-" + "a" * 32)
    remote.mkdir(parents=True)
    (remote / "signed-result.json").write_text("signed evidence\n", encoding="utf-8")
    _, updated = archive_project(tmp_path)
    assert updated["source_sha256"] == original["source_sha256"]


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../../escape"])
def test_extractor_rejects_traversal(tmp_path, name):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        item = tarfile.TarInfo(name)
        item.size = 1
        archive.addfile(item, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="unsafe archive path"):
        extract_project_archive(buffer.getvalue(), tmp_path / "out")


def test_extractor_rejects_symlinks_and_duplicate_paths(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    with pytest.raises(ValueError, match="unsupported archive entry"):
        extract_project_archive(buffer.getvalue(), tmp_path / "out")

    duplicate = io.BytesIO()
    with tarfile.open(fileobj=duplicate, mode="w:gz") as archive:
        for value in (b"one", b"two"):
            item = tarfile.TarInfo("same.txt")
            item.size = len(value)
            archive.addfile(item, io.BytesIO(value))
    with pytest.raises(ValueError, match="duplicate archive path"):
        extract_project_archive(duplicate.getvalue(), tmp_path / "duplicate")
