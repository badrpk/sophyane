from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sophyane.execution_evidence import FileEvidence
from sophyane.providers.base import ProviderCapabilities
from sophyane.strict_interactive_doer import (
    StrictInteractiveCodingDoerRuntime,
)


class NeverBackend:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        prompt: str,
        system: str,
    ) -> str:
        self.calls += 1
        raise AssertionError(
            "LLM verifier must not run for a fully evidenced "
            "single-file write-only completion"
        )


class FailingBackend:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        prompt: str,
        system: str,
    ) -> str:
        self.calls += 1
        raise RuntimeError(
            "EXPECTED_VERIFIER_CALL"
        )


class FakeIndex:
    def build(self):
        return SimpleNamespace(
            digest="TEST_REPOSITORY_DIGEST"
        )


class FakeGit:
    def status(self):
        return "TEST_GIT_STATUS"


class FakeMechanical:
    def verify(
        self,
        checks,
        command_observations=None,
    ):
        return {
            "passed": True,
            "results": [],
        }


class FakeReport:
    def __init__(self) -> None:
        self.files = []
        self.commands = []

    def to_dict(self):
        return {
            "files": [
                {
                    "path": item.path,
                    "size": item.size,
                    "sha256": item.sha256,
                }
                for item in self.files
            ],
            "commands": [],
        }


class FakeProgress:
    @contextmanager
    def waiting(
        self,
        *args,
        **kwargs,
    ):
        yield

    def emit(
        self,
        *args,
        **kwargs,
    ) -> None:
        return None


def _runtime(
    tmp_path: Path,
    backend: Any,
) -> StrictInteractiveCodingDoerRuntime:
    runtime = object.__new__(
        StrictInteractiveCodingDoerRuntime
    )

    runtime.workspace = tmp_path
    runtime.backend = backend

    runtime._current_checks = []

    runtime.executor = SimpleNamespace(
        report=FakeReport()
    )

    runtime.progress = FakeProgress()
    runtime._visible_step = 1

    runtime.index = FakeIndex()
    runtime.git = FakeGit()
    runtime.mechanical = FakeMechanical()

    runtime.capabilities = (
        ProviderCapabilities()
    )

    # Normally populated by run().
    runtime._requires_mutation = True
    runtime._requires_command = False

    return runtime


def _record_real_write(
    runtime: StrictInteractiveCodingDoerRuntime,
    relative: str,
    content: str,
) -> dict[str, Any]:
    target = (
        Path(runtime.workspace)
        / relative
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        content,
        encoding="utf-8",
    )

    data = target.read_bytes()

    evidence = FileEvidence(
        path=relative,
        size=len(data),
        sha256=hashlib.sha256(
            data
        ).hexdigest(),
    )

    runtime.executor.report.files.append(
        evidence
    )

    return {
        "status": "written",
        "file": {
            "path": evidence.path,
            "size": evidence.size,
            "sha256": evidence.sha256,
        },
    }


def _single_file_prompt(
    relative: str,
) -> str:
    return f"""Create exactly one file:

{relative}

The first and only workspace-changing action must be:

write_file {relative}

Do not modify any other file.

Success means only that {relative} is created and is nonempty.
"""


def _fast_path(
    runtime: StrictInteractiveCodingDoerRuntime,
    prompt: str,
    observation: dict[str, Any],
):
    return (
        runtime
        ._deterministic_single_file_write_verdict(
            prompt,
            observation,
        )
    )


def test_exact_single_file_write_can_finish_without_llm_verifier(
    tmp_path: Path,
) -> None:
    backend = NeverBackend()

    runtime = _runtime(
        tmp_path,
        backend,
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# Navier-Stokes\n",
    )

    verdict = runtime._verify(
        _single_file_prompt(relative),
        (
            "Create exactly one file: "
            + relative
        ),
        [
            relative
            + " exists and is nonempty",
        ],
        [],
        observation,
    )

    assert backend.calls == 0

    assert verdict["goal_met"] is True
    assert verdict["confidence"] == 1

    assert (
        verdict["missing_requirements"]
        == []
    )

    assert (
        verdict["next_instruction"]
        == ""
    )

    assert (
        verdict["verification_mode"]
        == "deterministic_single_file_write"
    )


def test_fast_path_rejects_multiple_recorded_file_writes(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    _record_real_write(
        runtime,
        "research/extra.md",
        "# extra\n",
    )

    assert (
        _fast_path(
            runtime,
            _single_file_prompt(
                relative
            ),
            observation,
        )
        is None
    )


def test_fast_path_rejects_evidence_path_mismatch(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    observation = _record_real_write(
        runtime,
        "research/other.md",
        "# other\n",
    )

    assert (
        _fast_path(
            runtime,
            _single_file_prompt(
                "research/problem_statement.md"
            ),
            observation,
        )
        is None
    )


def test_fast_path_rejects_tampered_file_after_evidence(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# original\n",
    )

    (
        tmp_path
        / relative
    ).write_text(
        "# changed later\n",
        encoding="utf-8",
    )

    assert (
        _fast_path(
            runtime,
            _single_file_prompt(
                relative
            ),
            observation,
        )
        is None
    )


def test_fast_path_rejects_empty_file(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "",
    )

    assert (
        _fast_path(
            runtime,
            _single_file_prompt(
                relative
            ),
            observation,
        )
        is None
    )


def test_fast_path_rejects_deterministic_checks(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    runtime._current_checks = [
        {
            "type": "file_contains",
            "path": relative,
            "text": "target",
        }
    ]

    assert (
        _fast_path(
            runtime,
            _single_file_prompt(
                relative
            ),
            observation,
        )
        is None
    )


def test_fast_path_rejects_command_required_contract(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = "hello.py"

    observation = _record_real_write(
        runtime,
        relative,
        'print("ok")\n',
    )

    runtime._requires_command = True

    assert (
        _fast_path(
            runtime,
            (
                _single_file_prompt(
                    relative
                )
                + "\nThen run hello.py "
                "and verify its output.\n"
            ),
            observation,
        )
        is None
    )


def test_fast_path_rejects_non_explicit_single_file_contract(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    assert (
        _fast_path(
            runtime,
            f"Create {relative}",
            observation,
        )
        is None
    )


def test_declined_fast_path_falls_through_to_semantic_verifier(
    tmp_path: Path,
) -> None:
    backend = FailingBackend()

    runtime = _runtime(
        tmp_path,
        backend,
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    # Deliberately does not satisfy the explicit
    # "Create exactly one file:" fast-path contract.
    verdict = runtime._verify(
        f"Create {relative}",
        "",
        [],
        [],
        observation,
    )

    assert backend.calls == 1

    assert verdict["goal_met"] is False

    assert any(
        "Verifier failure"
        in str(item)
        for item in verdict[
            "missing_requirements"
        ]
    )


def test_command_required_contract_reaches_semantic_verifier(
    tmp_path: Path,
) -> None:
    backend = FailingBackend()

    runtime = _runtime(
        tmp_path,
        backend,
    )

    relative = "hello.py"

    observation = _record_real_write(
        runtime,
        relative,
        'print("ok")\n',
    )

    runtime._requires_command = True

    verdict = runtime._verify(
        (
            _single_file_prompt(
                relative
            )
            + "\nThen run hello.py "
            "and verify its output.\n"
        ),
        "",
        [],
        [],
        observation,
    )

    assert backend.calls == 1
    assert verdict["goal_met"] is False



class PassingMechanicalChecks:
    def __init__(
        self,
        results,
    ) -> None:
        self.results = list(results)
        self.calls = 0

    def verify(
        self,
        checks,
        *,
        command_observations=(),
    ):
        self.calls += 1
        return {
            "passed": True,
            "results": [
                {
                    "check": check,
                    "passed": True,
                    "detail": "passed",
                }
                for check in checks
            ],
        }


def _passed_mechanical(
    checks,
):
    return {
        "passed": True,
        "results": [
            {
                "check": check,
                "passed": True,
                "detail": "passed",
            }
            for check in checks
        ],
    }


def test_passed_same_file_contains_check_can_finish_before_semantic_verifier(
    tmp_path: Path,
) -> None:
    backend = NeverBackend()

    runtime = _runtime(
        tmp_path,
        backend,
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\nrequired marker\n",
    )

    runtime._current_checks = [
        {
            "type": "contains",
            "path": relative,
            "text": "required marker",
        }
    ]

    runtime.mechanical = (
        PassingMechanicalChecks(
            runtime._current_checks
        )
    )

    verdict = runtime._verify(
        _single_file_prompt(
            relative
        ),
        "",
        [],
        [],
        observation,
    )

    assert backend.calls == 0
    assert runtime.mechanical.calls == 1
    assert verdict["goal_met"] is True
    assert (
        verdict["verification_mode"]
        == "deterministic_single_file_write"
    )
    assert (
        verdict["mechanical_verification"][
            "passed"
        ]
        is True
    )


def test_passed_same_file_exists_check_can_finish_before_semantic_verifier(
    tmp_path: Path,
) -> None:
    backend = NeverBackend()

    runtime = _runtime(
        tmp_path,
        backend,
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    runtime._current_checks = [
        {
            "type": "file_exists",
            "path": relative,
        }
    ]

    runtime.mechanical = (
        PassingMechanicalChecks(
            runtime._current_checks
        )
    )

    verdict = runtime._verify(
        _single_file_prompt(
            relative
        ),
        "",
        [],
        [],
        observation,
    )

    assert backend.calls == 0
    assert runtime.mechanical.calls == 1
    assert verdict["goal_met"] is True


def test_mechanical_fast_path_rejects_failed_check(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    check = {
        "type": "file_exists",
        "path": relative,
    }

    runtime._current_checks = [
        check
    ]

    mechanical = {
        "passed": False,
        "results": [
            {
                "check": check,
                "passed": False,
                "detail": "failed",
            }
        ],
    }

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=mechanical,
        )
        is None
    )


def test_mechanical_fast_path_rejects_check_on_other_file(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    check = {
        "type": "file_exists",
        "path": "research/other.md",
    }

    runtime._current_checks = [
        check
    ]

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                [check]
            ),
        )
        is None
    )


def test_mechanical_fast_path_rejects_unsupported_file_contains_alias(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    check = {
        "type": "file_contains",
        "path": relative,
        "text": "target",
    }

    runtime._current_checks = [
        check
    ]

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                [check]
            ),
        )
        is None
    )


def test_mechanical_fast_path_rejects_command_exit_zero(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    check = {
        "type": "command_exit_zero",
        "executable": "python",
    }

    runtime._current_checks = [
        check
    ]

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                [check]
            ),
        )
        is None
    )


def test_mechanical_fast_path_rejects_stdout_contains(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    check = {
        "type": "stdout_contains",
        "text": "ok",
    }

    runtime._current_checks = [
        check
    ]

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                [check]
            ),
        )
        is None
    )


def test_mechanical_fast_path_rejects_no_uncommitted_changes(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    check = {
        "type": "no_uncommitted_changes",
    }

    runtime._current_checks = [
        check
    ]

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                [check]
            ),
        )
        is None
    )


def test_mechanical_fast_path_rejects_result_check_mismatch(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/problem_statement.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# target\n",
    )

    check = {
        "type": "file_exists",
        "path": relative,
    }

    runtime._current_checks = [
        check
    ]

    mechanical = {
        "passed": True,
        "results": [
            {
                "check": {
                    "type": "contains",
                    "path": relative,
                    "text": "different",
                },
                "passed": True,
                "detail": "mismatched result",
            }
        ],
    }

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=mechanical,
        )
        is None
    )


def test_mechanical_fast_path_still_rejects_command_required_contract(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "hello.py"
    )

    observation = _record_real_write(
        runtime,
        relative,
        'print("ok")\n',
    )

    check = {
        "type": "file_exists",
        "path": relative,
    }

    runtime._current_checks = [
        check
    ]

    runtime._requires_command = True

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                [check]
            ),
        )
        is None
    )



def test_mechanical_fast_path_accepts_live_absolute_observation_and_evidence_paths(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/runtime_fastpath_proof.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# Runtime Fast-Path Proof\n\n"
        "Runtime fast-path proof.\n",
    )

    target = (
        tmp_path
        / relative
    ).resolve()

    original = (
        runtime.executor.report.files[0]
    )

    runtime.executor.report.files[0] = (
        FileEvidence(
            path=str(target),
            size=original.size,
            sha256=original.sha256,
        )
    )

    observation["file"]["path"] = str(
        target
    )

    checks = [
        {
            "type": "file_exists",
            "path": relative,
        },
        {
            "type": "contains",
            "path": relative,
            "text": "Runtime fast-path proof.",
        },
    ]

    runtime._current_checks = checks

    verdict = (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                checks
            ),
        )
    )

    assert verdict is not None
    assert verdict["goal_met"] is True
    assert (
        verdict["verification_mode"]
        == "deterministic_single_file_write"
    )
    assert (
        verdict["mechanical_verification"][
            "passed"
        ]
        is True
    )


def test_mechanical_fast_path_rejects_absolute_observation_outside_workspace(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/runtime_fastpath_proof.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# Runtime Fast-Path Proof\n",
    )

    outside = (
        tmp_path.parent
        / "outside-runtime-fastpath-proof.md"
    ).resolve()

    observation["file"]["path"] = str(
        outside
    )

    checks = [
        {
            "type": "file_exists",
            "path": relative,
        }
    ]

    runtime._current_checks = checks

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                checks
            ),
        )
        is None
    )


def test_mechanical_fast_path_rejects_absolute_evidence_outside_workspace(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/runtime_fastpath_proof.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# Runtime Fast-Path Proof\n",
    )

    original = (
        runtime.executor.report.files[0]
    )

    outside = (
        tmp_path.parent
        / "outside-runtime-fastpath-proof.md"
    ).resolve()

    runtime.executor.report.files[0] = (
        FileEvidence(
            path=str(outside),
            size=original.size,
            sha256=original.sha256,
        )
    )

    checks = [
        {
            "type": "file_exists",
            "path": relative,
        }
    ]

    runtime._current_checks = checks

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                checks
            ),
        )
        is None
    )


def test_mechanical_fast_path_rejects_check_path_escape(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    relative = (
        "research/runtime_fastpath_proof.md"
    )

    observation = _record_real_write(
        runtime,
        relative,
        "# Runtime Fast-Path Proof\n",
    )

    checks = [
        {
            "type": "file_exists",
            "path": "../runtime_fastpath_proof.md",
        }
    ]

    runtime._current_checks = checks

    assert (
        runtime
        ._deterministic_single_file_write_verdict(
            _single_file_prompt(
                relative
            ),
            observation,
            mechanical=_passed_mechanical(
                checks
            ),
        )
        is None
    )
