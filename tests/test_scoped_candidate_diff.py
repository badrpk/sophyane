from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sophyane.recursive_evolution_controller import (
    RecursiveEvolutionError,
)
from sophyane.scoped_candidate_diff import (
    candidate_diff_for_paths,
)


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    subprocess.run(
        ["git", "init", "-q"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Scoped Diff"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "scoped@example.invalid",
        ],
        cwd=repo,
        check=True,
    )

    (repo / ".gitignore").write_text(
        "ignored.txt\n",
        encoding="utf-8",
    )
    (repo / "tracked.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (repo / "unrelated.py").write_text(
        "UNRELATED = 1\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "fixture"],
        cwd=repo,
        check=True,
    )

    return repo


def state(repo: Path) -> tuple[bytes, bytes, dict[str, bytes]]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    files = {
        path.name: path.read_bytes()
        for path in repo.iterdir()
        if path.is_file()
    }
    return head, status, files


def test_includes_only_explicit_paths_and_preserves_state(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)

    (repo / "tracked.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    (repo / "unrelated.py").write_text(
        "UNRELATED = 2\n",
        encoding="utf-8",
    )
    (repo / "selected_new.py").write_text(
        "NEW = 1\n",
        encoding="utf-8",
    )
    (repo / "unrelated_new.py").write_text(
        "OTHER = 1\n",
        encoding="utf-8",
    )

    before = state(repo)

    diff = candidate_diff_for_paths(
        repo,
        ["selected_new.py", "tracked.py"],
    )

    assert "tracked.py" in diff
    assert "selected_new.py" in diff
    assert "unrelated.py" not in diff
    assert "unrelated_new.py" not in diff
    assert state(repo) == before


@pytest.mark.parametrize(
    "selected",
    [
        ["../escape.py"],
        ["/absolute.py"],
        ["ignored.txt"],
        ["missing.py"],
    ],
)
def test_rejects_unsafe_ignored_and_missing_paths(
    tmp_path: Path,
    selected: list[str],
) -> None:
    repo = init_repo(tmp_path)

    (repo / "ignored.txt").write_text(
        "secret\n",
        encoding="utf-8",
    )

    with pytest.raises(RecursiveEvolutionError):
        candidate_diff_for_paths(repo, selected)


def test_rejects_directories_and_symlinks(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "folder").mkdir()
    os.symlink(
        repo / "tracked.py",
        repo / "linked.py",
    )

    for selected in (["folder"], ["linked.py"]):
        with pytest.raises(RecursiveEvolutionError):
            candidate_diff_for_paths(
                repo,
                selected,
            )


def test_enforces_file_and_byte_budgets(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)

    (repo / "one.py").write_text(
        "ONE = 1\n",
        encoding="utf-8",
    )
    (repo / "two.py").write_text(
        "TWO = 2\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RecursiveEvolutionError,
        match="max_files",
    ):
        candidate_diff_for_paths(
            repo,
            ["one.py", "two.py"],
            max_files=1,
        )

    with pytest.raises(
        RecursiveEvolutionError,
        match="byte",
    ):
        candidate_diff_for_paths(
            repo,
            ["one.py"],
            max_total_bytes=5,
        )


def test_output_order_is_deterministic(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)

    (repo / "a.py").write_text(
        "A = 1\n",
        encoding="utf-8",
    )
    (repo / "z.py").write_text(
        "Z = 1\n",
        encoding="utf-8",
    )

    first = candidate_diff_for_paths(
        repo,
        ["z.py", "a.py"],
    )
    second = candidate_diff_for_paths(
        repo,
        ["a.py", "z.py"],
    )

    assert first == second
    assert first.index("a.py") < first.index("z.py")



def test_reconcile_candidate_paths_preserves_dirty_source(
    tmp_path: Path,
) -> None:
    from sophyane.scoped_candidate_diff import (
        reconcile_candidate_paths,
    )

    repo = init_repo(tmp_path)

    (repo / "tracked.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    (repo / "unrelated.py").write_text(
        "UNRELATED = 2\n",
        encoding="utf-8",
    )
    (repo / "selected_new.py").write_text(
        "NEW = 1\n",
        encoding="utf-8",
    )
    (repo / "unknown.txt").write_text(
        "preserve me\n",
        encoding="utf-8",
    )

    before = state(repo)

    result = reconcile_candidate_paths(
        repo,
        [
            "tracked.py",
            "selected_new.py",
        ],
    )

    assert result.authoritative_worktree_preserved
    assert result.clean_integration_worktree

    assert set(result.accepted_paths) == {
        "tracked.py",
        "selected_new.py",
    }

    assert set(result.reproduced_paths) == {
        "tracked.py",
        "selected_new.py",
    }

    assert result.unrelated_paths == ()

    assert "unrelated.py" in result.unknown_paths
    assert "unknown.txt" in result.unknown_paths

    assert state(repo) == before
    assert (repo / "unknown.txt").read_text(
        encoding="utf-8",
    ) == "preserve me\n"


def test_reconcile_classifies_known_ephemeral_without_deleting(
    tmp_path: Path,
) -> None:
    from sophyane.scoped_candidate_diff import (
        reconcile_candidate_paths,
    )

    repo = init_repo(tmp_path)

    (repo / "tracked.py").write_text(
        "VALUE = 7\n",
        encoding="utf-8",
    )

    generated = (
        repo
        / ".sophyane-provider-response-20260101-000000-1.txt"
    )
    generated.write_text(
        "provider output\n",
        encoding="utf-8",
    )

    unknown = repo / "notes.txt"
    unknown.write_text(
        "user notes\n",
        encoding="utf-8",
    )

    result = reconcile_candidate_paths(
        repo,
        ["tracked.py"],
    )

    assert (
        ".sophyane-provider-response-20260101-000000-1.txt"
        in result.ephemeral_paths
    )

    assert "notes.txt" in result.unknown_paths

    assert generated.exists()
    assert unknown.exists()


def test_reconcile_refuses_non_dirty_accepted_path(
    tmp_path: Path,
) -> None:
    from sophyane.scoped_candidate_diff import (
        reconcile_candidate_paths,
    )

    repo = init_repo(tmp_path)

    with pytest.raises(
        RecursiveEvolutionError,
        match="not currently dirty",
    ):
        reconcile_candidate_paths(
            repo,
            ["tracked.py"],
        )


def test_reconcile_unrelated_dirt_does_not_enter_clean_worktree(
    tmp_path: Path,
) -> None:
    from sophyane.scoped_candidate_diff import (
        reconcile_candidate_paths,
    )

    repo = init_repo(tmp_path)

    (repo / "tracked.py").write_text(
        "VALUE = 3\n",
        encoding="utf-8",
    )

    (repo / "unrelated.py").write_text(
        "UNRELATED = 99\n",
        encoding="utf-8",
    )

    (repo / "extra.py").write_text(
        "EXTRA = 1\n",
        encoding="utf-8",
    )

    result = reconcile_candidate_paths(
        repo,
        ["tracked.py"],
    )

    assert result.clean_integration_worktree
    assert result.reproduced_paths == (
        "tracked.py",
    )
    assert result.unrelated_paths == ()

    assert set(result.unknown_paths) == {
        "extra.py",
        "unrelated.py",
    }


@pytest.mark.parametrize(
    "accepted",
    [
        "../escape.py",
        "/absolute.py",
    ],
)
def test_reconcile_rejects_unsafe_selected_path(
    tmp_path: Path,
    accepted: str,
) -> None:
    from sophyane.scoped_candidate_diff import (
        reconcile_candidate_paths,
    )

    repo = init_repo(tmp_path)

    with pytest.raises(
        RecursiveEvolutionError,
        match="unsafe accepted path",
    ):
        reconcile_candidate_paths(
            repo,
            [accepted],
        )


def test_reconcile_classifies_exact_sophyane_generated_paths_only(tmp_path: Path):
    from sophyane.scoped_candidate_diff import reconcile_candidate_paths

    repo = init_repo(tmp_path)
    (repo / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")
    known = (
        ".sophyane-candidate.patch",
        "artifacts/sophyane-process-graph.json",
        "artifacts/sophyane-process-graph.mmd",
        "website/static/artifacts/sophyane-visualization.json",
        "website/static/artifacts/sophyane-visualization.png",
    )
    for relative in known:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"generated")
    user_files = ("artifacts/sophyane-process-graph-user.json", "website/static/artifacts/sophyane-visualization-user.png", "src/sophyane-output.txt", "tests/sophyane-output.txt")
    for relative in user_files:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"user")

    before = state(repo)
    result = reconcile_candidate_paths(repo, ["tracked.py"])
    assert set(known).issubset(set(result.ephemeral_paths))
    assert set(user_files).issubset(set(result.unknown_paths))
    assert state(repo) == before


def test_ephemeral_provenance_is_complete_and_deterministic(tmp_path: Path):
    from sophyane.scoped_candidate_diff import reconcile_candidate_paths

    repo = init_repo(tmp_path)
    (repo / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")
    generated = (
        ".sophyane-provider-response-2.txt",
        ".sophyane-candidate.patch",
        "artifacts/sophyane-process-graph.json",
        "artifacts/sophyane-process-graph.mmd",
        "website/static/artifacts/sophyane-visualization.json",
        "website/static/artifacts/sophyane-visualization.png",
    )
    for relative in generated:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"generated")
    (repo / "artifacts/sophyane-process-graph-user.json").write_bytes(b"user")
    before = state(repo)

    first = reconcile_candidate_paths(repo, ["tracked.py"])
    second = reconcile_candidate_paths(repo, ["tracked.py"])
    reasons = dict(first.ephemeral_provenance)
    assert tuple(path for path, _ in first.ephemeral_provenance) == first.ephemeral_paths
    assert set(reasons) == set(generated)
    assert reasons[".sophyane-provider-response-2.txt"] == "provider-response temporary artifact"
    assert reasons[".sophyane-candidate.patch"] == "candidate-patch temporary artifact"
    assert reasons["artifacts/sophyane-process-graph.json"] == "Sophyane process-graph generated artifact"
    assert reasons["website/static/artifacts/sophyane-visualization.png"] == "Sophyane visualization generated artifact"
    assert "artifacts/sophyane-process-graph-user.json" in first.unknown_paths
    assert first.ephemeral_provenance == second.ephemeral_provenance
    assert first.clean_integration_worktree
    assert first.authoritative_worktree_preserved
    assert state(repo) == before
