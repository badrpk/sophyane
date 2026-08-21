"""Baseline validator execution in disposable target worktrees.

V2E executes only validator nodes already classified runnable by the
repository-wide validation topology.

The original repository is never used as validator cwd.
No patch is applied.
No commit is created.
The detached worktree is force-discarded after validation.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .badrpk_targets import TargetSpec
from .target_validation_topology import (
    ValidationNode,
    ValidationTopology,
)
from .target_worktree import (
    abandon_target_worktree,
    create_target_worktree,
    target_head,
)


DEFAULT_BASELINE_TIMEOUT = 300


@dataclass(frozen=True)
class BaselineRun:
    kind: str
    relative_cwd: str
    argv: tuple[str, ...]
    returncode: int | None
    timed_out: bool
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return (
            not self.timed_out
            and self.returncode == 0
        )


@dataclass(frozen=True)
class BaselineResult:
    target_name: str
    source_head: str
    status: str
    runs: tuple[BaselineRun, ...]
    unavailable: tuple[str, ...]
    message: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _relative_cwd(
    repo: Path,
    node: ValidationNode,
) -> Path:
    try:
        return node.cwd.resolve().relative_to(
            repo.resolve()
        )
    except ValueError as error:
        raise ValueError(
            f"validator cwd escapes target repository: "
            f"{node.cwd}"
        ) from error


def _run_node(
    worktree: Path,
    relative_cwd: Path,
    node: ValidationNode,
    *,
    timeout: int,
) -> BaselineRun:
    cwd = (
        worktree
        / relative_cwd
    ).resolve()

    try:
        cwd.relative_to(
            worktree.resolve()
        )
    except ValueError as error:
        raise ValueError(
            f"mapped validator cwd escapes worktree: {cwd}"
        ) from error

    if not cwd.is_dir():
        return BaselineRun(
            kind=node.kind,
            relative_cwd=str(
                relative_cwd
            ),
            argv=node.argv,
            returncode=None,
            timed_out=False,
            stdout="",
            stderr=(
                "validator cwd missing in detached worktree"
            ),
        )

    try:
        completed = subprocess.run(
            node.argv,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )

        return BaselineRun(
            kind=node.kind,
            relative_cwd=str(
                relative_cwd
            ),
            argv=node.argv,
            returncode=completed.returncode,
            timed_out=False,
            stdout=completed.stdout[-30000:],
            stderr=completed.stderr[-30000:],
        )

    except subprocess.TimeoutExpired as error:
        stdout = (
            error.stdout
            if isinstance(
                error.stdout,
                str,
            )
            else ""
        )

        stderr = (
            error.stderr
            if isinstance(
                error.stderr,
                str,
            )
            else ""
        )

        return BaselineRun(
            kind=node.kind,
            relative_cwd=str(
                relative_cwd
            ),
            argv=node.argv,
            returncode=None,
            timed_out=True,
            stdout=stdout[-30000:],
            stderr=stderr[-30000:],
        )


def execute_baseline(
    target: TargetSpec,
    topology: ValidationTopology,
    *,
    timeout: int = DEFAULT_BASELINE_TIMEOUT,
) -> BaselineResult:
    """Execute verified baseline validators in one detached worktree."""

    source_head = target_head(
        target
    )

    unavailable = tuple(
        (
            f"{node.kind}@"
            f"{node.cwd.relative_to(target.repo)}: "
            f"{node.reason}"
        )
        for node in topology.unavailable
    )

    if not topology.nodes:
        return BaselineResult(
            target_name=target.name,
            source_head=source_head,
            status="NO_VALIDATOR",
            runs=(),
            unavailable=(),
            message=(
                "No validator-bearing projects discovered"
            ),
        )

    # Fail closed. We do not call a partially runnable topology PASS.
    if unavailable:
        return BaselineResult(
            target_name=target.name,
            source_head=source_head,
            status="VALIDATION_UNAVAILABLE",
            runs=(),
            unavailable=unavailable,
            message=(
                "One or more discovered baseline validators "
                "are unavailable"
            ),
        )

    worktree = None

    try:
        worktree = create_target_worktree(
            target
        )

        if target_head(
            target
        ) != source_head:
            raise RuntimeError(
                "Target HEAD changed during baseline startup"
            )

        runs: list[BaselineRun] = []

        for node in topology.nodes:
            relative = _relative_cwd(
                target.repo,
                node,
            )

            runs.append(
                _run_node(
                    worktree.path,
                    relative,
                    node,
                    timeout=timeout,
                )
            )

        failures = tuple(
            run
            for run in runs
            if not run.passed
        )

        if failures:
            return BaselineResult(
                target_name=target.name,
                source_head=source_head,
                status="BASELINE_FAILED",
                runs=tuple(
                    runs
                ),
                unavailable=(),
                message=(
                    f"{len(failures)} baseline validator(s) failed"
                ),
            )

        return BaselineResult(
            target_name=target.name,
            source_head=source_head,
            status="PASS",
            runs=tuple(
                runs
            ),
            unavailable=(),
            message=(
                "All discovered baseline validators passed "
                "in disposable worktree"
            ),
        )

    finally:
        if worktree is not None:
            abandon_target_worktree(
                worktree
            )

        final_head = target_head(
            target
        )

        if final_head != source_head:
            raise RuntimeError(
                "CRITICAL: target HEAD changed during baseline"
            )
