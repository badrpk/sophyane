from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import sophyane.competitive_coding_application_preflight as preflight
import sophyane.competitive_coding_approval as approval
from sophyane.competitive_coding_phase2 import (
    CompetitiveEvaluationCandidate,
    CompetitiveEvaluationResult,
)
from sophyane.evolution.trusted_supplemental_executor import TrustedSupplementalEvidence
from sophyane.scoped_candidate_diff import candidate_diff_for_paths


def git(repo: Path, *args: str, text: bool = True):
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text,
    ).stdout.strip() if text else subprocess.run


def run_git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


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


def make_patch(repo: Path, relative: str = "app.py", replacement: str = "VALUE = 2\n") -> str:
    target = repo / relative
    original = target.read_bytes()
    target.write_text(replacement)
    patch = git(repo, "diff", "--binary", "HEAD", "--", relative)
    target.write_bytes(original)
    return patch + "\n"


def evidence() -> TrustedSupplementalEvidence:
    return TrustedSupplementalEvidence(
        family="targeted", challenge_id="c1", evaluator_identity="judge",
        test_path="tests/red_queen/test_targeted_supplemental.py", executed=True,
        passed=True, returncode=0, timed_out=False, elapsed_seconds=.1,
        stdout="ok", stderr="", rejection_reason=None,
    )


def candidate(repo: Path, patch: str, paths: tuple[str, ...] = ("app.py",)) -> CompetitiveEvaluationCandidate:
    return CompetitiveEvaluationCandidate(
        candidate_id="only", proposal_valid=True, proposal_rejection_reason="",
        evaluation_status="PASS", evaluation_message="ok", changed_paths=paths,
        validators=("tests",), passed=True, trusted_status="PASS", trusted_passed=True,
        trusted_evidence=(evidence(),), patch=patch, patch_sha256=digest(patch),
        source_head=git(repo, "rev-parse", "HEAD"),
    )


def evaluation(repo: Path, item: CompetitiveEvaluationCandidate) -> CompetitiveEvaluationResult:
    baseline_paths = ("app.py",)
    baseline = candidate_diff_for_paths(repo, baseline_paths)
    return CompetitiveEvaluationResult(
        objective="repair", repository=repo.resolve(), target_name="sophyane",
        baseline_paths=baseline_paths, baseline_patch=baseline, txq_policy=None,
        candidates=(item,), status="fail_closed",
        missing_boundary="trusted_candidate_ranking_and_approval", winner=None,
        source_head=git(repo, "rev-parse", "HEAD"), baseline_patch_sha256=digest(baseline),
    )


@pytest.fixture
def isolated_hitl(tmp_path: Path, monkeypatch) -> Path:
    directory = tmp_path / "hitl"
    queue = directory / "queue.json"
    monkeypatch.setattr(approval.hitl, "HITL_DIR", directory)
    monkeypatch.setattr(approval.hitl, "QUEUE", queue)
    return queue


def approved(tmp_path: Path, *, patch: str | None = None, paths=("app.py",)):
    repo = fixture_repo(tmp_path)
    patch = make_patch(repo) if patch is None else patch
    value = evaluation(repo, candidate(repo, patch, paths))
    request = approval.request_competitive_approval(value)
    approval.hitl.resolve(request.request_id, approve=True)
    return repo, value, request


def snapshot(repo: Path):
    files = {path.relative_to(repo).as_posix(): path.read_bytes() for path in repo.rglob("*")
             if path.is_file() and ".git" not in path.relative_to(repo).parts}
    return git(repo, "rev-parse", "HEAD"), run_git(repo, "status", "--porcelain=v1", "-z"), files


def test_approved_patch_produces_exact_frozen_repeatable_plan(tmp_path: Path, isolated_hitl: Path) -> None:
    repo, value, request = approved(tmp_path)
    ranked = approval.rank_competitive_evaluation(value)
    before_repo, before_queue = snapshot(repo), isolated_hitl.read_bytes()
    first = preflight.prepare_competitive_application(value, request.request_id)
    second = preflight.prepare_competitive_application(value, request.request_id)
    payload = json.loads(ranked.approval_payload)
    assert first == second == preflight.CompetitiveApplicationPlan(
        request.request_id, ranked.approval_digest, ranked.approval_payload,
        payload["repository"], payload["source_head"], payload["baseline_patch_sha256"],
        "only", ranked.winner.patch, ranked.winner.patch_sha256, ("app.py",),
    )
    with pytest.raises(FrozenInstanceError):
        first.candidate_id = "changed"
    assert snapshot(repo) == before_repo
    assert isolated_hitl.read_bytes() == before_queue


@pytest.mark.parametrize("status", ["pending", "denied"])
def test_pending_and_denied_are_read_only_rejections(tmp_path: Path, isolated_hitl: Path, status: str) -> None:
    repo = fixture_repo(tmp_path)
    value = evaluation(repo, candidate(repo, make_patch(repo)))
    request = approval.request_competitive_approval(value)
    if status == "denied":
        approval.hitl.resolve(request.request_id, approve=False)
    before_repo, before_queue = snapshot(repo), isolated_hitl.read_bytes()
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(value, request.request_id)
    assert snapshot(repo) == before_repo and isolated_hitl.read_bytes() == before_queue


@pytest.mark.parametrize("kind", ["candidate", "result", "payload", "ranking"])
def test_tampering_fails_closed(tmp_path: Path, isolated_hitl: Path, monkeypatch, kind: str) -> None:
    repo, value, request = approved(tmp_path)
    if kind == "candidate":
        value = replace(value, candidates=(replace(value.candidates[0], patch="tampered"),))
    elif kind == "result":
        value = replace(value, baseline_patch_sha256="tampered")
    elif kind == "payload":
        original = preflight.verify_competitive_approval
        monkeypatch.setattr(preflight, "verify_competitive_approval", lambda *args: replace(
            original(*args), approval_payload="{}"
        ))
    else:
        original = preflight.rank_competitive_evaluation
        monkeypatch.setattr(preflight, "rank_competitive_evaluation", lambda arg: replace(
            original(arg), approval_digest="tampered"
        ))
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(value, request.request_id)


@pytest.mark.parametrize("kind", ["head", "baseline"])
def test_repository_drift_is_rejected(tmp_path: Path, isolated_hitl: Path, kind: str) -> None:
    repo, value, request = approved(tmp_path)
    if kind == "head":
        (repo / "new.txt").write_text("new\n")
        git(repo, "add", "new.txt")
        git(repo, "commit", "-m", "drift")
    else:
        (repo / "app.py").write_text("VALUE = drift\n")
    before = snapshot(repo)
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(value, request.request_id)
    assert snapshot(repo) == before


@pytest.mark.parametrize("patch,paths", [
    ("not a patch\n", ("app.py",)),
    ("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-NOPE\n+VALUE = 2\n", ("app.py",)),
    ("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n", ("other.txt",)),
])
def test_invalid_nonapplicable_and_path_mismatch(tmp_path: Path, isolated_hitl: Path, patch: str, paths) -> None:
    repo, value, request = approved(tmp_path, patch=patch, paths=paths)
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(value, request.request_id)


@pytest.mark.parametrize("path", ["/absolute", "../escape", "a/../../escape", "a\\b", "a//b"])
def test_unsafe_candidate_paths_are_rejected(tmp_path: Path, isolated_hitl: Path, path: str) -> None:
    patch = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
    _, value, request = approved(tmp_path, patch=patch, paths=(path,))
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(value, request.request_id)


@pytest.mark.parametrize("path", ["/absolute", "../escape"])
def test_absolute_and_escaping_patch_paths_are_rejected(
    tmp_path: Path, isolated_hitl: Path, path: str,
) -> None:
    patch = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
    _, value, request = approved(tmp_path, patch=patch)
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(value, request.request_id)


def profile_patch(repo: Path, profile: str) -> tuple[str, tuple[str, ...]]:
    if profile == "new":
        patch = "diff --git a/created.txt b/created.txt\nnew file mode 100644\n--- /dev/null\n+++ b/created.txt\n@@ -0,0 +1 @@\n+new\n"
        return patch, ("created.txt",)
    if profile == "delete":
        (repo / "app.py").unlink(); patch = git(repo, "diff", "--binary", "HEAD", "--", "app.py")
        (repo / "app.py").write_text("VALUE = 1\n"); return patch + "\n", ("app.py",)
    if profile == "mode":
        (repo / "app.py").chmod(0o755); patch = git(repo, "diff", "HEAD", "--", "app.py")
        (repo / "app.py").chmod(0o644); return patch + "\n", ("app.py",)
    if profile in {"rename", "copy"}:
        word = profile
        patch = f"diff --git a/app.py b/moved.py\nsimilarity index 100%\n{word} from app.py\n{word} to moved.py\n"
        return patch, ("moved.py",)
    if profile == "binary":
        return "diff --git a/app.py b/app.py\nGIT binary patch\nliteral 0\nHcmV?d00001\n", ("app.py",)
    path = "untracked.txt" if profile == "untracked" else "missing.txt"
    if profile == "untracked":
        (repo / path).write_text("old\n")
    patch = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
    return patch, (path,)


@pytest.mark.parametrize("profile", ["new", "delete", "binary", "rename", "copy", "mode", "untracked", "missing"])
def test_unsupported_profiles_are_rejected(tmp_path: Path, isolated_hitl: Path, profile: str) -> None:
    repo = fixture_repo(tmp_path)
    patch, paths = profile_patch(repo, profile)
    value = evaluation(repo, candidate(repo, patch, paths))
    request = approval.request_competitive_approval(value)
    approval.hitl.resolve(request.request_id, approve=True)
    before = snapshot(repo)
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(value, request.request_id)
    assert snapshot(repo) == before


@pytest.mark.parametrize("profile,mode", [("symlink", "120000"), ("gitlink", "160000")])
def test_symlink_and_gitlink_targets_are_rejected(tmp_path: Path, isolated_hitl: Path, profile: str, mode: str) -> None:
    repo = fixture_repo(tmp_path)
    path = profile
    blob = git(repo, "rev-parse", "HEAD") if profile == "gitlink" else git(repo, "hash-object", "-w", "--stdin")
    git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}")
    git(repo, "commit", "-m", profile)
    if profile == "symlink":
        (repo / path).symlink_to("app.py")
    patch = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
    value = evaluation(repo, candidate(repo, patch, (path,)))
    request = approval.request_competitive_approval(value); approval.hitl.resolve(request.request_id, approve=True)
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(value, request.request_id)


def test_unrelated_dirt_is_preserved_on_success_and_failure(tmp_path: Path, isolated_hitl: Path) -> None:
    repo, value, request = approved(tmp_path)
    (repo / "other.txt").write_text("dirty\n")
    (repo / "untracked.txt").write_text("untracked\n")
    before = snapshot(repo)
    assert preflight.prepare_competitive_application(value, request.request_id)
    assert snapshot(repo) == before
    bad = replace(value, candidates=(replace(value.candidates[0], patch="bad"),))
    with pytest.raises(preflight.CompetitiveApplicationPreflightError):
        preflight.prepare_competitive_application(bad, request.request_id)
    assert snapshot(repo) == before


def test_all_git_apply_invocations_are_guarded(tmp_path: Path, isolated_hitl: Path, monkeypatch) -> None:
    _, value, request = approved(tmp_path)
    original = subprocess.run
    seen = []
    def recording(argv, *args, **kwargs):
        if "apply" in argv:
            seen.append(tuple(argv))
            assert "--check" in argv or "--numstat" in argv
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", recording)
    preflight.prepare_competitive_application(value, request.request_id)
    assert any("--check" in argv for argv in seen)


def test_source_ast_has_no_mutation_consumption_or_unguarded_apply() -> None:
    source = Path(preflight.__file__).read_text()
    tree = ast.parse(source)
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not any("competitive_coding_consumption" in name for name in imports)
    assert calls.isdisjoint({"write_text", "write_bytes", "commit", "stage", "promote", "push"})
    assert "claim_competitive_approval" not in source
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_git":
            literals = [arg.value for arg in node.args if isinstance(arg, ast.Constant)]
            if "apply" in literals:
                assert "--check" in literals
