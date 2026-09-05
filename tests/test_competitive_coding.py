from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

import sophyane.competitive_coding as cc


VALID_PATCH = """diff --git a/demo.py b/demo.py
--- a/demo.py
+++ b/demo.py
@@ -1 +1 @@
-old
+new
"""


def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q"],
        cwd=repo,
        check=True,
    )
    (repo / "demo.py").write_text(
        "old\n",
        encoding="utf-8",
    )
    return repo


def test_exact_exports_and_keyword_only_signature() -> None:
    assert cc.__all__ == [
        "CompetitiveCandidateResult",
        "CompetitiveCodingResult",
        "CompetitiveCodingError",
        "run_competitive_coding",
        "request_competitive_application",
        "apply_competitive_application",
    ]

    signature = inspect.signature(
        cc.run_competitive_coding
    )

    assert list(signature.parameters) == [
        "objective",
        "repository",
        "candidate_provider",
        "candidate_count",
        "apply_winner",
        "progress",
    ]

    assert all(
        parameter.kind
        is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_rejects_empty_objective_and_small_count(
    tmp_path: Path,
) -> None:
    repo = git_repo(tmp_path)

    with pytest.raises(
        cc.CompetitiveCodingError,
        match="objective",
    ):
        cc.run_competitive_coding(
            objective=" ",
            repository=repo,
            candidate_provider=lambda _: VALID_PATCH,
        )

    with pytest.raises(
        cc.CompetitiveCodingError,
        match="at least two",
    ):
        cc.run_competitive_coding(
            objective="repair",
            repository=repo,
            candidate_provider=lambda _: VALID_PATCH,
            candidate_count=1,
        )


def test_rejects_non_git_repository(
    tmp_path: Path,
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(
        cc.CompetitiveCodingError,
        match="Git repository",
    ):
        cc.run_competitive_coding(
            objective="repair",
            repository=plain,
            candidate_provider=lambda _: VALID_PATCH,
        )


def test_selects_mode4_txq_once_and_calls_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = git_repo(tmp_path)
    txq_calls = []
    prompts = []

    original = cc.choose_global_txq_policy

    def txq(mode, objective):
        txq_calls.append((mode, objective))
        return original(mode, objective)

    def provider(prompt):
        prompts.append(prompt)
        return VALID_PATCH

    monkeypatch.setattr(
        cc,
        "choose_global_txq_policy",
        txq,
    )

    result = cc.run_competitive_coding(
        objective=" repair repository ",
        repository=repo,
        candidate_provider=provider,
        candidate_count=3,
    )

    assert txq_calls == [(4, "repair repository")]
    assert len(prompts) == 3
    assert len(set(prompts)) == 3
    assert result.txq_policy.mode == 4
    assert [
        row.candidate_id
        for row in result.candidates
    ] == [
        "candidate-1",
        "candidate-2",
        "candidate-3",
    ]
    assert all(row.valid for row in result.candidates)


def test_accepts_text_attribute_and_records_invalid_proposal(
    tmp_path: Path,
) -> None:
    repo = git_repo(tmp_path)

    class Response:
        def __init__(self, text: str):
            self.text = text

    responses = iter(
        [
            Response(VALID_PATCH),
            "not a patch",
        ]
    )

    result = cc.run_competitive_coding(
        objective="repair",
        repository=repo,
        candidate_provider=lambda _: next(responses),
    )

    assert result.candidates[0].valid
    assert not result.candidates[1].valid
    assert result.candidates[1].rejection_reason
    assert len(result.candidates) == 2


@pytest.mark.parametrize(
    "patch",
    [
        """diff --git /tmp/a b/a
--- /tmp/a
+++ b/a
@@ -1 +1 @@
-a
+b
""",
        """diff --git a/../secret b/../secret
--- a/../secret
+++ b/../secret
@@ -1 +1 @@
-a
+b
""",
    ],
)
def test_rejects_unsafe_paths(
    tmp_path: Path,
    patch: str,
) -> None:
    repo = git_repo(tmp_path)

    result = cc.run_competitive_coding(
        objective="repair",
        repository=repo,
        candidate_provider=lambda _: patch,
    )

    assert all(
        not row.valid
        and "unsafe" in row.rejection_reason
        for row in result.candidates
    )


def test_status_boundary_winner_and_repository_immutability(
    tmp_path: Path,
) -> None:
    repo = git_repo(tmp_path)
    before_file = (repo / "demo.py").read_bytes()
    before_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    normal = cc.run_competitive_coding(
        objective="repair",
        repository=repo,
        candidate_provider=lambda _: VALID_PATCH,
    )
    approval = cc.run_competitive_coding(
        objective="repair",
        repository=repo,
        candidate_provider=lambda _: VALID_PATCH,
        apply_winner=True,
    )

    assert normal.status == "fail_closed"
    assert approval.status == "approval_required"
    assert normal.winner is None
    assert approval.winner is None
    assert normal.missing_boundary == (
        "objective_driven_multi_worktree_gate_coordinator"
    )
    assert approval.missing_boundary == (
        "objective_driven_multi_worktree_gate_coordinator"
    )

    assert (repo / "demo.py").read_bytes() == before_file
    after_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert after_status == before_status


def test_source_avoids_execution_routes() -> None:
    source = Path(
        "src/sophyane/competitive_coding.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "Candidate" + "Evolver",
        "Evolution" + "Engine",
        "run_" + "adaptive_loop",
        "run_" + "structured_loop",
    )

    assert all(name not in source for name in forbidden)


def test_approved_evaluation_handoff_delegates_to_public_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sophyane.competitive_coding_approval as approval
    import sophyane.competitive_coding_application as boundary

    evaluation = object()
    request = object()
    applied = object()
    calls = []

    def make_request(value):
        calls.append(("request", value))
        return request

    def apply(value, request_id, **kwargs):
        calls.append(("apply", value, request_id, kwargs))
        return applied

    monkeypatch.setattr(approval, "request_competitive_approval", make_request)
    monkeypatch.setattr(boundary, "apply_competitive_application", apply)

    assert cc.request_competitive_application(evaluation) is request
    assert cc.apply_competitive_application(
        evaluation, "approved-id", transaction_dir=tmp_path / "transactions",
        claim_ledger_dir=tmp_path / "claims", application_dir=tmp_path / "applications",
    ) is applied
    assert calls == [
        ("request", evaluation),
        ("apply", evaluation, "approved-id", {
            "transaction_dir": tmp_path / "transactions",
            "claim_ledger_dir": tmp_path / "claims",
            "application_dir": tmp_path / "applications",
        }),
    ]


def test_phase1_default_remains_fail_closed_without_handoff(tmp_path: Path) -> None:
    repo = git_repo(tmp_path)
    result = cc.run_competitive_coding(
        objective="repair", repository=repo,
        candidate_provider=lambda _: VALID_PATCH,
    )
    assert result.status == "fail_closed"
    assert result.winner is None
    assert not list(tmp_path.iterdir()) or (repo / "demo.py").read_text() == "old\n"
