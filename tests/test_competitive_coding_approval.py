from __future__ import annotations

import ast
import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import sophyane.competitive_coding_approval as approval
from sophyane.competitive_coding_ranking import (
    CompetitiveRankedCandidate,
    CompetitiveRankingError,
    CompetitiveRankingResult,
)


def ranking(
    status: str = "approval_required",
    *,
    winner: bool = True,
) -> CompetitiveRankingResult:
    selected = (
        CompetitiveRankedCandidate(
            "one",
            "patch",
            "patch-hash",
            "head",
            "evidence-hash",
        )
        if winner
        else None
    )

    payload = (
        json.dumps(
            {
                "objective": "fixture objective",
                "repository": "/fixture/repository",
                "target_name": "sophyane",
                "source_head": "head",
                "baseline_patch_sha256": "baseline-hash",
                "candidate_id": "one",
                "candidate_patch_sha256": "patch-hash",
                "trusted_evidence_digest": "evidence-hash",
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if winner
        else ""
    )
    digest = (
        hashlib.sha256(
            payload.encode(
                "utf-8",
                errors="strict",
            )
        ).hexdigest()
        if winner
        else ""
    )

    return CompetitiveRankingResult(
        status,
        ("one",) if winner else (),
        selected,
        payload,
        digest,
        "fixture",
    )


def stored(value: CompetitiveRankingResult, status: str = "pending", request_id: str = "req-1") -> dict:
    action, detail = approval._binding(value)
    return {"ok": True, "request": {"id": request_id, "status": status, "action": action, "detail": detail, "risk": "high"}}


def test_exports_frozen_dataclasses_and_signatures() -> None:
    assert approval.__all__ == [
        "CompetitiveApprovalRequest", "CompetitiveApprovalVerification",
        "CompetitiveApprovalError", "request_competitive_approval",
        "verify_competitive_approval",
    ]
    request = approval.CompetitiveApprovalRequest("x", "pending", "d", "p")
    with pytest.raises(FrozenInstanceError):
        request.status = "approved"
    assert str(inspect.signature(approval.request_competitive_approval)) == "(evaluation: 'CompetitiveEvaluationResult') -> 'CompetitiveApprovalRequest'"
    assert str(inspect.signature(approval.verify_competitive_approval)) == "(evaluation: 'CompetitiveEvaluationResult', request_id: 'str') -> 'CompetitiveApprovalVerification'"


def test_request_uses_exact_action_detail_and_risk(monkeypatch) -> None:
    value = ranking()
    seen = {}
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: value)
    def request(action, detail, *, risk):
        seen.update(action=action, detail=detail, risk=risk)
        return stored(value)
    monkeypatch.setattr(approval.hitl, "request_approval", request)
    result = approval.request_competitive_approval(object())
    assert seen == {"action": f"competitive_coding_apply:{value.approval_digest}", "detail": approval._binding(value)[1], "risk": "high"}
    assert result.request_id == "req-1"
    assert result.approval_payload == value.approval_payload


def valid_ranking(status: str = "approval_required", *, winner: bool = True) -> CompetitiveRankingResult:
    selected = CompetitiveRankedCandidate("one", "patch", "patch-hash", "head", "evidence-hash") if winner else None
    payload = json.dumps({
        "objective": "repair", "repository": "/repo", "target_name": "sophyane",
        "source_head": "head", "baseline_patch_sha256": "baseline",
        "candidate_id": "one", "candidate_patch_sha256": "patch-hash",
        "trusted_evidence_digest": "evidence-hash",
    }, sort_keys=True, separators=(",", ":"))
    return CompetitiveRankingResult(status, ("one",) if winner else (), selected, payload if winner else "", hashlib.sha256(payload.encode()).hexdigest() if winner else "", "fixture")


ranking = valid_ranking


@pytest.mark.parametrize("bad_id", ["", "   ", None, 7])
def test_request_rejects_invalid_stored_id(monkeypatch, bad_id) -> None:
    value = ranking()
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: value)
    response = stored(value)
    response["request"]["id"] = bad_id
    monkeypatch.setattr(approval.hitl, "request_approval", lambda *a, **k: response)
    with pytest.raises(approval.CompetitiveApprovalError, match="id"):
        approval.request_competitive_approval(object())


@pytest.mark.parametrize("bad_id", ["", " ", None, 4])
def test_verify_rejects_bad_id_before_lookup(monkeypatch, bad_id) -> None:
    monkeypatch.setattr(approval.hitl, "get_request", lambda _: pytest.fail("lookup called"))
    with pytest.raises(approval.CompetitiveApprovalError, match="request_id"):
        approval.verify_competitive_approval(object(), bad_id)


@pytest.mark.parametrize("status,approved", [("pending", False), ("approved", True), ("denied", False)])
def test_verify_states_are_deterministic(monkeypatch, status, approved) -> None:
    value = ranking()
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: value)
    monkeypatch.setattr(approval.hitl, "get_request", lambda _: stored(value, status))
    first = approval.verify_competitive_approval(object(), "req-1")
    second = approval.verify_competitive_approval(object(), "req-1")
    assert first == second
    assert first.status == status and first.approved is approved


@pytest.mark.parametrize("field,value", [("id", "wrong"), ("action", "wrong"), ("detail", "wrong"), ("risk", "low"), ("status", "unknown")])
def test_verify_rejects_tampered_lookup(monkeypatch, field, value) -> None:
    ranked = ranking()
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: ranked)
    response = stored(ranked)
    response["request"][field] = value
    monkeypatch.setattr(approval.hitl, "get_request", lambda _: response)
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.verify_competitive_approval(object(), "req-1")


@pytest.mark.parametrize("response", [None, {}, {"ok": False}, {"ok": True}, {"ok": True, "request": None}])
def test_lookup_malformed_fails_closed(monkeypatch, response) -> None:
    value = ranking()
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: value)
    monkeypatch.setattr(approval.hitl, "get_request", lambda _: response)
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.verify_competitive_approval(object(), "req-1")


def test_lookup_exception_fails_closed(monkeypatch) -> None:
    value = ranking()
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: value)
    monkeypatch.setattr(approval.hitl, "get_request", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(approval.CompetitiveApprovalError, match="lookup"):
        approval.verify_competitive_approval(object(), "req-1")


@pytest.mark.parametrize("status", ["ambiguous", "no_eligible_candidate"])
def test_nonunique_ranking_never_requests(monkeypatch, status) -> None:
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: ranking(status, winner=False))
    monkeypatch.setattr(approval.hitl, "request_approval", lambda *a, **k: pytest.fail("requested"))
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.request_competitive_approval(object())


@pytest.mark.parametrize("error", [CompetitiveRankingError("bad"), RuntimeError("bad")])
def test_ranking_exceptions_are_converted(monkeypatch, error) -> None:
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: (_ for _ in ()).throw(error))
    monkeypatch.setattr(approval.hitl, "request_approval", lambda *a, **k: pytest.fail("requested"))
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.request_competitive_approval(object())


@pytest.mark.parametrize("response", [None, {}, {"ok": False}, {"ok": True, "request": None}])
def test_request_malformed_fails_closed(monkeypatch, response) -> None:
    value = ranking()
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: value)
    monkeypatch.setattr(approval.hitl, "request_approval", lambda *a, **k: response)
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.request_competitive_approval(object())


def test_verify_never_requests_or_resolves(monkeypatch) -> None:
    value = ranking()
    monkeypatch.setattr(approval, "rank_competitive_evaluation", lambda _: value)
    monkeypatch.setattr(approval.hitl, "request_approval", lambda *a, **k: pytest.fail("requested"))
    if hasattr(approval.hitl, "resolve"):
        monkeypatch.setattr(approval.hitl, "resolve", lambda *a, **k: pytest.fail("resolved"))
    monkeypatch.setattr(approval.hitl, "get_request", lambda _: stored(value, "approved"))
    assert approval.verify_competitive_approval(object(), "req-1").approved


def test_ast_has_no_prohibited_mutating_calls() -> None:
    tree = ast.parse(Path(approval.__file__).read_text())
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert called.isdisjoint({"apply", "commit", "branch", "stage", "stash", "reset", "clean", "promote", "resolve", "write_text", "write_bytes", "unlink"})


import subprocess

import test_competitive_coding_ranking as ranking_fixtures


def git(repo: Path, *args: str):
    return ranking_fixtures.git(repo, *args)


def fixture_repo(tmp_path: Path) -> Path:
    return ranking_fixtures.fixture_repo(tmp_path)


def real_evidence():
    return ranking_fixtures.evidence()


def real_candidate(repo: Path, name: str = "only", **changes):
    changes.setdefault("trusted_evidence", (real_evidence(),))
    return ranking_fixtures.candidate(repo, name, **changes)


def real_result(repo: Path, candidates):
    return ranking_fixtures.result(repo, tuple(candidates))


def repository_snapshot(repo: Path):
    head = git(repo, "rev-parse", "HEAD")
    status = subprocess.run(
        ("git", "-C", str(repo), "status", "--porcelain=v1", "-z"),
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    files = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in sorted(repo.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }
    return head, status, files


@pytest.fixture
def isolated_hitl(tmp_path: Path, monkeypatch):
    directory = tmp_path / "isolated-hitl"
    queue = directory / "queue.json"
    monkeypatch.setattr(approval.hitl, "HITL_DIR", directory)
    monkeypatch.setattr(approval.hitl, "QUEUE", queue)
    return queue


def test_real_pending_then_approved_preserves_binding(tmp_path: Path, isolated_hitl: Path) -> None:
    repo = fixture_repo(tmp_path)
    evaluation = real_result(repo, (real_candidate(repo),))
    ranked = approval.rank_competitive_evaluation(evaluation)
    request = approval.request_competitive_approval(evaluation)
    pending = approval.verify_competitive_approval(evaluation, request.request_id)
    assert pending.status == "pending" and not pending.approved
    assert request.approval_payload == pending.approval_payload == ranked.approval_payload
    assert request.approval_digest == pending.approval_digest == ranked.approval_digest
    approval.hitl.resolve(request.request_id, approve=True)
    verified = approval.verify_competitive_approval(evaluation, request.request_id)
    assert verified.status == "approved" and verified.approved


def test_real_denial_is_not_approved(tmp_path: Path, isolated_hitl: Path) -> None:
    repo = fixture_repo(tmp_path)
    evaluation = real_result(repo, (real_candidate(repo),))
    request = approval.request_competitive_approval(evaluation)
    approval.hitl.resolve(request.request_id, approve=False)
    verified = approval.verify_competitive_approval(evaluation, request.request_id)
    assert verified.status == "denied" and not verified.approved


def test_repeated_pending_verification_preserves_queue_and_repository(
    tmp_path: Path,
    isolated_hitl: Path,
) -> None:
    repo = fixture_repo(tmp_path)
    evaluation = real_result(repo, (real_candidate(repo),))
    request = approval.request_competitive_approval(evaluation)
    before_repository = repository_snapshot(repo)
    before_queue = isolated_hitl.read_bytes()
    first = approval.verify_competitive_approval(evaluation, request.request_id)
    second = approval.verify_competitive_approval(evaluation, request.request_id)
    assert first == second
    assert first.status == "pending" and not first.approved
    assert isolated_hitl.read_bytes() == before_queue
    assert repository_snapshot(repo) == before_repository


from dataclasses import replace


def test_real_head_drift_rejects_existing_approval(tmp_path: Path, isolated_hitl: Path) -> None:
    repo = fixture_repo(tmp_path)
    evaluation = real_result(repo, (real_candidate(repo),))
    request = approval.request_competitive_approval(evaluation)
    queue_before = isolated_hitl.read_bytes()
    (repo / "head-change.txt").write_text("new head\n")
    git(repo, "add", "head-change.txt")
    git(repo, "commit", "-m", "head drift")
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.verify_competitive_approval(evaluation, request.request_id)
    assert isolated_hitl.read_bytes() == queue_before


def test_real_selected_baseline_drift_rejects_existing_approval(tmp_path: Path, isolated_hitl: Path) -> None:
    repo = fixture_repo(tmp_path)
    evaluation = real_result(repo, (real_candidate(repo),))
    request = approval.request_competitive_approval(evaluation)
    queue_before = isolated_hitl.read_bytes()
    (repo / "app.py").write_text("VALUE = 3\n")
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.verify_competitive_approval(evaluation, request.request_id)
    assert isolated_hitl.read_bytes() == queue_before


def test_unselected_dirty_and_untracked_state_is_preserved(tmp_path: Path, isolated_hitl: Path) -> None:
    repo = fixture_repo(tmp_path)
    (repo / "other.txt").write_text("tracked\n")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-m", "add unrelated")
    (repo / "other.txt").write_text("dirty unrelated\n")
    (repo / "untracked.txt").write_text("untracked unrelated\n")
    evaluation = real_result(repo, (real_candidate(repo),))
    assert "other.txt" not in evaluation.baseline_patch
    assert "untracked.txt" not in evaluation.baseline_patch
    before = repository_snapshot(repo)
    request = approval.request_competitive_approval(evaluation)
    verified = approval.verify_competitive_approval(evaluation, request.request_id)
    assert verified.status == "pending" and not verified.approved
    assert repository_snapshot(repo) == before


@pytest.mark.parametrize("field", [
    "candidate.patch",
    "candidate.patch_sha256",
    "candidate.source_head",
    "result.source_head",
    "result.baseline_patch",
    "result.baseline_patch_sha256",
])
def test_stored_evaluation_tampering_rejects_existing_approval(
    tmp_path: Path,
    isolated_hitl: Path,
    field: str,
) -> None:
    repo = fixture_repo(tmp_path)
    original_candidate = real_candidate(repo)
    evaluation = real_result(repo, (original_candidate,))
    request = approval.request_competitive_approval(evaluation)
    queue_before = isolated_hitl.read_bytes()
    if field.startswith("candidate."):
        name = field.split(".", 1)[1]
        altered_candidate = replace(original_candidate, **{name: "tampered"})
        altered = replace(evaluation, candidates=(altered_candidate,))
    else:
        name = field.split(".", 1)[1]
        altered = replace(evaluation, **{name: "tampered"})
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.verify_competitive_approval(altered, request.request_id)
    assert isolated_hitl.read_bytes() == queue_before


@pytest.mark.parametrize("eligible_count", [0, 2])
def test_real_non_unique_result_cannot_request_approval(
    tmp_path: Path,
    isolated_hitl: Path,
    eligible_count: int,
) -> None:
    repo = fixture_repo(tmp_path)
    if eligible_count == 0:
        candidates = (real_candidate(repo, passed=False),)
    else:
        candidates = (real_candidate(repo, "first"), real_candidate(repo, "second"))
    evaluation = real_result(repo, candidates)
    before = isolated_hitl.read_bytes() if isolated_hitl.exists() else None
    with pytest.raises(approval.CompetitiveApprovalError):
        approval.request_competitive_approval(evaluation)
    after = isolated_hitl.read_bytes() if isolated_hitl.exists() else None
    assert after == before
