import json
import hashlib
import subprocess
from dataclasses import replace

import pytest

from sophyane.rsi.curriculum import AbilityRecord, CurriculumStore
from sophyane.rsi.curriculum_proposals import CurriculumProposalAdapter, ProposalContext
from sophyane.rsi.curriculum_source import CurriculumTaskSource
from sophyane.rsi.repository_inventory import RepositoryRecord


def repository(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run([
        "git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "--allow-empty", "-m", "base",
    ], check=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return RepositoryRecord(
        repo_id="owner/repo", path=str(root), remote="", owner="owner", name="repo",
        commit=commit, branch="main", test_commands=(("python", "-m", "pytest"),),
        editable_paths=("src",), digest="inventory-digest",
    )


def context(repo):
    return ProposalContext(
        ability=AbilityRecord("ability", "fix parser", ("failing test",)),
        allowed_paths=("src/parser.py",), existing_task_ids=(), capability_summary="parser",
        repository=repo, repository_id=repo.repo_id, base_commit=repo.commit,
    )


def proposal(repo, **changes):
    payload = {
        "task_id": "task-1", "parent_ability_id": "ability", "objective": "Fix parser",
        "repository_id": "owner/repo", "base_commit": repo.commit,
        "editable_paths": ["src/parser.py"], "verification": ["python", "-m", "pytest"],
        "red_command": ["python", "-m", "pytest", "tests/test_parser.py"],
        "red_failure_marker": "test_parser_handles_empty",
        "green_commands": [["python", "-m", "pytest", "tests/test_parser.py"]],
    }
    payload.update(changes)
    return payload


def test_old_json_task_loads_with_empty_repository_defaults(tmp_path):
    path = tmp_path / "curriculum.json"
    path.write_text(json.dumps({"schema_version": 1, "queue": [{
        "task_id": "legacy", "objective": "old", "source": "curriculum",
        "editable_paths": ["src/a.py"], "verification": ["pytest"],
    }]}), encoding="utf-8")

    task = CurriculumStore(path).load().queue[0]

    assert (task.repository_id, task.base_commit, task.proposal_digest) == ("", "", "")
    assert task.red_command == ()
    assert task.red_failure_marker == ""
    assert task.green_commands == ()


def test_bound_proposal_preserves_repository_verification_and_digest(tmp_path):
    repo = repository(tmp_path)
    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo))).propose(context(repo))

    assert result.accepted, result.reason
    task = result.task
    assert task.repository_id == "owner/repo"
    assert task.base_commit == repo.commit
    assert len(task.proposal_digest) == 64
    assert task.red_command == ("python", "-m", "pytest", "tests/test_parser.py")
    assert task.red_failure_marker == "test_parser_handles_empty"
    assert task.green_commands == (("python", "-m", "pytest", "tests/test_parser.py"),)
    store = CurriculumStore(tmp_path / "curriculum.json")
    from sophyane.rsi.curriculum import CurriculumState
    store.save(CurriculumState(queue=[task]))
    assert store.load().queue[0] == task


@pytest.mark.parametrize("changes", [
    {"repository_id": "owner/other"},
    {"repository_id": ""},
    {"base_commit": "short"},
    {"base_commit": "b" * 40},
    {"red_command": []},
    {"red_failure_marker": ""},
    {"green_commands": []},
    {"green_commands": [["python", "" ]]},
])
def test_bound_proposal_rejects_invalid_identity_or_verification(tmp_path, changes):
    repo = repository(tmp_path)
    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo, **changes))).propose(context(repo))
    assert not result.accepted


def test_duplicate_identity_is_rejected(tmp_path):
    repo = repository(tmp_path)
    bound = replace(context(repo), existing_task_ids=("task-1",))
    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo))).propose(bound)
    assert not result.accepted


@pytest.mark.parametrize("path", ["../other/src/parser.py", "/tmp/parser.py", "src/../other.py", "other/parser.py"])
def test_cross_repository_or_non_policy_path_is_rejected(tmp_path, path):
    repo = repository(tmp_path)
    bound = replace(context(repo), allowed_paths=(path,))
    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo, editable_paths=[path]))).propose(bound)
    assert not result.accepted


def test_symlink_out_of_repository_is_rejected(tmp_path):
    repo = repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "repo" / "src" / "escape").symlink_to(outside, target_is_directory=True)
    path = "src/escape/parser.py"
    bound = replace(context(repo), allowed_paths=(path,))
    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo, editable_paths=[path]))).propose(bound)
    assert not result.accepted


def test_symlink_inside_repository_cannot_escape_editable_subtree(tmp_path):
    repo = repository(tmp_path)
    root = tmp_path / "repo"
    (root / "private").mkdir()
    (root / "src" / "link").symlink_to(root / "private", target_is_directory=True)
    path = "src/link/parser.py"
    bound = replace(context(repo), allowed_paths=(path,))

    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo, editable_paths=[path]))).propose(bound)

    assert not result.accepted
    assert "path" in result.reason


def test_live_head_divergence_rejects_stale_inventory_record(tmp_path):
    repo = repository(tmp_path)
    subprocess.run([
        "git", "-C", repo.path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "--allow-empty", "-m", "new head",
    ], check=True)

    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo))).propose(context(repo))

    assert not result.accepted
    assert "stale" in result.reason.lower() or "commit" in result.reason.lower()


@pytest.mark.parametrize("path", ["src/./parser.py", "src//parser.py", "src/parser.py/"])
def test_noncanonical_repository_path_is_rejected(tmp_path, path):
    repo = repository(tmp_path)
    bound = replace(context(repo), allowed_paths=(path,))
    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo, editable_paths=[path]))).propose(bound)
    assert not result.accepted


def test_source_prompt_carries_repository_and_structured_check(tmp_path):
    repo = repository(tmp_path)
    prompts = []
    source = CurriculumTaskSource(
        lambda prompt: prompts.append(json.loads(prompt)) or json.dumps(proposal(repo)),
        CurriculumProposalAdapter(lambda _: ""),
    )
    result = source.propose(context(repo))
    assert result.accepted, result.reason
    assert prompts[0]["repository_id"] == repo.repo_id
    assert prompts[0]["base_commit"] == repo.commit
    assert "red_command" in prompts[0]["required_fields"]
    assert "green_commands" in prompts[0]["required_fields"]


def test_bounded_source_prompt_is_valid_json_and_keeps_required_fields(tmp_path):
    repo = repository(tmp_path)
    prompts = []
    bound = replace(context(repo), capability_summary="x" * 50_000)
    source = CurriculumTaskSource(
        lambda prompt: prompts.append(prompt) or json.dumps(proposal(repo)),
        CurriculumProposalAdapter(lambda _: ""),
    )

    result = source.propose(bound)

    assert result.accepted, result.reason
    assert len(prompts[0]) <= 12_000
    sent = json.loads(prompts[0])
    assert sent["repository_id"] == repo.repo_id
    assert sent["base_commit"] == repo.commit
    assert "red_command" in sent["required_fields"]
    assert "green_commands" in sent["required_fields"]
    assert sent["allowed_paths"] == ["src/parser.py"]


def test_duplicate_json_keys_are_rejected(tmp_path):
    repo = repository(tmp_path)
    raw = json.dumps(proposal(repo)).replace(
        '"repository_id": "owner/repo",',
        '"repository_id": "owner/other", "repository_id": "owner/repo",',
    )

    result = CurriculumProposalAdapter(lambda _: raw).propose(context(repo))

    assert not result.accepted
    assert "duplicate" in result.reason.lower()


def test_proposal_digest_binds_exact_provider_response(tmp_path):
    repo = repository(tmp_path)
    compact = json.dumps(proposal(repo), separators=(",", ":"))
    pretty = json.dumps(proposal(repo), indent=2)
    adapter = CurriculumProposalAdapter(lambda _: compact)

    first = adapter.validate(compact, context(repo))
    second = adapter.validate(pretty, context(repo))

    assert first.accepted and second.accepted
    assert first.task.proposal_digest == hashlib.sha256(compact.encode()).hexdigest()
    assert second.task.proposal_digest == hashlib.sha256(pretty.encode()).hexdigest()
    assert first.task.proposal_digest != second.task.proposal_digest


@pytest.mark.parametrize("argument", [12, False, {"shell": "pytest"}, None])
def test_verification_rejects_nonstrings(tmp_path, argument):
    repo = repository(tmp_path)
    result = CurriculumProposalAdapter(lambda _: json.dumps(proposal(repo, verification=["pytest", argument]))).propose(context(repo))
    assert not result.accepted
    assert "verification" in result.reason.lower()
