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
            "semantic verifier must not run"
        )


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


class FakeIndex:
    def build(self):
        return SimpleNamespace(
            digest="TEST_DIGEST"
        )


class FakeGit:
    def status(self):
        return "TEST_STATUS"


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

    runtime.mechanical = FakeMechanical()
    runtime.index = FakeIndex()
    runtime.git = FakeGit()
    runtime.progress = FakeProgress()

    runtime._visible_step = 1
    runtime._requires_mutation = True
    runtime._requires_command = False

    runtime.capabilities = (
        ProviderCapabilities()
    )

    return runtime


def _record_write(
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
    digest = hashlib.sha256(data).hexdigest()

    evidence = FileEvidence(
        path=relative,
        size=len(data),
        sha256=digest,
    )

    runtime.executor.report.files.append(
        evidence
    )

    return {
        "status": "written",
        "file": {
            "path": relative,
            "size": len(data),
            "sha256": digest,
        },
    }


def _minimal_filesystem_prompt(
    relative: str,
) -> str:
    return (
        "Create exactly one file:\n\n"
        f"{relative}\n\n"
        "Success means only that "
        f"{relative} is created and is nonempty."
    )


def _write_only_filesystem_prompt(
    relative: str,
) -> str:
    return f"""Create exactly one file:

{relative}

The first and only workspace-changing action must be:

write_file {relative}

Do not modify any other file.

Success means only that {relative} is created and is nonempty.
"""


def _rich_n12_prompt() -> str:
    return """Create exactly one file:

research/dependency_graph.md

Read research/problem_statement.md first.

Write a compact mathematical dependency graph for the 3D incompressible Navier-Stokes global regularity problem.

Keep the file between 1800 and 3200 characters.

Required content:
- target theorem
- local smooth existence
- continuation/blow-up criterion
- energy identity
- vorticity equation and vortex stretching
- scaling and critical norms
- pressure/incompressibility role
- at least 3 plausible proof routes
- for each route: what is known, what remains unproved, and the exact obstruction
- shortest plausible implication chain from initial data to global smoothness
- explicit labels: ESTABLISHED, CONDITIONAL, OPEN, FALSE-LEAD
- no claim of solving the Millennium problem
- no invented theorem names or citations

Use dense bullets and arrows rather than long prose.

Success means only that research/dependency_graph.md is created, nonempty, and satisfies the above structure.
"""


def test_minimal_filesystem_only_contract_still_completes(
    tmp_path: Path,
) -> None:
    backend = NeverBackend()
    runtime = _runtime(tmp_path, backend)

    relative = "research/example.md"

    observation = _record_write(
        runtime,
        relative,
        "content\n",
    )

    verdict = runtime._verify(
        _minimal_filesystem_prompt(relative),
        "",
        [],
        [],
        observation,
    )

    assert backend.calls == 0
    assert verdict["goal_met"] is True

    assert (
        verdict["verification_mode"]
        == "deterministic_single_file_write"
    )


def test_existing_write_only_contract_still_completes(
    tmp_path: Path,
) -> None:
    backend = NeverBackend()
    runtime = _runtime(tmp_path, backend)

    relative = "research/example.md"

    observation = _record_write(
        runtime,
        relative,
        "content\n",
    )

    verdict = runtime._verify(
        _write_only_filesystem_prompt(relative),
        "",
        [],
        [],
        observation,
    )

    assert backend.calls == 0
    assert verdict["goal_met"] is True

    assert (
        verdict["verification_mode"]
        == "deterministic_single_file_write"
    )


def test_rich_exact_single_file_contract_is_not_certified_by_filesystem_only(
    tmp_path: Path,
) -> None:
    backend = NeverBackend()
    runtime = _runtime(tmp_path, backend)

    relative = "research/dependency_graph.md"

    observation = _record_write(
        runtime,
        relative,
        "# generated research map\n",
    )

    verdict = runtime._verify(
        _rich_n12_prompt(),
        "",
        [],
        [],
        observation,
    )

    assert backend.calls == 0
    assert verdict["goal_met"] is False
    assert verdict["confidence"] == 1

    assert (
        verdict["verification_mode"]
        == "deterministic_single_file_content_unverified"
    )

    assert verdict["missing_requirements"]

    assert "content" in (
        " ".join(
            verdict["missing_requirements"]
        ).lower()
    )


def test_rich_prompt_remains_exact_single_file_for_planner_fail_closed_scope(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        NeverBackend(),
    )

    assert (
        runtime
        ._explicit_single_file_contract_path(
            _rich_n12_prompt()
        )
        == "research/dependency_graph.md"
    )


def test_extra_substantive_sentence_disqualifies_positive_completion(
    tmp_path: Path,
) -> None:
    backend = NeverBackend()
    runtime = _runtime(tmp_path, backend)

    relative = "research/example.md"

    prompt = (
        "Create exactly one file:\n\n"
        f"{relative}\n\n"
        "Explain the mathematical argument rigorously.\n\n"
        "Success means only that "
        f"{relative} is created and is nonempty."
    )

    observation = _record_write(
        runtime,
        relative,
        "some argument\n",
    )

    verdict = runtime._verify(
        prompt,
        "",
        [],
        [],
        observation,
    )

    assert backend.calls == 0
    assert verdict["goal_met"] is False

    assert (
        verdict["verification_mode"]
        == "deterministic_single_file_content_unverified"
    )
