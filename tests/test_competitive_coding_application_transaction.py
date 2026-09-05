from __future__ import annotations

import ast
import base64
import fcntl
import hashlib
import json
import multiprocessing
import os
import subprocess
import time
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

import sophyane.competitive_coding_application_transaction as transaction
import sophyane.competitive_coding_approval as approval
from sophyane.competitive_coding_phase2 import CompetitiveEvaluationCandidate, CompetitiveEvaluationResult
from sophyane.evolution.trusted_supplemental_executor import TrustedSupplementalEvidence
from sophyane.scoped_candidate_diff import candidate_diff_for_paths


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: str) -> str:
    return digest_bytes(value.encode())


def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("VALUE = 1\n")
    (repo / "other.txt").write_text("other\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo


def make_patch(repo: Path) -> str:
    target = repo / "app.py"
    original = target.read_bytes()
    target.write_text("VALUE = 2\n")
    patch = git(repo, "diff", "--binary", "HEAD", "--", "app.py") + "\n"
    target.write_bytes(original)
    return patch


def make_patch_for_paths(repo: Path, replacements: dict[str, bytes]) -> str:
    originals = {relative: (repo / relative).read_bytes() for relative in replacements}
    try:
        for relative, content in replacements.items():
            (repo / relative).write_bytes(content)
        return git(repo, "diff", "--binary", "HEAD", "--", *replacements) + "\n"
    finally:
        for relative, content in originals.items():
            (repo / relative).write_bytes(content)


def evidence() -> TrustedSupplementalEvidence:
    return TrustedSupplementalEvidence(
        family="targeted", challenge_id="c1", evaluator_identity="judge",
        test_path="tests/red_queen/test_targeted_supplemental.py", executed=True,
        passed=True, returncode=0, timed_out=False, elapsed_seconds=.1,
        stdout="ok", stderr="", rejection_reason=None,
    )


def candidate(
    repo: Path, patch: str | None = None, changed_paths: tuple[str, ...] = ("app.py",),
) -> CompetitiveEvaluationCandidate:
    patch = make_patch(repo) if patch is None else patch
    return CompetitiveEvaluationCandidate(
        candidate_id="only", proposal_valid=True, proposal_rejection_reason="",
        evaluation_status="PASS", evaluation_message="ok", changed_paths=changed_paths,
        validators=("tests",), passed=True, trusted_status="PASS", trusted_passed=True,
        trusted_evidence=(evidence(),), patch=patch, patch_sha256=digest(patch),
        source_head=git(repo, "rev-parse", "HEAD"),
    )


def evaluation(repo: Path, item: CompetitiveEvaluationCandidate) -> CompetitiveEvaluationResult:
    baseline = candidate_diff_for_paths(repo, item.changed_paths)
    return CompetitiveEvaluationResult(
        objective="repair", repository=repo.resolve(), target_name="sophyane",
        baseline_paths=item.changed_paths, baseline_patch=baseline, txq_policy=None,
        candidates=(item,), status="fail_closed",
        missing_boundary="trusted_candidate_ranking_and_approval", winner=None,
        source_head=git(repo, "rev-parse", "HEAD"), baseline_patch_sha256=digest(baseline),
    )


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch):
    hitl_dir = tmp_path / "hitl"
    queue = hitl_dir / "queue.json"
    monkeypatch.setattr(approval.hitl, "HITL_DIR", hitl_dir)
    monkeypatch.setattr(approval.hitl, "QUEUE", queue)
    return tmp_path / "transactions", queue


def approved(tmp_path: Path):
    repo = fixture_repo(tmp_path)
    value = evaluation(repo, candidate(repo))
    request = approval.request_competitive_approval(value)
    approval.hitl.resolve(request.request_id, approve=True)
    return repo, value, request


def snapshot(repo: Path):
    files = {path.relative_to(repo).as_posix(): path.read_bytes() for path in repo.rglob("*")
             if path.is_file() and ".git" not in path.relative_to(repo).parts}
    modes = {path.relative_to(repo).as_posix(): path.lstat().st_mode & 0o7777 for path in repo.rglob("*")
             if path.is_file() and ".git" not in path.relative_to(repo).parts}
    return git(repo, "rev-parse", "HEAD"), git_bytes(repo, "status", "--porcelain=v1", "-z"), files, modes


def manifest(repo: Path) -> str:
    mapping = {path: digest_bytes(content) for path, content in snapshot(repo)[2].items()}
    canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return digest(canonical)


def integrity(repo: Path, excluded: frozenset[str] = frozenset()) -> str:
    _, _, files, modes = snapshot(repo)
    mapping = {
        path: {"sha256": digest_bytes(content), "filesystem_mode": modes[path]}
        for path, content in files.items() if path not in excluded
    }
    canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return digest(canonical)


def test_real_preparation_has_exact_bindings_and_snapshots(tmp_path: Path, isolated) -> None:
    directory, queue = isolated
    repo, value, request = approved(tmp_path)
    plan = transaction.prepare_competitive_application(value, request.request_id)
    before_repo, before_queue = snapshot(repo), queue.read_bytes()
    prepared = transaction.prepare_competitive_application_transaction(
        value, request.request_id, transaction_dir=directory,
    )
    assert prepared.state == "prepared"
    assert tuple(transaction.CompetitiveApplicationFileSnapshot.__dataclass_fields__) == (
        "path", "mode", "filesystem_mode", "sha256", "content_base64",
        "expected_filesystem_mode", "expected_sha256", "expected_content_base64",
    )
    assert tuple(transaction.CompetitiveApplicationTransaction.__dataclass_fields__)[-3:] == (
        "repository_integrity_sha256", "unaffected_repository_integrity_sha256",
        "unaffected_status_base64",
    )
    for field in ("request_id", "approval_digest", "approval_payload", "repository", "source_head",
                  "baseline_patch_sha256", "candidate_id", "candidate_patch", "candidate_patch_sha256", "changed_paths"):
        assert getattr(prepared, field) == getattr(plan, field)
    assert base64.b64decode(prepared.repository_status_base64) == before_repo[1]
    assert prepared.repository_manifest_sha256 == manifest(repo)
    assert prepared.repository_integrity_sha256 == integrity(repo)
    assert prepared.unaffected_repository_integrity_sha256 == integrity(
        repo, frozenset({"app.py"}),
    )
    assert base64.b64decode(prepared.unaffected_status_base64) == b""
    assert prepared.files == (transaction.CompetitiveApplicationFileSnapshot(
        "app.py", 100644, before_repo[3]["app.py"], digest_bytes(b"VALUE = 1\n"), base64.b64encode(b"VALUE = 1\n").decode(),
        before_repo[3]["app.py"], digest_bytes(b"VALUE = 2\n"),
        base64.b64encode(b"VALUE = 2\n").decode(),
    ),)
    with pytest.raises(FrozenInstanceError):
        prepared.state = "changed"
    with pytest.raises(FrozenInstanceError):
        prepared.files[0].mode = 0
    assert snapshot(repo) == before_repo and queue.read_bytes() == before_queue


def test_unaffected_status_uses_literal_top_level_exclusions(
    tmp_path: Path, monkeypatch,
) -> None:
    repo = fixture_repo(tmp_path)
    excluded = (":colon", "glob*.txt", "bracket[abc].txt", "space name.txt",
                "tab\tname.txt", "unicodé.txt", "-leading-dash.txt")
    unaffected = ("globSAFE.txt", "ordinary.txt")
    for name in (*excluded, *unaffected):
        (repo / name).write_bytes(b"before\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "adversarial paths")
    for name in (*excluded, *unaffected):
        (repo / name).write_bytes(b"after\n")
    calls = []
    original = transaction._git

    def recording(repository, *arguments):
        calls.append(arguments)
        return original(repository, *arguments)

    monkeypatch.setattr(transaction, "_git", recording)
    raw = transaction._unaffected_status(repo, excluded)
    records = {record[3:].decode("utf-8") for record in raw.split(b"\0") if record}
    assert records == set(unaffected)
    assert calls == [(
        "status", "--porcelain=v1", "-z", "--", ".",
        *(f":(top,exclude,literal){path}" for path in excluded),
    )]


def test_multi_file_nested_post_images_are_exact_and_sorted(tmp_path: Path, isolated) -> None:
    directory, queue = isolated
    repo = fixture_repo(tmp_path)
    nested = repo / "pkg" / "nested.txt"
    nested.parent.mkdir()
    nested.write_bytes(b"before nested\n")
    git(repo, "add", "pkg/nested.txt")
    git(repo, "commit", "-m", "nested")
    replacements = {"pkg/nested.txt": b"after nested\n", "app.py": b"VALUE = 3\n"}
    patch = make_patch_for_paths(repo, replacements)
    item = candidate(repo, patch, tuple(replacements))
    value = evaluation(repo, item)
    request = approval.request_competitive_approval(value)
    approval.hitl.resolve(request.request_id, approve=True)
    before, queue_before = snapshot(repo), queue.read_bytes()
    prepared = transaction.prepare_competitive_application_transaction(
        value, request.request_id, transaction_dir=directory,
    )
    assert [item.path for item in prepared.files] == ["app.py", "pkg/nested.txt"]
    assert [base64.b64decode(item.content_base64) for item in prepared.files] == [
        b"VALUE = 1\n", b"before nested\n",
    ]
    assert [base64.b64decode(item.expected_content_base64) for item in prepared.files] == [
        b"VALUE = 3\n", b"after nested\n",
    ]
    assert all(item.expected_filesystem_mode == item.filesystem_mode for item in prepared.files)
    assert snapshot(repo) == before and queue.read_bytes() == queue_before
    assert not list(tmp_path.rglob("claims.json"))


def test_git_apply_is_confined_to_cleaned_disposable_repository(
    tmp_path: Path, isolated, monkeypatch,
) -> None:
    directory, _ = isolated
    repo, value, request = approved(tmp_path)
    original = transaction.subprocess.run
    applications = []

    def recording(*args, **kwargs):
        command = args[0]
        if tuple(command[:2]) == ("git", "apply"):
            applications.append((tuple(command), Path(kwargs["cwd"]).resolve()))
        return original(*args, **kwargs)

    monkeypatch.setattr(transaction.subprocess, "run", recording)
    transaction.prepare_competitive_application_transaction(
        value, request.request_id, transaction_dir=directory,
    )
    assert len(applications) == 2
    assert "--check" in applications[0][0] and "--check" not in applications[1][0]
    for command, root in applications:
        assert command[-2] == "--"
        assert root != repo.resolve() and repo.resolve() not in root.parents
        assert directory.resolve() in root.parents
        assert not root.exists()


@pytest.mark.parametrize("filesystem_mode", [0o644, 0o755])
def test_preparation_captures_exact_filesystem_mode(tmp_path: Path, isolated, filesystem_mode: int) -> None:
    directory, queue = isolated
    repo, value, request = approved(tmp_path)
    git(repo, "config", "core.filemode", "false")
    (repo / "app.py").chmod(filesystem_mode)
    before_repo, before_queue = snapshot(repo), queue.read_bytes()
    prepared = transaction.prepare_competitive_application_transaction(
        value, request.request_id, transaction_dir=directory,
    )
    assert prepared.files[0].mode == 100644
    assert prepared.files[0].filesystem_mode == filesystem_mode
    assert prepared.files[0].expected_filesystem_mode == filesystem_mode
    assert snapshot(repo) == before_repo and queue.read_bytes() == before_queue


def test_preexisting_filesystem_permission_dirt_is_authoritative(tmp_path: Path, isolated) -> None:
    directory, queue = isolated
    repo, value, request = approved(tmp_path)
    (repo / "app.py").chmod(0o600)
    before_repo, before_queue = snapshot(repo), queue.read_bytes()
    prepared = transaction.prepare_competitive_application_transaction(
        value, request.request_id, transaction_dir=directory,
    )
    assert prepared.files[0].mode == 100644
    assert prepared.files[0].filesystem_mode == 0o600
    assert snapshot(repo) == before_repo and queue.read_bytes() == before_queue


def test_retrieval_and_repeated_preparation_are_read_only(tmp_path: Path, isolated) -> None:
    directory, _ = isolated
    _, value, request = approved(tmp_path)
    first = transaction.prepare_competitive_application_transaction(value, request.request_id, transaction_dir=directory)
    ledger = directory / "transactions.json"
    before = ledger.read_bytes()
    assert transaction.get_competitive_application_transaction(request.request_id, transaction_dir=directory) == first
    assert transaction.get_competitive_application_transaction(
        request.request_id, transaction_dir=directory,
    ).files[0].filesystem_mode == first.files[0].filesystem_mode
    assert ledger.read_bytes() == before
    assert transaction.prepare_competitive_application_transaction(value, request.request_id, transaction_dir=directory) == first
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("status", ["pending", "denied"])
def test_unapproved_request_publishes_no_transaction(tmp_path: Path, isolated, status: str) -> None:
    directory, queue = isolated
    repo = fixture_repo(tmp_path)
    value = evaluation(repo, candidate(repo))
    request = approval.request_competitive_approval(value)
    if status == "denied":
        approval.hitl.resolve(request.request_id, approve=False)
    before = queue.read_bytes()
    with pytest.raises(transaction.CompetitiveApplicationTransactionError):
        transaction.prepare_competitive_application_transaction(value, request.request_id, transaction_dir=directory)
    assert not (directory / "transactions.json").exists() and queue.read_bytes() == before


def write_ledger(directory: Path, value: object) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "transactions.lock").touch()
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    (directory / "transactions.json").write_bytes(raw)
    return raw


def valid_record(tmp_path: Path, isolated) -> tuple[dict, Path, object, object]:
    directory, _ = isolated
    repo, value, request = approved(tmp_path)
    prepared = transaction.prepare_competitive_application_transaction(value, request.request_id, transaction_dir=directory)
    return asdict(prepared), repo, value, request


@pytest.mark.parametrize("mutation", ["json", "schema", "fields", "base64", "file_digest", "state"])
def test_malformed_ledgers_fail_closed_without_rewrite(tmp_path: Path, isolated, mutation: str) -> None:
    directory, _ = isolated
    record, _, _, request = valid_record(tmp_path, isolated)
    if mutation == "json":
        value = b"not-json"
    elif mutation == "schema":
        value = {"schema_version": 2, "transactions": [record]}
    elif mutation == "fields":
        record.pop("candidate_id"); value = {"schema_version": 1, "transactions": [record]}
    elif mutation == "base64":
        record["repository_status_base64"] = "***"; value = {"schema_version": 1, "transactions": [record]}
    elif mutation == "file_digest":
        record["files"][0]["sha256"] = "0" * 64; value = {"schema_version": 1, "transactions": [record]}
    else:
        record["state"] = "other"; value = {"schema_version": 1, "transactions": [record]}
    raw = write_ledger(directory, value)
    with pytest.raises(transaction.CompetitiveApplicationTransactionError):
        transaction.get_competitive_application_transaction(request.request_id, transaction_dir=directory)
    assert (directory / "transactions.json").read_bytes() == raw


@pytest.mark.parametrize(
    "mutation",
    ["missing_integrity", "missing_unaffected_integrity", "missing_status", "extra",
     "malformed_integrity", "malformed_unaffected_integrity", "invalid_status_base64"],
)
def test_invalid_integrity_bindings_fail_closed_without_rewrite(
    tmp_path: Path, isolated, mutation: str,
) -> None:
    directory, _ = isolated
    record, _, _, request = valid_record(tmp_path, isolated)
    if mutation.startswith("missing_"):
        record.pop({
            "missing_integrity": "repository_integrity_sha256",
            "missing_unaffected_integrity": "unaffected_repository_integrity_sha256",
            "missing_status": "unaffected_status_base64",
        }[mutation])
    elif mutation == "extra":
        record["unexpected_integrity"] = "value"
    elif mutation == "malformed_integrity":
        record["repository_integrity_sha256"] = "G" * 64
    elif mutation == "malformed_unaffected_integrity":
        record["unaffected_repository_integrity_sha256"] = "0"
    else:
        record["unaffected_status_base64"] = "***"
    raw = write_ledger(directory, {"schema_version": 1, "transactions": [record]})
    with pytest.raises(transaction.CompetitiveApplicationTransactionError):
        transaction.get_competitive_application_transaction(
            request.request_id, transaction_dir=directory,
        )
    assert (directory / "transactions.json").read_bytes() == raw


@pytest.mark.parametrize(
    ("mutation", "filesystem_mode"),
    [("missing", None), ("extra", 0o644), ("boolean", True), ("negative", -1),
     ("oversized", 0o1000), ("setuid", 0o4644), ("setgid", 0o2644), ("sticky", 0o1644)],
)
def test_invalid_filesystem_modes_fail_closed_without_rewrite(
    tmp_path: Path, isolated, mutation: str, filesystem_mode: int | None,
) -> None:
    directory, _ = isolated
    record, _, _, request = valid_record(tmp_path, isolated)
    file_record = record["files"][0]
    if mutation == "missing":
        file_record.pop("filesystem_mode")
    elif mutation == "extra":
        file_record["unexpected"] = "value"
    else:
        file_record["filesystem_mode"] = filesystem_mode
    raw = write_ledger(directory, {"schema_version": 1, "transactions": [record]})
    with pytest.raises(transaction.CompetitiveApplicationTransactionError):
        transaction.get_competitive_application_transaction(request.request_id, transaction_dir=directory)
    assert (directory / "transactions.json").read_bytes() == raw


@pytest.mark.parametrize(
    "mutation",
    ["missing_mode", "missing_sha", "missing_content", "extra", "boolean", "negative", "oversized", "special",
     "invalid_base64", "malformed_digest", "digest_mismatch", "inconsistent_mode",
     "unchanged_all"],
)
def test_invalid_expected_fields_fail_closed_without_rewrite(
    tmp_path: Path, isolated, mutation: str,
) -> None:
    directory, _ = isolated
    record, _, _, request = valid_record(tmp_path, isolated)
    file_record = record["files"][0]
    if mutation.startswith("missing_"):
        file_record.pop({
            "missing_mode": "expected_filesystem_mode",
            "missing_sha": "expected_sha256",
            "missing_content": "expected_content_base64",
        }[mutation])
    elif mutation == "extra":
        file_record["unexpected_expected"] = "value"
    elif mutation == "boolean":
        file_record["expected_filesystem_mode"] = True
    elif mutation == "negative":
        file_record["expected_filesystem_mode"] = -1
    elif mutation == "oversized":
        file_record["expected_filesystem_mode"] = 0o1000
    elif mutation == "special":
        file_record["expected_filesystem_mode"] = 0o4644
    elif mutation == "invalid_base64":
        file_record["expected_content_base64"] = "***"
    elif mutation == "malformed_digest":
        file_record["expected_sha256"] = "G" * 64
    elif mutation == "digest_mismatch":
        file_record["expected_sha256"] = "0" * 64
    elif mutation == "inconsistent_mode":
        file_record["expected_filesystem_mode"] = file_record["filesystem_mode"] ^ 1
    else:
        file_record["expected_sha256"] = file_record["sha256"]
        file_record["expected_content_base64"] = file_record["content_base64"]
    raw = write_ledger(directory, {"schema_version": 1, "transactions": [record]})
    with pytest.raises(transaction.CompetitiveApplicationTransactionError):
        transaction.get_competitive_application_transaction(
            request.request_id, transaction_dir=directory,
        )
    assert (directory / "transactions.json").read_bytes() == raw


@pytest.mark.parametrize("failure", ["check", "apply", "partial", "unexpected", "noop"])
def test_disposable_failures_publish_nothing_and_are_cleaned(
    tmp_path: Path, isolated, monkeypatch, failure: str,
) -> None:
    directory, queue = isolated
    repo, value, request = approved(tmp_path)
    before, queue_before = snapshot(repo), queue.read_bytes()
    original = transaction._apply_disposable_patch
    disposable_roots = []

    def failing(disposable, patch_path, *, check):
        disposable_roots.append(disposable)
        if failure == "check" and check:
            raise transaction.CompetitiveApplicationTransactionError("forced check failure")
        if failure == "apply" and not check:
            raise transaction.CompetitiveApplicationTransactionError("forced apply failure")
        if failure == "partial" and not check:
            (disposable / "app.py").write_bytes(b"partial\n")
            raise transaction.CompetitiveApplicationTransactionError("forced partial failure")
        if failure == "noop":
            return None
        result = original(disposable, patch_path, check=check)
        if failure == "unexpected" and not check:
            (disposable / "unexpected.txt").write_bytes(b"unexpected\n")
        return result

    monkeypatch.setattr(transaction, "_apply_disposable_patch", failing)
    with pytest.raises(transaction.CompetitiveApplicationTransactionError):
        transaction.prepare_competitive_application_transaction(
            value, request.request_id, transaction_dir=directory,
        )
    assert not (directory / "transactions.json").exists()
    assert disposable_roots and all(not root.exists() for root in disposable_roots)
    assert not list(directory.glob(".post-image-*"))
    assert snapshot(repo) == before and queue.read_bytes() == queue_before
    assert not list(tmp_path.rglob("claims.json"))


def test_order_duplicates_and_conflict_do_not_rewrite(tmp_path: Path, isolated) -> None:
    directory, _ = isolated
    record, _, value, request = valid_record(tmp_path, isolated)
    second = dict(record, request_id="!")
    for records, message in [([record, record], "duplicate"), ([record, second], "unsorted")]:
        raw = write_ledger(directory, {"schema_version": 1, "transactions": records})
        with pytest.raises(transaction.CompetitiveApplicationTransactionError, match=message):
            transaction.get_competitive_application_transaction(request.request_id, transaction_dir=directory)
        assert (directory / "transactions.json").read_bytes() == raw
    payload = json.loads(record["approval_payload"])
    payload["candidate_id"] = "different"
    record["candidate_id"] = "different"
    record["approval_payload"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    record["approval_digest"] = digest(record["approval_payload"])
    raw = write_ledger(directory, {"schema_version": 1, "transactions": [record]})
    with pytest.raises(transaction.CompetitiveApplicationTransactionError, match="conflicting"):
        transaction.prepare_competitive_application_transaction(value, request.request_id, transaction_dir=directory)
    assert (directory / "transactions.json").read_bytes() == raw


@pytest.mark.parametrize("drift", ["head", "baseline", "candidate", "result", "approval"])
def test_evidence_drift_prevents_publication(tmp_path: Path, isolated, monkeypatch, drift: str) -> None:
    directory, _ = isolated
    repo, value, request = approved(tmp_path)
    if drift == "head":
        (repo / "new.txt").write_text("new\n"); git(repo, "add", "new.txt"); git(repo, "commit", "-m", "drift")
    elif drift == "baseline":
        (repo / "app.py").write_text("drift\n")
    elif drift == "candidate":
        value = replace(value, candidates=(replace(value.candidates[0], patch="tampered"),))
    elif drift == "result":
        value = replace(value, baseline_patch_sha256="tampered")
    else:
        monkeypatch.setattr(approval.hitl, "get_request", lambda request_id: {"ok": False})
    with pytest.raises(transaction.CompetitiveApplicationTransactionError):
        transaction.prepare_competitive_application_transaction(value, request.request_id, transaction_dir=directory)
    assert not (directory / "transactions.json").exists()


@pytest.mark.parametrize("drift", ["bytes", "mode"])
def test_affected_file_drift_during_preparation_fails_before_publication(tmp_path: Path, isolated, monkeypatch, drift: str) -> None:
    directory, _ = isolated
    repo, value, request = approved(tmp_path)
    original = transaction._affected_files
    def changing(repository, paths):
        result = original(repository, paths)
        if drift == "bytes":
            (repo / "app.py").write_text("changed concurrently\n")
        else:
            (repo / "app.py").chmod(0o755)
        return result
    monkeypatch.setattr(transaction, "_affected_files", changing)
    with pytest.raises(transaction.CompetitiveApplicationTransactionError, match="changed"):
        transaction.prepare_competitive_application_transaction(value, request.request_id, transaction_dir=directory)
    assert not (directory / "transactions.json").exists()


def test_unrelated_dirt_is_preserved_and_bound(tmp_path: Path, isolated) -> None:
    directory, queue = isolated
    repo, value, request = approved(tmp_path)
    (repo / "other.txt").write_text("dirty\n")
    (repo / "untracked.txt").write_text("untracked\n")
    before, queue_before = snapshot(repo), queue.read_bytes()
    prepared = transaction.prepare_competitive_application_transaction(value, request.request_id, transaction_dir=directory)
    assert base64.b64decode(prepared.repository_status_base64) == before[1]
    assert prepared.repository_manifest_sha256 == manifest(repo)
    assert prepared.repository_integrity_sha256 == integrity(repo)
    assert prepared.unaffected_repository_integrity_sha256 == integrity(
        repo, frozenset({"app.py"}),
    )
    expected_unaffected_status = git_bytes(
        repo, "status", "--porcelain=v1", "-z", "--", ".",
        ":(top,exclude,literal)app.py",
    )
    assert base64.b64decode(prepared.unaffected_status_base64) == expected_unaffected_status
    assert snapshot(repo) == before and queue.read_bytes() == queue_before


def _worker(value, request_id: str, directory: Path, gate, output, close_fd=None) -> None:
    if close_fd is not None:
        os.close(close_fd)
    gate.wait()
    try:
        output.put(transaction.prepare_competitive_application_transaction(
            value, request_id, transaction_dir=directory,
        ))
    except Exception as exc:
        output.put(type(exc).__name__ + ":" + str(exc))


def test_concurrent_identical_preparations_are_idempotent(tmp_path: Path, isolated) -> None:
    directory, _ = isolated
    _, value, request = approved(tmp_path)
    context = multiprocessing.get_context("fork")
    gate, output = context.Event(), context.Queue()
    workers = [context.Process(target=_worker, args=(value, request.request_id, directory, gate, output)) for _ in range(2)]
    for worker in workers: worker.start()
    gate.set()
    for worker in workers:
        worker.join(15); assert worker.exitcode == 0
    results = [output.get(timeout=2) for _ in workers]
    assert results[0] == results[1]
    assert len(json.loads((directory / "transactions.json").read_text())["transactions"]) == 1


def test_repository_lock_is_external_and_blocks_competing_holder(tmp_path: Path, isolated) -> None:
    directory, _ = isolated
    repo, value, request = approved(tmp_path)
    key = digest(str(repo.resolve()))
    locks = directory / "repository-locks"; locks.mkdir(parents=True)
    lock_path = locks / f"{key}.lock"
    with lock_path.open("a+b") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        context = multiprocessing.get_context("fork")
        gate, output = context.Event(), context.Queue()
        worker = context.Process(target=_worker, args=(value, request.request_id, directory, gate, output, held.fileno()))
        worker.start(); gate.set(); time.sleep(.25)
        assert worker.is_alive() and not (directory / "transactions.json").exists()
    worker.join(15); assert worker.exitcode == 0
    assert isinstance(output.get(timeout=2), transaction.CompetitiveApplicationTransaction)
    assert repo not in lock_path.resolve().parents


def test_source_ast_excludes_mutation_and_consumption() -> None:
    source = Path(transaction.__file__).read_text()
    tree = ast.parse(source)
    assert "competitive_coding_consumption" not in source
    assert "claim_competitive_approval" not in source
    function_apply_literals = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        and any(isinstance(item, ast.Constant) and item.value == "apply" for item in ast.walk(node))
    ]
    assert function_apply_literals == ["_apply_disposable_patch"]
    assert all(option not in source for option in ("--3way", "--index", "--cached", "--unsafe-paths", "--reject"))
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert calls.isdisjoint({"write_text", "write_bytes", "commit", "stage", "promote", "push"})
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_git":
            literals = [argument.value for argument in node.args if isinstance(argument, ast.Constant)]
            assert "apply" not in literals
