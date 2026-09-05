from __future__ import annotations

import ast
import hashlib
import json
import multiprocessing
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import sophyane.competitive_coding_approval as approval
import sophyane.competitive_coding_consumption as consumption
from sophyane.competitive_coding_phase2 import (
    CompetitiveEvaluationCandidate,
    CompetitiveEvaluationResult,
)
from sophyane.evolution.trusted_supplemental_executor import TrustedSupplementalEvidence
from sophyane.scoped_candidate_diff import candidate_diff_for_paths


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("VALUE = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    (repo / "app.py").write_text("VALUE = 2\n")
    return repo


def evidence() -> TrustedSupplementalEvidence:
    return TrustedSupplementalEvidence(
        family="targeted", challenge_id="c1", evaluator_identity="judge",
        test_path="tests/red_queen/test_targeted_supplemental.py",
        executed=True, passed=True, returncode=0, timed_out=False,
        elapsed_seconds=.1, stdout="ok", stderr="", rejection_reason=None,
    )


def candidate(repo: Path) -> CompetitiveEvaluationCandidate:
    patch = "candidate patch"
    return CompetitiveEvaluationCandidate(
        candidate_id="only", proposal_valid=True, proposal_rejection_reason="",
        evaluation_status="PASS", evaluation_message="ok", changed_paths=("app.py",),
        validators=("tests",), passed=True, trusted_status="PASS", trusted_passed=True,
        trusted_evidence=(evidence(),), patch=patch, patch_sha256=digest(patch),
        source_head=git(repo, "rev-parse", "HEAD"),
    )


def result(repo: Path, item: CompetitiveEvaluationCandidate) -> CompetitiveEvaluationResult:
    baseline = candidate_diff_for_paths(repo, ("app.py",))
    return CompetitiveEvaluationResult(
        objective="repair", repository=repo.resolve(), target_name="sophyane",
        baseline_paths=("app.py",), baseline_patch=baseline, txq_policy=None,
        candidates=(item,), status="fail_closed",
        missing_boundary="trusted_candidate_ranking_and_approval", winner=None,
        source_head=git(repo, "rev-parse", "HEAD"),
        baseline_patch_sha256=digest(baseline),
    )


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch):
    hitl_dir = tmp_path / "hitl"
    monkeypatch.setattr(approval.hitl, "HITL_DIR", hitl_dir)
    monkeypatch.setattr(approval.hitl, "QUEUE", hitl_dir / "queue.json")
    return tmp_path / "ledger"


def approved_evaluation(tmp_path: Path):
    repo = fixture_repo(tmp_path)
    evaluation = result(repo, candidate(repo))
    request = approval.request_competitive_approval(evaluation)
    approval.hitl.resolve(request.request_id, approve=True)
    return repo, evaluation, request


def snapshot(repo: Path):
    status = subprocess.run(
        ("git", "-C", str(repo), "status", "--porcelain=v1", "-z"),
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    files = {path.relative_to(repo).as_posix(): path.read_bytes() for path in repo.rglob("*")
             if path.is_file() and ".git" not in path.relative_to(repo).parts}
    return git(repo, "rev-parse", "HEAD"), status, files


def test_real_approval_claims_once_and_retrieves_exactly(tmp_path: Path, isolated: Path) -> None:
    _, evaluation, request = approved_evaluation(tmp_path)
    ranked = approval.rank_competitive_evaluation(evaluation)
    claim = consumption.claim_competitive_approval(evaluation, request.request_id, ledger_dir=isolated)
    payload = json.loads(ranked.approval_payload)
    assert claim == consumption.CompetitiveApprovalClaim(
        request.request_id, "claimed", ranked.approval_digest, ranked.approval_payload,
        payload["repository"], payload["source_head"], payload["baseline_patch_sha256"],
        payload["candidate_id"], payload["candidate_patch_sha256"],
        payload["trusted_evidence_digest"],
    )
    assert consumption.get_competitive_approval_claim(request.request_id, ledger_dir=isolated) == claim
    with pytest.raises(FrozenInstanceError):
        claim.state = "changed"
    ledger = isolated / "claims.json"
    before = ledger.read_bytes()
    with pytest.raises(consumption.CompetitiveConsumptionError, match="replay"):
        consumption.claim_competitive_approval(evaluation, request.request_id, ledger_dir=isolated)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("approved,status", [(False, "pending"), (False, "denied")])
def test_unapproved_never_creates_ledger(tmp_path: Path, isolated: Path, approved: bool, status: str) -> None:
    repo = fixture_repo(tmp_path)
    evaluation = result(repo, candidate(repo))
    request = approval.request_competitive_approval(evaluation)
    if status == "denied":
        approval.hitl.resolve(request.request_id, approve=approved)
    with pytest.raises(consumption.CompetitiveConsumptionError):
        consumption.claim_competitive_approval(evaluation, request.request_id, ledger_dir=isolated)
    assert not isolated.exists()


def valid_record(request_id: str = "req") -> dict:
    payload = json.dumps({
        "objective": "repair", "repository": "/repo", "target_name": "sophyane",
        "source_head": "head", "baseline_patch_sha256": "base", "candidate_id": "only",
        "candidate_patch_sha256": "patch", "trusted_evidence_digest": "evidence",
    }, sort_keys=True, separators=(",", ":"))
    return {"request_id": request_id, "state": "claimed", "approval_digest": digest(payload),
            "approval_payload": payload, "repository": "/repo", "source_head": "head",
            "baseline_patch_sha256": "base", "candidate_id": "only",
            "candidate_patch_sha256": "patch", "trusted_evidence_digest": "evidence"}


def install_ledger(directory: Path, value: object) -> bytes:
    directory.mkdir(exist_ok=True)
    (directory / "ledger.lock").write_bytes(b"")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    (directory / "claims.json").write_bytes(raw)
    return raw


@pytest.mark.parametrize("value", [
    "not-json",
    {"schema_version": 2, "claims": []},
    {"schema_version": 1, "claims": [{}]},
])
def test_malformed_ledgers_fail_closed_without_rewrite(tmp_path: Path, isolated: Path, value: object) -> None:
    isolated.mkdir()
    (isolated / "ledger.lock").write_bytes(b"")
    raw = value.encode() if isinstance(value, str) else json.dumps(value).encode()
    (isolated / "claims.json").write_bytes(raw)
    with pytest.raises(consumption.CompetitiveConsumptionError):
        consumption.get_competitive_approval_claim("req", ledger_dir=isolated)
    assert (isolated / "claims.json").read_bytes() == raw


def test_digest_duplicate_and_conflict_fail_closed(tmp_path: Path, isolated: Path) -> None:
    record = valid_record()
    bad = dict(record, approval_digest="bad")
    raw = install_ledger(isolated, {"schema_version": 1, "claims": [bad]})
    with pytest.raises(consumption.CompetitiveConsumptionError, match="digest"):
        consumption.get_competitive_approval_claim("req", ledger_dir=isolated)
    assert (isolated / "claims.json").read_bytes() == raw
    raw = install_ledger(isolated, {"schema_version": 1, "claims": [record, record]})
    with pytest.raises(consumption.CompetitiveConsumptionError, match="duplicate"):
        consumption.get_competitive_approval_claim("req", ledger_dir=isolated)
    assert (isolated / "claims.json").read_bytes() == raw


def test_conflicting_record_rejected_without_rewrite(tmp_path: Path, isolated: Path) -> None:
    _, evaluation, request = approved_evaluation(tmp_path)
    record = valid_record(request.request_id)
    raw = install_ledger(isolated, {"schema_version": 1, "claims": [record]})
    with pytest.raises(consumption.CompetitiveConsumptionError, match="conflicting"):
        consumption.claim_competitive_approval(evaluation, request.request_id, ledger_dir=isolated)
    assert (isolated / "claims.json").read_bytes() == raw


@pytest.mark.parametrize("drift", ["head", "baseline", "candidate", "result"])
def test_claim_reranks_and_rejects_drift(tmp_path: Path, isolated: Path, drift: str) -> None:
    repo, evaluation, request = approved_evaluation(tmp_path)
    if drift == "head":
        (repo / "new.txt").write_text("new\n")
        git(repo, "add", "new.txt")
        git(repo, "commit", "-m", "drift")
    elif drift == "baseline":
        (repo / "app.py").write_text("VALUE = 3\n")
    elif drift == "candidate":
        evaluation = replace(evaluation, candidates=(replace(evaluation.candidates[0], patch="tampered"),))
    else:
        evaluation = replace(evaluation, baseline_patch_sha256="tampered")
    with pytest.raises(consumption.CompetitiveConsumptionError):
        consumption.claim_competitive_approval(evaluation, request.request_id, ledger_dir=isolated)
    assert not isolated.exists()


def test_repository_state_is_untouched(tmp_path: Path, isolated: Path) -> None:
    repo = fixture_repo(tmp_path)
    (repo / "other.txt").write_text("tracked\n")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-m", "other")
    (repo / "other.txt").write_text("dirty\n")
    (repo / "untracked.txt").write_text("untracked\n")
    evaluation = result(repo, candidate(repo))
    request = approval.request_competitive_approval(evaluation)
    approval.hitl.resolve(request.request_id, approve=True)
    before = snapshot(repo)
    consumption.claim_competitive_approval(evaluation, request.request_id, ledger_dir=isolated)
    assert snapshot(repo) == before


def _claim_worker(evaluation, request_id: str, ledger_dir: Path, gate, output) -> None:
    gate.wait()
    try:
        consumption.claim_competitive_approval(evaluation, request_id, ledger_dir=ledger_dir)
        output.put("success")
    except consumption.CompetitiveConsumptionError as exc:
        output.put(str(exc))


def test_concurrent_same_request_has_one_winner(tmp_path: Path, isolated: Path) -> None:
    _, evaluation, request = approved_evaluation(tmp_path)
    context = multiprocessing.get_context("fork")
    gate = context.Event()
    output = context.Queue()
    workers = [context.Process(target=_claim_worker, args=(evaluation, request.request_id, isolated, gate, output)) for _ in range(2)]
    for worker in workers:
        worker.start()
    gate.set()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    outcomes = sorted(output.get(timeout=2) for _ in workers)
    assert outcomes == ["competitive approval claim replay", "success"]
    assert len(json.loads((isolated / "claims.json").read_text())["claims"]) == 1


def test_get_is_byte_for_byte_read_only(tmp_path: Path, isolated: Path) -> None:
    raw = install_ledger(isolated, {"schema_version": 1, "claims": [valid_record()]})
    lock_before = (isolated / "ledger.lock").read_bytes()
    assert consumption.get_competitive_approval_claim("req", ledger_dir=isolated)
    assert (isolated / "claims.json").read_bytes() == raw
    assert (isolated / "ledger.lock").read_bytes() == lock_before


def test_source_ast_has_no_repository_mutation_or_git_execution() -> None:
    tree = ast.parse(Path(consumption.__file__).read_text())
    names = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert names.isdisjoint({"run", "Popen", "resolve", "apply", "commit", "stage", "promote", "write_text", "write_bytes"})
    assert "subprocess" not in {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
