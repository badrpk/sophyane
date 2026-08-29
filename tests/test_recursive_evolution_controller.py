from __future__ import annotations

from pathlib import Path

import pytest


def test_controller_defaults_are_bounded():
    from sophyane.recursive_evolution_controller import (
        EvolutionConfig,
    )

    config = EvolutionConfig()

    assert config.max_iterations >= 1
    assert config.max_iterations <= 10

    assert config.max_files_per_candidate >= 1
    assert config.max_files_per_candidate <= 5

    assert config.require_clean_candidate is True


def test_controller_rejects_path_escape(tmp_path):
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionError,
        resolve_candidate_path,
    )

    with pytest.raises(RecursiveEvolutionError):
        resolve_candidate_path(
            tmp_path,
            "../escape.py",
        )


def test_controller_accepts_workspace_relative_file(tmp_path):
    from sophyane.recursive_evolution_controller import (
        resolve_candidate_path,
    )

    result = resolve_candidate_path(
        tmp_path,
        "src/example.py",
    )

    assert result == (
        tmp_path / "src" / "example.py"
    ).resolve()


def test_parse_local_llm_candidate_contract():
    from sophyane.recursive_evolution_controller import (
        parse_candidate,
    )

    candidate = parse_candidate(
        """RSI_CANDIDATE
reason:
Remove duplicated routing branch.
files:
- src/sophyane/example.py
verification:
- python -m py_compile src/sophyane/example.py
END_RSI_CANDIDATE
"""
    )

    assert candidate.reason == (
        "Remove duplicated routing branch."
    )

    assert candidate.files == (
        "src/sophyane/example.py",
    )

    assert candidate.verification == (
        "python -m py_compile src/sophyane/example.py",
    )


def test_parse_candidate_rejects_shell_payload_as_file():
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionError,
        parse_candidate,
    )

    with pytest.raises(RecursiveEvolutionError):
        parse_candidate(
            """RSI_CANDIDATE
reason:
bad
files:
- $(rm -rf ~)
verification:
- true
END_RSI_CANDIDATE
"""
        )


def test_controller_never_mutates_authoritative_repo_directly(
    tmp_path,
):
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionController,
    )

    repo = tmp_path / "repo"
    repo.mkdir()

    controller = RecursiveEvolutionController(
        repository=repo,
    )

    assert controller.repository == repo.resolve()

    candidate = controller.candidate_root(
        "iteration-1"
    )

    assert candidate != repo.resolve()
    assert repo.resolve() not in candidate.parents


def test_local_llm_prompt_requires_bounded_candidate():
    from sophyane.recursive_evolution_controller import (
        build_local_llm_prompt,
    )

    prompt = build_local_llm_prompt(
        objective="Improve routing reliability.",
        repository_summary="tests green",
        max_files=2,
    )

    assert "LOCAL LLM" in prompt
    assert "RSI_CANDIDATE" in prompt
    assert "END_RSI_CANDIDATE" in prompt
    assert "maximum 2 files" in prompt
    assert "Do not commit" in prompt
    assert "Do not push" in prompt


def test_nifdu_review_contract_is_nonexecuting():
    from sophyane.recursive_evolution_controller import (
        build_nifdu_review_prompt,
    )

    prompt = build_nifdu_review_prompt(
        objective="Improve routing reliability.",
        diff="diff --git a/a.py b/a.py",
        verification="3 passed",
    )

    assert "APPROVE" in prompt
    assert "REJECT" in prompt
    assert "Do not execute" in prompt
    assert "Do not modify" in prompt


# SOPHYANE_MODE3_RSI_REAL_CYCLE_V2

def test_apply_candidate_files_requires_explicit_content(tmp_path):
    from sophyane.recursive_evolution_controller import (
        CandidateProposal,
        RecursiveEvolutionError,
        apply_candidate_files,
    )

    proposal = CandidateProposal(
        reason="test",
        files=("src/example.py",),
        verification=("python -m py_compile src/example.py",),
    )

    try:
        apply_candidate_files(
            workspace=tmp_path,
            proposal=proposal,
            contents={},
        )
    except RecursiveEvolutionError:
        pass
    else:
        raise AssertionError(
            "candidate file without explicit content was accepted"
        )


def test_apply_candidate_files_writes_only_declared_files(tmp_path):
    from sophyane.recursive_evolution_controller import (
        CandidateProposal,
        apply_candidate_files,
    )

    proposal = CandidateProposal(
        reason="test",
        files=("src/example.py",),
        verification=("python -m py_compile src/example.py",),
    )

    written = apply_candidate_files(
        workspace=tmp_path,
        proposal=proposal,
        contents={
            "src/example.py": "print('ok')\n",
        },
    )

    assert written == (
        (tmp_path / "src" / "example.py").resolve(),
    )

    assert (
        tmp_path / "src" / "example.py"
    ).read_text(
        encoding="utf-8",
    ) == "print('ok')\n"


def test_candidate_diff_is_grounded(tmp_path):
    import subprocess

    from sophyane.recursive_evolution_controller import (
        candidate_diff,
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "a.py"
    target.write_text(
        "print('a')\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "a.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "base"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    target.write_text(
        "print('b')\n",
        encoding="utf-8",
    )

    diff = candidate_diff(
        tmp_path
    )

    assert "a.py" in diff
    assert "print('b')" in diff


def test_parse_nifdu_review():
    from sophyane.recursive_evolution_controller import (
        parse_nifdu_review,
    )

    assert parse_nifdu_review(
        "APPROVE"
    ) == (
        True,
        "APPROVE",
    )

    assert parse_nifdu_review(
        "REJECT: regression risk"
    ) == (
        False,
        "regression risk",
    )


def test_parse_nifdu_review_fails_closed():
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionError,
        parse_nifdu_review,
    )

    try:
        parse_nifdu_review(
            "looks good"
        )
    except RecursiveEvolutionError:
        pass
    else:
        raise AssertionError(
            "non-contract NIFDU review was accepted"
        )


# SOPHYANE_MODE3_RSI_LOCAL_LLM_V3

def test_extract_candidate_contents_contract():
    from sophyane.recursive_evolution_controller import (
        extract_candidate_contents,
    )

    response = """CANDIDATE
reason: improve classifier
files:
- src/example.py
verification:
- python -m py_compile src/example.py
FILE
path: src/example.py
content:
print('candidate')
END_FILE
END_CANDIDATE
"""

    proposal, contents = extract_candidate_contents(
        response
    )

    assert proposal.reason == "improve classifier"

    assert proposal.files == (
        "src/example.py",
    )

    assert contents == {
        "src/example.py": "print('candidate')\n",
    }


def test_extract_candidate_rejects_undeclared_file():
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionError,
        extract_candidate_contents,
    )

    response = """CANDIDATE
reason: test
files:
- src/a.py
verification:
- python -m py_compile src/a.py
FILE
path: src/b.py
content:
print('bad')
END_FILE
END_CANDIDATE
"""

    try:
        extract_candidate_contents(
            response
        )
    except RecursiveEvolutionError:
        pass
    else:
        raise AssertionError(
            "undeclared candidate file was accepted"
        )


def test_build_nifdu_review_bundle_contains_diff_and_verification():
    from sophyane.recursive_evolution_controller import (
        build_nifdu_review_bundle,
    )

    bundle = build_nifdu_review_bundle(
        objective="Improve classifier behavior.",
        diff="diff --git a/a.py b/a.py\n+print('x')\n",
        verification_ok=True,
        verification_evidence="$ pytest\n1 passed\n",
    )

    assert "Improve classifier behavior." in bundle
    assert "diff --git" in bundle
    assert "1 passed" in bundle
    assert "APPROVE" in bundle
    assert "REJECT:" in bundle


def test_local_llm_candidate_prompt_forbids_publish():
    from sophyane.recursive_evolution_controller import (
        build_real_local_llm_candidate_prompt,
    )

    prompt = build_real_local_llm_candidate_prompt(
        objective="Improve one classifier.",
        repository_summary="Sophyane repository",
    )

    lower = prompt.lower()

    assert "commit" in lower
    assert "push" in lower
    assert "merge" in lower
    assert "do not" in lower
    assert "candidate" in lower


# SOPHYANE_MODE3_RSI_VERIFICATION_POLICY_TESTS_V1

def test_rsi_verification_rejects_git_commit(tmp_path):
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionController,
        RecursiveEvolutionError,
    )

    controller = RecursiveEvolutionController(
        repository=tmp_path,
    )

    with __import__("pytest").raises(
        RecursiveEvolutionError
    ):
        controller.run_verification(
            workspace=tmp_path,
            commands=(
                'git commit -m "unsafe"',
            ),
        )


def test_rsi_verification_rejects_git_push(tmp_path):
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionController,
        RecursiveEvolutionError,
    )

    controller = RecursiveEvolutionController(
        repository=tmp_path,
    )

    with __import__("pytest").raises(
        RecursiveEvolutionError
    ):
        controller.run_verification(
            workspace=tmp_path,
            commands=(
                "git push origin main",
            ),
        )


def test_rsi_verification_rejects_git_add(tmp_path):
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionController,
        RecursiveEvolutionError,
    )

    controller = RecursiveEvolutionController(
        repository=tmp_path,
    )

    with __import__("pytest").raises(
        RecursiveEvolutionError
    ):
        controller.run_verification(
            workspace=tmp_path,
            commands=(
                "git add probe.py",
            ),
        )


def test_rsi_verification_rejects_repository_mutation_commands(
    tmp_path,
):
    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionController,
        RecursiveEvolutionError,
    )

    controller = RecursiveEvolutionController(
        repository=tmp_path,
    )

    blocked = (
        "git reset --hard HEAD",
        "git checkout -- file.py",
        "git restore file.py",
        "git merge other",
        "git rebase main",
        "git cherry-pick deadbeef",
        "rm -rf src",
    )

    for command in blocked:
        with __import__("pytest").raises(
            RecursiveEvolutionError
        ):
            controller.run_verification(
                workspace=tmp_path,
                commands=(
                    command,
                ),
            )


def test_rsi_verification_allows_read_only_and_test_commands(
    tmp_path,
):
    import subprocess

    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionController,
    )

    # Read-only Git verification still requires a real Git repository.
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "init",
            "-q",
        ],
        check=True,
    )

    controller = RecursiveEvolutionController(
        repository=tmp_path,
    )

    ok, evidence = controller.run_verification(
        workspace=tmp_path,
        commands=(
            "python -c \"print('SAFE')\"",
            "git status --porcelain",
            "git diff --check",
        ),
    )

    assert ok
    assert "SAFE" in evidence


def test_apply_candidate_files_keyword_contract(tmp_path):
    from sophyane.recursive_evolution_controller import (
        CandidateProposal,
        apply_candidate_files,
    )

    proposal = CandidateProposal(
        reason="probe",
        files=(
            "probe.py",
        ),
        verification=(
            "python probe.py",
        ),
    )

    written = apply_candidate_files(
        workspace=tmp_path,
        proposal=proposal,
        contents={
            "probe.py": "print('SAFE')\n",
        },
    )

    assert written == (
        (
            tmp_path
            / "probe.py"
        ).resolve(),
    )


# SOPHYANE_RSI_UNTRACKED_DIFF_TEST_V1

def test_candidate_diff_includes_untracked_candidate_file(
    tmp_path,
):
    import subprocess

    from sophyane.recursive_evolution_controller import (
        candidate_diff,
    )

    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "init",
            "-q",
        ],
        check=True,
    )

    target = (
        tmp_path
        / "tmp_mode3_rsi_probe.py"
    )

    target.write_text(
        "print('MODE3_RSI_PROBE')\n",
        encoding="utf-8",
    )

    diff = candidate_diff(
        tmp_path
    )

    assert (
        "tmp_mode3_rsi_probe.py"
        in diff
    )

    assert (
        "MODE3_RSI_PROBE"
        in diff
    )

    assert (
        "new file mode"
        in diff
        or "--- /dev/null"
        in diff
    )


def test_candidate_diff_includes_tracked_modification(
    tmp_path,
):
    import subprocess

    from sophyane.recursive_evolution_controller import (
        candidate_diff,
    )

    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "init",
            "-q",
        ],
        check=True,
    )

    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "config",
            "user.email",
            "rsi-test@example.invalid",
        ],
        check=True,
    )

    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "config",
            "user.name",
            "RSI Test",
        ],
        check=True,
    )

    target = (
        tmp_path
        / "existing.py"
    )

    target.write_text(
        "print('before')\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "existing.py",
        ],
        check=True,
    )

    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        check=True,
    )

    target.write_text(
        "print('after')\n",
        encoding="utf-8",
    )

    diff = candidate_diff(
        tmp_path
    )

    assert "existing.py" in diff
    assert "print('after')" in diff



# SOPHYANE_MODE3_NIFDU_SUPERVISED_RSI_TESTS_V4

def test_parse_supervised_nifdu_continue_contract():
    from sophyane.recursive_evolution_controller import (
        parse_supervised_nifdu_review,
    )

    result = parse_supervised_nifdu_review(
        """STATUS: CONTINUE
NEXT_MODE3_INSTRUCTION:
Inspect only the failing parser and repair its keyword-only call.
REASON:
The previous attempt used positional arguments.
"""
    )

    assert result.status == "CONTINUE"
    assert "keyword-only" in result.next_instruction
    assert "positional" in result.reason


def test_parse_supervised_nifdu_success_contract():
    from sophyane.recursive_evolution_controller import (
        parse_supervised_nifdu_review,
    )

    result = parse_supervised_nifdu_review(
        """STATUS: SUCCESS
EVIDENCE:
Focused tests and deterministic verification passed.
"""
    )

    assert result.status == "SUCCESS"
    assert "verification passed" in result.evidence


def test_parse_supervised_nifdu_malformed_fails_closed():
    import pytest

    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionError,
        parse_supervised_nifdu_review,
    )

    with pytest.raises(RecursiveEvolutionError):
        parse_supervised_nifdu_review(
            "Looks good, keep going."
        )


def test_supervised_rsi_rejection_causes_bounded_retry(
    tmp_path,
    monkeypatch,
):
    import shutil

    import sophyane.recursive_evolution_controller as rsi

    class FakeProvider:
        primary = "local_gguf"

        def __init__(self):
            self._providers = [
                (
                    "local_gguf",
                    object(),
                ),
            ]
            self.last_provider = ""
            self.calls = 0

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            self.calls += 1
            self.last_provider = "local_gguf"
            return f"candidate-{self.calls}"

    class FakeController:
        def __init__(self):
            self.created = []
            self.removed = []

        def create_worktree(
            self,
            *,
            name,
        ):
            target = tmp_path / name
            target.mkdir()
            self.created.append(target)
            return target

        def remove_worktree(
            self,
            workspace,
        ):
            workspace = workspace.resolve()
            self.removed.append(workspace)
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )

        def verify_candidate_scope(
            self,
            *,
            workspace,
            proposal,
        ):
            return None

        def run_verification(
            self,
            *,
            workspace,
            commands,
        ):
            return (
                True,
                "$ python probe.py\nPASS\n",
            )

    proposal = rsi.CandidateProposal(
        reason="probe",
        files=("probe.py",),
        verification=(
            "python probe.py",
        ),
    )

    monkeypatch.setattr(
        rsi,
        "extract_candidate_contents",
        lambda raw: (
            proposal,
            {
                "probe.py": "print('PASS')\n",
            },
        ),
    )

    monkeypatch.setattr(
        rsi,
        "apply_candidate_files",
        lambda **kwargs: (
            kwargs["workspace"] / "probe.py",
        ),
    )

    monkeypatch.setattr(
        rsi,
        "candidate_diff",
        lambda workspace: (
            "diff --git a/probe.py b/probe.py\n"
            "+print('PASS')\n"
        ),
    )

    responses = iter(
        (
            """STATUS: CONTINUE
NEXT_MODE3_INSTRUCTION:
Generate the same candidate but keep the implementation minimal.
REASON:
First candidate needs one bounded retry.
""",
            """STATUS: SUCCESS
EVIDENCE:
Verification passed and the candidate diff satisfies the objective.
""",
        )
    )

    result = rsi.run_supervised_mode3_nifdu_rsi(
        objective="Create one harmless probe.",
        repository=tmp_path,
        max_iterations=3,
        local_provider=FakeProvider(),
        nifdu_reviewer=lambda prompt: next(
            responses
        ),
        controller=FakeController(),
        authoritative_head_check=False,
    )

    assert result.success
    assert len(result.iterations) == 2
    assert result.iterations[0].review.status == "CONTINUE"
    assert result.iterations[1].review.status == "SUCCESS"

    for item in result.iterations:
        assert not item.worktree.exists()


def test_supervised_rsi_approval_stops_immediately(
    tmp_path,
    monkeypatch,
):
    import shutil

    import sophyane.recursive_evolution_controller as rsi

    class FakeProvider:
        primary = "local_gguf"
        _providers = [
            (
                "local_gguf",
                object(),
            ),
        ]

        def __init__(self):
            self.last_provider = ""
            self.calls = 0

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            self.calls += 1
            self.last_provider = "local_gguf"
            return "candidate"

    class FakeController:
        def create_worktree(
            self,
            *,
            name,
        ):
            target = tmp_path / name
            target.mkdir()
            return target

        def remove_worktree(
            self,
            workspace,
        ):
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )

        def verify_candidate_scope(
            self,
            *,
            workspace,
            proposal,
        ):
            pass

        def run_verification(
            self,
            *,
            workspace,
            commands,
        ):
            return (
                True,
                "verification-pass",
            )

    proposal = rsi.CandidateProposal(
        reason="probe",
        files=("probe.py",),
        verification=("python probe.py",),
    )

    monkeypatch.setattr(
        rsi,
        "extract_candidate_contents",
        lambda raw: (
            proposal,
            {
                "probe.py": "print('PASS')\n",
            },
        ),
    )

    monkeypatch.setattr(
        rsi,
        "apply_candidate_files",
        lambda **kwargs: (),
    )

    monkeypatch.setattr(
        rsi,
        "candidate_diff",
        lambda workspace: "diff --git\n+PASS\n",
    )

    provider = FakeProvider()

    result = rsi.run_supervised_mode3_nifdu_rsi(
        objective="probe",
        repository=tmp_path,
        max_iterations=3,
        local_provider=provider,
        nifdu_reviewer=lambda prompt: (
            "STATUS: SUCCESS\n"
            "EVIDENCE:\n"
            "All gates passed.\n"
        ),
        controller=FakeController(),
        authoritative_head_check=False,
    )

    assert result.success
    assert provider.calls == 1
    assert len(result.iterations) == 1


def test_supervised_rsi_repeated_rejection_stops_at_limit(
    tmp_path,
    monkeypatch,
):
    import shutil

    import sophyane.recursive_evolution_controller as rsi

    class FakeProvider:
        primary = "local_gguf"
        _providers = [
            (
                "local_gguf",
                object(),
            ),
        ]

        def __init__(self):
            self.last_provider = ""

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            self.last_provider = "local_gguf"
            return "candidate"

    class FakeController:
        def create_worktree(
            self,
            *,
            name,
        ):
            target = tmp_path / name
            target.mkdir()
            return target

        def remove_worktree(
            self,
            workspace,
        ):
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )

        def verify_candidate_scope(
            self,
            *,
            workspace,
            proposal,
        ):
            pass

        def run_verification(
            self,
            *,
            workspace,
            commands,
        ):
            return True, "PASS"

    proposal = rsi.CandidateProposal(
        reason="probe",
        files=("probe.py",),
        verification=("python probe.py",),
    )

    monkeypatch.setattr(
        rsi,
        "extract_candidate_contents",
        lambda raw: (
            proposal,
            {
                "probe.py": "print('PASS')\n",
            },
        ),
    )

    monkeypatch.setattr(
        rsi,
        "apply_candidate_files",
        lambda **kwargs: (),
    )

    monkeypatch.setattr(
        rsi,
        "candidate_diff",
        lambda workspace: "diff --git\n+PASS\n",
    )

    result = rsi.run_supervised_mode3_nifdu_rsi(
        objective="probe",
        repository=tmp_path,
        max_iterations=2,
        local_provider=FakeProvider(),
        nifdu_reviewer=lambda prompt: (
            "STATUS: CONTINUE\n"
            "NEXT_MODE3_INSTRUCTION:\n"
            "Try one smaller bounded repair.\n"
            "REASON:\n"
            "Not accepted yet.\n"
        ),
        controller=FakeController(),
        authoritative_head_check=False,
    )

    assert not result.success
    assert result.stop_reason == "max_iterations"
    assert len(result.iterations) == 2


def test_supervised_rsi_verification_failure_cannot_be_success(
    tmp_path,
    monkeypatch,
):
    import shutil
    import pytest

    import sophyane.recursive_evolution_controller as rsi

    class FakeProvider:
        primary = "local_gguf"
        _providers = [
            (
                "local_gguf",
                object(),
            ),
        ]
        last_provider = ""

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            self.last_provider = "local_gguf"
            return "candidate"

    class FakeController:
        def create_worktree(
            self,
            *,
            name,
        ):
            target = tmp_path / name
            target.mkdir()
            return target

        def remove_worktree(
            self,
            workspace,
        ):
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )

        def verify_candidate_scope(
            self,
            *,
            workspace,
            proposal,
        ):
            pass

        def run_verification(
            self,
            *,
            workspace,
            commands,
        ):
            return (
                False,
                "FAILED",
            )

    proposal = rsi.CandidateProposal(
        reason="probe",
        files=("probe.py",),
        verification=("python probe.py",),
    )

    monkeypatch.setattr(
        rsi,
        "extract_candidate_contents",
        lambda raw: (
            proposal,
            {
                "probe.py": "print('PASS')\n",
            },
        ),
    )

    monkeypatch.setattr(
        rsi,
        "apply_candidate_files",
        lambda **kwargs: (),
    )

    monkeypatch.setattr(
        rsi,
        "candidate_diff",
        lambda workspace: "diff --git\n+PASS\n",
    )

    with pytest.raises(
        rsi.RecursiveEvolutionError,
    ):
        rsi.run_supervised_mode3_nifdu_rsi(
            objective="probe",
            repository=tmp_path,
            max_iterations=1,
            local_provider=FakeProvider(),
            nifdu_reviewer=lambda prompt: (
                "STATUS: SUCCESS\n"
                "EVIDENCE:\n"
                "Claimed success.\n"
            ),
            controller=FakeController(),
            authoritative_head_check=False,
        )


def test_supervised_rsi_requires_singleton_local_gguf_chain():
    import pytest

    from sophyane.recursive_evolution_controller import (
        RecursiveEvolutionError,
        assert_mode3_local_provider,
    )

    class WrongProvider:
        primary = "local_gguf"
        _providers = [
            ("local_gguf", object()),
            ("gemini", object()),
        ]

    with pytest.raises(
        RecursiveEvolutionError,
    ):
        assert_mode3_local_provider(
            WrongProvider()
        )



def test_existing_evolution_context_uses_native_learning_authorities(
    tmp_path,
    monkeypatch,
) -> None:
    import sophyane.evolution.curriculum as curriculum
    import sophyane.evolution.principles as principles

    from sophyane.recursive_evolution_controller import (
        _existing_evolution_context,
    )

    observed = {
        "focus": [],
        "store": [],
        "recurrent": 0,
    }

    def fake_focused_capability(repo):
        observed["focus"].append(repo)
        return "python_execution"

    class FakePrincipleStore:
        def __init__(self, repo):
            observed["store"].append(repo)

        def recurrent_principles(self, *, component=""):
            observed["recurrent"] += 1

            assert component == ""

            return [
                {
                    "component": "runtime",
                    "capability": "python_execution",
                    "status": "recurrent",
                    "confidence": 0.97,
                    "principle": (
                        "preserve exact execution evidence"
                    ),
                },
            ]

    monkeypatch.setattr(
        curriculum,
        "focused_capability",
        fake_focused_capability,
    )

    monkeypatch.setattr(
        principles,
        "PrincipleStore",
        FakePrincipleStore,
    )

    result = _existing_evolution_context(
        tmp_path,
    )

    expected = tmp_path.resolve()

    assert observed["focus"] == [
        expected
    ]

    assert observed["store"] == [
        expected
    ]

    assert observed["recurrent"] == 1

    assert (
        "focused_capability=python_execution"
        in result
    )

    assert (
        "component=runtime"
        in result
    )

    assert (
        "capability=python_execution"
        in result
    )

    assert (
        "status=recurrent"
        in result
    )

    assert (
        "preserve exact execution evidence"
        in result
    )


def test_ground_supervised_rsi_instruction_preserves_objective_and_context(
) -> None:
    from sophyane.recursive_evolution_controller import (
        _ground_supervised_rsi_instruction,
    )

    result = _ground_supervised_rsi_instruction(
        "repair the failing parser",
        (
            "EXISTING_SOPHYANE_EVOLUTION_STATE\n"
            "focused_capability=python\n"
            "END_EXISTING_SOPHYANE_EVOLUTION_STATE"
        ),
    )

    assert result.startswith(
        "repair the failing parser"
    )

    assert (
        "focused_capability=python"
        in result
    )

    assert (
        "Do not treat it as permission"
        in result
    )

    assert (
        "repository mutation boundaries"
        in result
    )


def test_ground_supervised_rsi_instruction_without_context_is_identity(
) -> None:
    from sophyane.recursive_evolution_controller import (
        _ground_supervised_rsi_instruction,
    )

    assert (
        _ground_supervised_rsi_instruction(
            "one bounded repair",
            "",
        )
        == "one bounded repair"
    )


def test_existing_evolution_context_is_bounded(
    tmp_path,
    monkeypatch,
) -> None:
    import sophyane.evolution.curriculum as curriculum
    import sophyane.evolution.principles as principles

    from sophyane.recursive_evolution_controller import (
        _existing_evolution_context,
    )

    monkeypatch.setattr(
        curriculum,
        "focused_capability",
        lambda _repo: "filesystem",
    )

    class FakePrincipleStore:
        def __init__(self, _repo):
            pass

        def recurrent_principles(self, *, component=""):
            assert component == ""

            return [
                {
                    "status": "recurrent",
                    "principle": f"principle-{index}",
                }
                for index in range(50)
            ]

    monkeypatch.setattr(
        principles,
        "PrincipleStore",
        FakePrincipleStore,
    )

    result = _existing_evolution_context(
        tmp_path,
        maximum_principles=3,
    )

    assert (
        "recurrent_principle_count=50"
        in result
    )

    assert "principle-0" in result
    assert "principle-1" in result
    assert "principle-2" in result
    assert "principle-3" not in result



def _native_rsi_context(
    capability: str,
) -> str:
    return (
        "EXISTING_SOPHYANE_EVOLUTION_STATE\n"
        f"focused_capability={capability}\n"
        "recurrent_principle_count=0\n"
        "END_EXISTING_SOPHYANE_EVOLUTION_STATE"
    )


def test_supervised_rsi_native_evidence_failed_verification_learns_offline(
    tmp_path,
) -> None:
    import json

    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    workspace = (
        tmp_path
        / "candidate-one"
    )
    workspace.mkdir()

    path = _persist_supervised_rsi_evidence(
        repository=tmp_path,
        iteration=1,
        instruction="create the exact file",
        workspace=workspace,
        evolution_context=(
            _native_rsi_context(
                "filesystem"
            )
        ),
        verification_completed=True,
        verification_ok=False,
        verification_commands=(
            "python -m pytest -q tests/test_file.py",
        ),
        verification_evidence=(
            "file_exists=False\n"
            "exact_bytes=False"
        ),
        failure="verification failed",
        candidate_files=(
            "result.txt",
        ),
    )

    assert path is not None
    assert path.is_file()

    record = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    assert record["gate"] is None

    assert (
        record["task"]["capability"]
        == "filesystem"
    )

    assert (
        record["validation"]["passed"]
        is False
    )

    assert record["validation"]["checks"] == {
        "supervised_rsi_verification": False,
    }

    assert (
        record["status"]
        == "principle_candidate"
    )

    pipeline = record[
        "analysis_pipeline"
    ]

    assert (
        pipeline["blind"]
        is None
    )

    assert (
        pipeline["cloud"]
        is None
    )

    assert (
        pipeline["arbitration"]["decision"]
        == "deterministic_cloud_unavailable"
    )

    assert (
        pipeline["principle"]
        is not None
    )


def test_supervised_rsi_native_evidence_recurrence_uses_distinct_real_iterations(
    tmp_path,
) -> None:
    from sophyane.evolution.evidence_pipeline import (
        EvidenceStore,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    for index in (1, 2):
        workspace = (
            tmp_path
            / f"candidate-{index}"
        )
        workspace.mkdir()

        path = _persist_supervised_rsi_evidence(
            repository=tmp_path,
            iteration=index,
            instruction="create the exact file",
            workspace=workspace,
            evolution_context=(
                _native_rsi_context(
                    "filesystem"
                )
            ),
            verification_completed=True,
            verification_ok=False,
            verification_commands=(
                "git diff --check",
            ),
            verification_evidence=(
                "file_exists=False"
            ),
            failure="verification failed",
            candidate_diff=(
                "diff --git a/result.txt b/result.txt\n"
                + f"+wrong-{index}\\n"
            ),
            candidate_files=(
                "result.txt",
            ),
        )

        assert path is not None

    recurrent = (
        EvidenceStore(
            tmp_path
        )
        .principles
        .recurrent_principles(
            component="filesystem"
        )
    )

    assert len(recurrent) == 1

    assert (
        len(
            recurrent[0][
                "distinct_tasks"
            ]
        )
        == 2
    )


def test_supervised_rsi_native_evidence_success_is_persisted_but_not_analyzed(
    tmp_path,
) -> None:
    import json

    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    workspace = (
        tmp_path
        / "successful-candidate"
    )
    workspace.mkdir()

    path = _persist_supervised_rsi_evidence(
        repository=tmp_path,
        iteration=1,
        instruction="repair parser",
        workspace=workspace,
        evolution_context=(
            _native_rsi_context(
                "python"
            )
        ),
        verification_completed=True,
        verification_ok=True,
        verification_commands=(
            "python -m pytest -q",
        ),
        verification_evidence=(
            "37 passed"
        ),
        failure="",
    )

    assert path is not None

    record = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    assert record["gate"] is None

    assert (
        record["validation"]["passed"]
        is True
    )

    assert (
        record["status"]
        == "reinforced"
    )

    assert (
        "analysis_pipeline"
        not in record
    )


def test_supervised_rsi_preverification_failure_is_not_learning_evidence(
    tmp_path,
) -> None:
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    workspace = (
        tmp_path
        / "candidate"
    )
    workspace.mkdir()

    result = _persist_supervised_rsi_evidence(
        repository=tmp_path,
        iteration=1,
        instruction="repair parser",
        workspace=workspace,
        evolution_context=(
            _native_rsi_context(
                "python"
            )
        ),
        verification_completed=False,
        verification_ok=False,
        verification_commands=(),
        verification_evidence=(
            "candidate parse failed"
        ),
        failure="candidate parse failed",
    )

    assert result is None

    records = (
        tmp_path
        / ".sophyane-evolution"
        / "records"
    )

    assert (
        not records.exists()
        or not list(
            records.glob("*.json")
        )
    )


def test_supervised_rsi_native_evidence_unknown_focus_cannot_manufacture_principle(
    tmp_path,
) -> None:
    import json

    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    workspace = (
        tmp_path
        / "candidate"
    )
    workspace.mkdir()

    path = _persist_supervised_rsi_evidence(
        repository=tmp_path,
        iteration=1,
        instruction="bounded repair",
        workspace=workspace,
        evolution_context=(
            "EXISTING_SOPHYANE_EVOLUTION_STATE\n"
            "focused_capability=none\n"
            "END_EXISTING_SOPHYANE_EVOLUTION_STATE"
        ),
        verification_completed=True,
        verification_ok=False,
        verification_commands=(
            "git diff --check",
        ),
        verification_evidence=(
            "failed"
        ),
        failure="verification failed",
    )

    assert path is not None

    record = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    assert (
        record["task"]["capability"]
        == ""
    )

    assert (
        record["analysis_pipeline"]["principle"]
        is None
    )

    assert (
        record["status"]
        == "analysis_incomplete"
    )



def test_supervised_rsi_curriculum_feedback_records_success_once(
    tmp_path,
) -> None:
    from sophyane.evolution.curriculum import (
        load_scores,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    workspace = (
        tmp_path
        / "success-one"
    )
    workspace.mkdir()

    kwargs = {
        "repository": tmp_path,
        "iteration": 1,
        "instruction": "repair parser",
        "workspace": workspace,
        "evolution_context": (
            _native_rsi_context(
                "python"
            )
        ),
        "verification_completed": True,
        "verification_ok": True,
        "verification_commands": (
            "python -m pytest -q",
        ),
        "verification_evidence": (
            "42 passed"
        ),
        "failure": "",
    }

    first = _persist_supervised_rsi_evidence(
        **kwargs
    )

    assert first is not None

    scores = load_scores(
        tmp_path
    )

    assert (
        scores["python"]["attempts"]
        == 1
    )

    assert (
        scores["python"]["passes"]
        == 1
    )

    assert (
        scores["python"]["rate"]
        == 1.0
    )

    second = _persist_supervised_rsi_evidence(
        **kwargs
    )

    assert second == first

    scores = load_scores(
        tmp_path
    )

    assert (
        scores["python"]["attempts"]
        == 1
    )

    assert (
        scores["python"]["passes"]
        == 1
    )


def test_supervised_rsi_curriculum_feedback_records_failure_once(
    tmp_path,
) -> None:
    from sophyane.evolution.curriculum import (
        load_scores,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    workspace = (
        tmp_path
        / "failure-one"
    )
    workspace.mkdir()

    kwargs = {
        "repository": tmp_path,
        "iteration": 1,
        "instruction": "create exact file",
        "workspace": workspace,
        "evolution_context": (
            _native_rsi_context(
                "filesystem"
            )
        ),
        "verification_completed": True,
        "verification_ok": False,
        "verification_commands": (
            "git diff --check",
        ),
        "verification_evidence": (
            "file_exists=False"
        ),
        "failure": "verification failed",
    }

    first = _persist_supervised_rsi_evidence(
        **kwargs
    )

    assert first is not None

    scores = load_scores(
        tmp_path
    )

    assert (
        scores["filesystem"]["attempts"]
        == 1
    )

    assert (
        scores["filesystem"]["passes"]
        == 0
    )

    assert (
        scores["filesystem"]["rate"]
        == 0.0
    )

    second = _persist_supervised_rsi_evidence(
        **kwargs
    )

    assert second == first

    scores = load_scores(
        tmp_path
    )

    assert (
        scores["filesystem"]["attempts"]
        == 1
    )


def test_supervised_rsi_curriculum_feedback_ignores_unknown_capability(
    tmp_path,
) -> None:
    from sophyane.evolution.curriculum import (
        load_scores,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    workspace = (
        tmp_path
        / "unknown"
    )
    workspace.mkdir()

    before = load_scores(
        tmp_path
    )

    path = _persist_supervised_rsi_evidence(
        repository=tmp_path,
        iteration=1,
        instruction="bounded repair",
        workspace=workspace,
        evolution_context=(
            "EXISTING_SOPHYANE_EVOLUTION_STATE\n"
            "focused_capability=unknown_capability\n"
            "END_EXISTING_SOPHYANE_EVOLUTION_STATE"
        ),
        verification_completed=True,
        verification_ok=False,
        verification_commands=(
            "git diff --check",
        ),
        verification_evidence="failed",
        failure="verification failed",
    )

    assert path is not None

    after = load_scores(
        tmp_path
    )

    assert after == before


def test_supervised_rsi_preverification_failure_does_not_update_curriculum(
    tmp_path,
) -> None:
    from sophyane.evolution.curriculum import (
        load_scores,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    workspace = (
        tmp_path
        / "preverification"
    )
    workspace.mkdir()

    before = load_scores(
        tmp_path
    )

    result = _persist_supervised_rsi_evidence(
        repository=tmp_path,
        iteration=1,
        instruction="repair parser",
        workspace=workspace,
        evolution_context=(
            _native_rsi_context(
                "python"
            )
        ),
        verification_completed=False,
        verification_ok=False,
        verification_commands=(),
        verification_evidence=(
            "candidate parse failed"
        ),
        failure="candidate parse failed",
    )

    assert result is None

    after = load_scores(
        tmp_path
    )

    assert after == before


def test_supervised_rsi_curriculum_feedback_changes_native_focus(
    tmp_path,
) -> None:
    import json

    from sophyane.evolution.curriculum import (
        focused_capability,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    root = (
        tmp_path
        / ".sophyane-evolution"
    )
    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    scores = {
        "filesystem": {
            "attempts": 20,
            "passes": 20,
            "rate": 1.0,
        },
        "shell": {
            "attempts": 20,
            "passes": 20,
            "rate": 1.0,
        },
        "python": {
            "attempts": 19,
            "passes": 18,
            "rate": 18 / 19,
        },
        "html": {
            "attempts": 20,
            "passes": 20,
            "rate": 1.0,
        },
        "semantic_routing": {
            "attempts": 20,
            "passes": 20,
            "rate": 1.0,
        },
        "security": {
            "attempts": 20,
            "passes": 20,
            "rate": 1.0,
        },
    }

    (
        root
        / "capability-scores.json"
    ).write_text(
        json.dumps(
            scores
        ),
        encoding="utf-8",
    )

    assert (
        focused_capability(
            tmp_path,
            threshold=0.90,
            minimum_samples=20,
        )
        == "python"
    )

    workspace = (
        tmp_path
        / "python-mastery"
    )
    workspace.mkdir()

    path = _persist_supervised_rsi_evidence(
        repository=tmp_path,
        iteration=1,
        instruction="repair parser",
        workspace=workspace,
        evolution_context=(
            _native_rsi_context(
                "python"
            )
        ),
        verification_completed=True,
        verification_ok=True,
        verification_commands=(
            "python -m pytest -q",
        ),
        verification_evidence="passed",
        failure="",
    )

    assert path is not None

    #
    # Python now has 20 samples and 19 passes = 0.95, so it is mastered.
    # With all capabilities mastered, native focused_capability() falls back
    # to the lowest rate, which remains python at 0.95.
    #
    from sophyane.evolution.curriculum import (
        capability_mastered,
        load_scores,
    )

    updated = load_scores(
        tmp_path
    )

    assert (
        updated["python"]["attempts"]
        == 20
    )

    assert (
        updated["python"]["passes"]
        == 19
    )

    assert capability_mastered(
        tmp_path,
        "python",
        threshold=0.90,
        minimum_samples=20,
    )



def test_supervised_rsi_native_held_out_compares_baseline_and_candidate(
    tmp_path,
    monkeypatch,
) -> None:
    import sophyane.evolution.candidate_evolution as candidate_module

    from sophyane.evolution.candidate_evolution import (
        ReplayResult,
    )
    from sophyane.evolution.models import (
        TaskSpec,
    )
    from sophyane.recursive_evolution_controller import (
        _run_supervised_rsi_held_out,
    )

    candidate = (
        tmp_path
        / "candidate"
    )
    candidate.mkdir()

    observed = {
        "sources": [],
    }

    class FakeEvolver:
        def __init__(self, repo):
            assert repo == tmp_path.resolve()

        def held_out_tasks(
            self,
            *,
            capability,
        ):
            assert capability == "python"

            return [
                TaskSpec(
                    task_id="heldout-python",
                    prompt="probe",
                    capability="python",
                    validator="python",
                    held_out=True,
                )
            ]

        def replay_tasks(
            self,
            *,
            source_repo,
            tasks,
        ):
            observed["sources"].append(
                source_repo
            )

            assert len(tasks) == 1

            passed = (
                source_repo
                == candidate.resolve()
            )

            return [
                ReplayResult(
                    task_id="heldout-python",
                    capability="python",
                    passed=passed,
                    checks={
                        "probe": passed,
                    },
                    errors=(
                        []
                        if passed
                        else ["failed"]
                    ),
                )
            ]

        @staticmethod
        def score(results):
            return (
                sum(
                    1
                    for item in results
                    if item.passed
                )
                / max(
                    1,
                    len(results),
                )
            )

    monkeypatch.setattr(
        candidate_module,
        "CandidateEvolver",
        FakeEvolver,
    )

    result = _run_supervised_rsi_held_out(
        repository=tmp_path,
        workspace=candidate,
        evolution_context=(
            _native_rsi_context(
                "python"
            )
        ),
        verification_completed=True,
        verification_ok=True,
    )

    assert result["attempted"] is True
    assert result["baseline_score"] == 0.0
    assert result["candidate_score"] == 1.0
    assert result["not_regressed"] is True

    assert observed["sources"] == [
        tmp_path.resolve(),
        candidate.resolve(),
    ]


def test_supervised_rsi_native_held_out_detects_candidate_regression(
    tmp_path,
    monkeypatch,
) -> None:
    import sophyane.evolution.candidate_evolution as candidate_module

    from sophyane.evolution.candidate_evolution import (
        ReplayResult,
    )
    from sophyane.evolution.models import (
        TaskSpec,
    )
    from sophyane.recursive_evolution_controller import (
        _run_supervised_rsi_held_out,
    )

    candidate = (
        tmp_path
        / "candidate"
    )
    candidate.mkdir()

    class FakeEvolver:
        def __init__(self, _repo):
            pass

        def held_out_tasks(
            self,
            *,
            capability,
        ):
            return [
                TaskSpec(
                    task_id="heldout-filesystem",
                    prompt="probe",
                    capability=capability,
                    validator="filesystem",
                    held_out=True,
                )
            ]

        def replay_tasks(
            self,
            *,
            source_repo,
            tasks,
        ):
            passed = (
                source_repo
                == tmp_path.resolve()
            )

            return [
                ReplayResult(
                    task_id=tasks[0].task_id,
                    capability=tasks[0].capability,
                    passed=passed,
                    checks={},
                    errors=[],
                )
            ]

        @staticmethod
        def score(results):
            return (
                1.0
                if results[0].passed
                else 0.0
            )

    monkeypatch.setattr(
        candidate_module,
        "CandidateEvolver",
        FakeEvolver,
    )

    result = _run_supervised_rsi_held_out(
        repository=tmp_path,
        workspace=candidate,
        evolution_context=(
            _native_rsi_context(
                "filesystem"
            )
        ),
        verification_completed=True,
        verification_ok=True,
    )

    assert result["attempted"] is True
    assert result["baseline_score"] == 1.0
    assert result["candidate_score"] == 0.0
    assert result["not_regressed"] is False


def test_supervised_rsi_native_held_out_requires_real_verification_first(
    tmp_path,
    monkeypatch,
) -> None:
    import sophyane.evolution.candidate_evolution as candidate_module

    from sophyane.recursive_evolution_controller import (
        _run_supervised_rsi_held_out,
    )

    candidate = (
        tmp_path
        / "candidate"
    )
    candidate.mkdir()

    class ForbiddenEvolver:
        def __init__(self, _repo):
            raise AssertionError(
                "held-out replay must not start"
            )

    monkeypatch.setattr(
        candidate_module,
        "CandidateEvolver",
        ForbiddenEvolver,
    )

    result = _run_supervised_rsi_held_out(
        repository=tmp_path,
        workspace=candidate,
        evolution_context=(
            _native_rsi_context(
                "python"
            )
        ),
        verification_completed=False,
        verification_ok=False,
    )

    assert result["attempted"] is False
    assert result["not_regressed"] is True


def test_supervised_rsi_native_held_out_never_uses_authoritative_repo_as_candidate(
    tmp_path,
) -> None:
    from sophyane.recursive_evolution_controller import (
        _run_supervised_rsi_held_out,
    )

    result = _run_supervised_rsi_held_out(
        repository=tmp_path,
        workspace=tmp_path,
        evolution_context=(
            _native_rsi_context(
                "python"
            )
        ),
        verification_completed=True,
        verification_ok=True,
    )

    assert result["attempted"] is True
    assert result["not_regressed"] is False

    assert (
        "must_not_be_authoritative_repo"
        in result["evidence"]
    )



def test_supervised_rsi_synthetic_repository_does_not_claim_native_heldout(
    tmp_path,
    monkeypatch,
) -> None:
    import shutil

    import sophyane.recursive_evolution_controller as rsi

    class FakeProvider:
        primary = "local_gguf"
        _providers = [
            (
                "local_gguf",
                object(),
            ),
        ]

        def __init__(self):
            self.last_provider = ""

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            self.last_provider = "local_gguf"
            return "candidate"

    class FakeController:
        def create_worktree(
            self,
            *,
            name,
        ):
            target = (
                tmp_path
                / name
            )
            target.mkdir()
            return target

        def remove_worktree(
            self,
            workspace,
        ):
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )

        def verify_candidate_scope(
            self,
            *,
            workspace,
            proposal,
        ):
            return None

        def run_verification(
            self,
            *,
            workspace,
            commands,
        ):
            return (
                True,
                "verification-pass",
            )

    proposal = rsi.CandidateProposal(
        reason="probe",
        files=(
            "probe.py",
        ),
        verification=(
            "python probe.py",
        ),
    )

    monkeypatch.setattr(
        rsi,
        "extract_candidate_contents",
        lambda raw: (
            proposal,
            {
                "probe.py": (
                    "print('PASS')\n"
                ),
            },
        ),
    )

    monkeypatch.setattr(
        rsi,
        "apply_candidate_files",
        lambda **kwargs: (),
    )

    monkeypatch.setattr(
        rsi,
        "candidate_diff",
        lambda workspace: (
            "diff --git a/probe.py b/probe.py\n"
            "+print('PASS')\n"
        ),
    )

    def forbidden_held_out(**kwargs):
        raise AssertionError(
            "native held-out helper must not run "
            "without CandidateEvolver source authority"
        )

    monkeypatch.setattr(
        rsi,
        "_run_supervised_rsi_held_out",
        forbidden_held_out,
    )

    result = rsi.run_supervised_mode3_nifdu_rsi(
        objective="probe",
        repository=tmp_path,
        max_iterations=1,
        local_provider=FakeProvider(),
        nifdu_reviewer=lambda prompt: (
            "STATUS: SUCCESS\n"
            "EVIDENCE:\n"
            "deterministic verification passed\n"
        ),
        controller=FakeController(),
        authoritative_head_check=False,
    )

    assert result.success is True
    assert len(result.iterations) == 1

    item = result.iterations[0]

    assert (
        item.held_out_attempted
        is False
    )

    assert (
        item.held_out_not_regressed
        is True
    )

    assert (
        "candidate_evolution_authority_absent"
        in item.held_out_evidence
    )



def test_supervised_rsi_stable_identity_ignores_worktree_name(
) -> None:
    from sophyane.recursive_evolution_controller import (
        _supervised_rsi_evidence_identity,
    )

    common = {
        "instruction": "repair parser",
        "evolution_context": (
            _native_rsi_context(
                "python"
            )
        ),
        "diff": (
            "diff --git a/parser.py b/parser.py\n"
            "+return parsed\n"
        ),
        "verification_commands": (
            "python -m pytest -q",
        ),
        "candidate_files": (
            "parser.py",
        ),
    }

    first = _supervised_rsi_evidence_identity(
        **common
    )

    second = _supervised_rsi_evidence_identity(
        **common
    )

    assert first == second

    assert first.startswith(
        "supervised-rsi-"
    )


def test_supervised_rsi_stable_identity_changes_for_material_candidate_change(
) -> None:
    from sophyane.recursive_evolution_controller import (
        _supervised_rsi_evidence_identity,
    )

    common = {
        "instruction": "repair parser",
        "evolution_context": (
            _native_rsi_context(
                "python"
            )
        ),
        "verification_commands": (
            "python -m pytest -q",
        ),
        "candidate_files": (
            "parser.py",
        ),
    }

    first = _supervised_rsi_evidence_identity(
        diff="+return first\n",
        **common,
    )

    second = _supervised_rsi_evidence_identity(
        diff="+return second\n",
        **common,
    )

    assert first != second


def test_supervised_rsi_retry_same_candidate_does_not_double_count_score(
    tmp_path,
) -> None:
    from sophyane.evolution.curriculum import (
        load_scores,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    first_workspace = (
        tmp_path
        / "attempt-one"
    )

    second_workspace = (
        tmp_path
        / "attempt-after-restart"
    )

    first_workspace.mkdir()
    second_workspace.mkdir()

    common = {
        "repository": tmp_path,
        "iteration": 1,
        "instruction": "repair parser",
        "evolution_context": (
            _native_rsi_context(
                "python"
            )
        ),
        "verification_completed": True,
        "verification_ok": True,
        "verification_commands": (
            "python -m pytest -q",
        ),
        "verification_evidence": (
            "52 passed"
        ),
        "failure": "",
        "candidate_diff": (
            "diff --git a/parser.py b/parser.py\n"
            "+return parsed\n"
        ),
        "candidate_files": (
            "parser.py",
        ),
    }

    first = _persist_supervised_rsi_evidence(
        workspace=first_workspace,
        **common,
    )

    second = _persist_supervised_rsi_evidence(
        workspace=second_workspace,
        **common,
    )

    assert first is not None
    assert second == first

    scores = load_scores(
        tmp_path
    )

    assert (
        scores["python"]["attempts"]
        == 1
    )

    assert (
        scores["python"]["passes"]
        == 1
    )


def test_supervised_rsi_retry_same_failure_does_not_fake_principle_recurrence(
    tmp_path,
) -> None:
    from sophyane.evolution.evidence_pipeline import (
        EvidenceStore,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    for name in (
        "first-process",
        "restarted-process",
    ):
        workspace = (
            tmp_path
            / name
        )

        workspace.mkdir()

        path = _persist_supervised_rsi_evidence(
            repository=tmp_path,
            iteration=1,
            instruction="create exact file",
            workspace=workspace,
            evolution_context=(
                _native_rsi_context(
                    "filesystem"
                )
            ),
            verification_completed=True,
            verification_ok=False,
            verification_commands=(
                "git diff --check",
            ),
            verification_evidence=(
                "file_exists=False"
            ),
            failure="verification failed",
            candidate_diff=(
                "diff --git a/result.txt b/result.txt\n"
                "+wrong\n"
            ),
            candidate_files=(
                "result.txt",
            ),
        )

        assert path is not None

    store = EvidenceStore(
        tmp_path
    )

    recurrent = (
        store.principles
        .recurrent_principles(
            component="filesystem"
        )
    )

    assert recurrent == []

    principles = (
        store.principles
        ._load()
        .get(
            "principles",
            {},
        )
    )

    assert len(principles) == 1

    item = next(
        iter(
            principles.values()
        )
    )

    assert (
        len(
            item["distinct_tasks"]
        )
        == 1
    )


def test_supervised_rsi_distinct_candidates_remain_distinct_score_observations(
    tmp_path,
) -> None:
    from sophyane.evolution.curriculum import (
        load_scores,
    )
    from sophyane.recursive_evolution_controller import (
        _persist_supervised_rsi_evidence,
    )

    for index, diff in enumerate(
        (
            "+return first\n",
            "+return second\n",
        ),
        start=1,
    ):
        workspace = (
            tmp_path
            / f"candidate-{index}"
        )

        workspace.mkdir()

        path = _persist_supervised_rsi_evidence(
            repository=tmp_path,
            iteration=index,
            instruction="repair parser",
            workspace=workspace,
            evolution_context=(
                _native_rsi_context(
                    "python"
                )
            ),
            verification_completed=True,
            verification_ok=True,
            verification_commands=(
                "python -m pytest -q",
            ),
            verification_evidence="passed",
            failure="",
            candidate_diff=diff,
            candidate_files=(
                "parser.py",
            ),
        )

        assert path is not None

    scores = load_scores(
        tmp_path
    )

    assert (
        scores["python"]["attempts"]
        == 2
    )

    assert (
        scores["python"]["passes"]
        == 2
    )
