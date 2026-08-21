"""HEAD-pinned authoritative baseline execution.

Unlike V2E's all-or-nothing topology executor, V2F executes the runnable
required subset for diagnostic evidence while preserving fail-closed status.

A target only receives PASS when:

* target HEAD matches its contract;
* no required validator is missing;
* no required validator is unavailable;
* all required validator runs pass.

No target patching, committing, or promotion occurs.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .badrpk_targets import TargetSpec
from .target_validation_contracts import (
    ResolvedValidationContract,
    TargetValidationContract,
    get_validation_contract,
    resolve_contract,
)
from .target_validation_topology import (
    ValidationNode,
    discover_validation_topology,
)
from .target_worktree import (
    abandon_target_worktree,
    create_target_worktree,
    target_head,
)


DEFAULT_TIMEOUT = 300


@dataclass(frozen=True)
class AuthoritativeRun:
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
class AuthoritativeBaselineResult:
    target_name: str
    source_head: str
    contract_head: str
    status: str
    missing: tuple[str, ...]
    unavailable: tuple[str, ...]
    runs: tuple[AuthoritativeRun, ...]
    message: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _relative(
    repo: Path,
    node: ValidationNode,
) -> Path:
    return node.cwd.resolve().relative_to(
        repo.resolve()
    )


def _display_relative(
    path: Path,
) -> str:
    if path == Path("."):
        return "."

    return path.as_posix()


def _execute(
    worktree: Path,
    repo: Path,
    node: ValidationNode,
    *,
    timeout: int,
) -> AuthoritativeRun:
    relative = _relative(
        repo,
        node,
    )

    cwd = (
        worktree
        / relative
    ).resolve()

    try:
        cwd.relative_to(
            worktree.resolve()
        )
    except ValueError as error:
        raise ValueError(
            f"validator cwd escaped worktree: {cwd}"
        ) from error

    try:
        completed = subprocess.run(
            node.argv,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )

        return AuthoritativeRun(
            kind=node.kind,
            relative_cwd=_display_relative(
                relative
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

        return AuthoritativeRun(
            kind=node.kind,
            relative_cwd=_display_relative(
                relative
            ),
            argv=node.argv,
            returncode=None,
            timed_out=True,
            stdout=stdout[-30000:],
            stderr=stderr[-30000:],
        )


def evaluate_authoritative_baseline(
    target: TargetSpec,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    contract: TargetValidationContract | None = None,
) -> AuthoritativeBaselineResult:
    source_head = target_head(
        target
    )

    contract = (
        contract
        if contract is not None
        else get_validation_contract(
            target.name
        )
    )

    if source_head != contract.source_head:
        return AuthoritativeBaselineResult(
            target_name=target.name,
            source_head=source_head,
            contract_head=contract.source_head,
            status="CONTRACT_HEAD_MISMATCH",
            missing=(),
            unavailable=(),
            runs=(),
            message=(
                "Target HEAD differs from authoritative "
                "validator contract"
            ),
        )

    topology = discover_validation_topology(
        target_name=target.name,
        repo=target.repo,
    )

    resolved = resolve_contract(
        topology,
        contract,
    )

    missing = tuple(
        (
            f"{item.kind}@"
            f"{item.relative_cwd}"
        )
        for item in resolved.missing
    )

    unavailable = tuple(
        (
            f"{node.kind}@"
            f"{_display_relative(_relative(target.repo, node))}: "
            f"{node.reason}"
        )
        for node in resolved.unavailable
    )

    worktree = None
    runs: list[AuthoritativeRun] = []

    try:
        if resolved.runnable:
            worktree = create_target_worktree(
                target
            )

            if target_head(
                target
            ) != source_head:
                raise RuntimeError(
                    "Target HEAD changed while starting "
                    "authoritative baseline"
                )

            for node in resolved.runnable:
                runs.append(
                    _execute(
                        worktree.path,
                        target.repo,
                        node,
                        timeout=timeout,
                    )
                )

        failures = tuple(
            run
            for run in runs
            if not run.passed
        )

        if missing:
            status = "CONTRACT_INCOMPLETE"
            message = (
                "One or more required validators "
                "were not rediscovered"
            )

        elif unavailable:
            status = "VALIDATION_UNAVAILABLE"
            message = (
                "Required validators remain unavailable; "
                "runnable subset executed diagnostically"
            )

        elif failures:
            status = "BASELINE_FAILED"
            message = (
                f"{len(failures)} authoritative "
                "validator(s) failed"
            )

        else:
            status = "PASS"
            message = (
                "All authoritative validators passed"
            )

        return AuthoritativeBaselineResult(
            target_name=target.name,
            source_head=source_head,
            contract_head=contract.source_head,
            status=status,
            missing=missing,
            unavailable=unavailable,
            runs=tuple(
                runs
            ),
            message=message,
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
                "CRITICAL: target HEAD changed during "
                "authoritative baseline"
            )
