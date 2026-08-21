"""Verification and execution of target validators.

Validator discovery and validator executability are separate concepts.

V2C refuses PASS when:

* no validator was discovered;
* a discovered validator cannot be verified runnable;
* any executed validator fails or times out.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .target_policy import ValidatorSpec
from .python_validation_environment import (
    resolve_pytest_python,
)


DEFAULT_VALIDATION_TIMEOUT = 300


@dataclass(frozen=True)
class ValidatorCheck:
    spec: ValidatorSpec
    runnable: bool
    reason: str


@dataclass(frozen=True)
class ValidatorRun:
    name: str
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def passed(self) -> bool:
        return (
            not self.timed_out
            and self.returncode == 0
        )


def _which(command: str) -> str | None:
    return shutil.which(command)


def verify_validator(
    repo: Path,
    spec: ValidatorSpec,
) -> ValidatorCheck:
    """Verify that a discovered validator can be invoked."""

    repo = Path(repo).resolve()

    if not spec.argv:
        return ValidatorCheck(
            spec=spec,
            runnable=False,
            reason="empty validator argv",
        )

    if spec.name == "python-pytest":
        environment = resolve_pytest_python(
            repo=repo,
            cwd=repo,
            harness_repo=(
                Path.home()
                / "sophyane"
            ),
        )

        if environment is None:
            return ValidatorCheck(
                spec,
                False,
                (
                    "no discovered Python interpreter "
                    "can import pytest"
                ),
            )

        resolved_spec = ValidatorSpec(
            name=spec.name,
            argv=(
                str(environment.python),
                "-m",
                "pytest",
                "-q",
            ),
            reason=spec.reason,
        )

        return ValidatorCheck(
            resolved_spec,
            True,
            (
                f"{environment.source}: "
                f"{environment.reason}"
            ),
        )

    if spec.name == "npm-test":
        npm = _which("npm")

        if npm is None:
            return ValidatorCheck(
                spec,
                False,
                "npm unavailable",
            )

        package = repo / "package.json"

        try:
            data = json.loads(
                package.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return ValidatorCheck(
                spec,
                False,
                "package.json unreadable",
            )

        script = (
            data.get("scripts", {})
            .get("test")
        )

        if not isinstance(script, str):
            return ValidatorCheck(
                spec,
                False,
                "package.json has no test script",
            )

        script = script.strip()

        if not script:
            return ValidatorCheck(
                spec,
                False,
                "package.json test script is empty",
            )

        if (
            "no test specified"
            in script.casefold()
        ):
            return ValidatorCheck(
                spec,
                False,
                "package.json contains placeholder test script",
            )

        return ValidatorCheck(
            spec,
            True,
            "npm and package test script verified",
        )

    if spec.name == "gradle-test":
        wrapper = repo / "gradlew"

        if not wrapper.is_file():
            return ValidatorCheck(
                spec,
                False,
                "gradlew missing",
            )

        if not os.access(
            wrapper,
            os.X_OK,
        ):
            return ValidatorCheck(
                spec,
                False,
                "gradlew is not executable",
            )

        return ValidatorCheck(
            spec,
            True,
            "executable Gradle wrapper verified",
        )

    if spec.name == "cargo-test":
        if _which("cargo") is None:
            return ValidatorCheck(
                spec,
                False,
                "cargo unavailable",
            )

        return ValidatorCheck(
            spec,
            True,
            "cargo executable verified",
        )

    if spec.name == "go-test":
        if _which("go") is None:
            return ValidatorCheck(
                spec,
                False,
                "go unavailable",
            )

        return ValidatorCheck(
            spec,
            True,
            "go executable verified",
        )

    command = spec.argv[0]

    if command.startswith("./"):
        executable = repo / command[2:]

        if (
            executable.is_file()
            and os.access(
                executable,
                os.X_OK,
            )
        ):
            return ValidatorCheck(
                spec,
                True,
                "repository executable verified",
            )

    elif _which(command) is not None:
        return ValidatorCheck(
            spec,
            True,
            "command executable verified",
        )

    return ValidatorCheck(
        spec,
        False,
        f"validator executable unavailable: {command}",
    )


def verify_validators(
    repo: Path,
    validators: tuple[ValidatorSpec, ...],
) -> tuple[ValidatorCheck, ...]:
    return tuple(
        verify_validator(
            repo,
            validator,
        )
        for validator in validators
    )


def run_validator(
    repo: Path,
    check: ValidatorCheck,
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
) -> ValidatorRun:
    if not check.runnable:
        raise ValueError(
            f"Validator is not runnable: "
            f"{check.spec.name}: {check.reason}"
        )

    try:
        completed = subprocess.run(
            check.spec.argv,
            cwd=Path(repo).resolve(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )

    except subprocess.TimeoutExpired as error:
        stdout = (
            error.stdout
            if isinstance(error.stdout, str)
            else ""
        )

        stderr = (
            error.stderr
            if isinstance(error.stderr, str)
            else ""
        )

        return ValidatorRun(
            name=check.spec.name,
            argv=check.spec.argv,
            returncode=None,
            stdout=stdout[-20000:],
            stderr=stderr[-20000:],
            timed_out=True,
        )

    return ValidatorRun(
        name=check.spec.name,
        argv=check.spec.argv,
        returncode=completed.returncode,
        stdout=completed.stdout[-20000:],
        stderr=completed.stderr[-20000:],
        timed_out=False,
    )


def run_validators(
    repo: Path,
    checks: tuple[ValidatorCheck, ...],
    *,
    timeout: int = DEFAULT_VALIDATION_TIMEOUT,
) -> tuple[ValidatorRun, ...]:
    return tuple(
        run_validator(
            repo,
            check,
            timeout=timeout,
        )
        for check in checks
    )
