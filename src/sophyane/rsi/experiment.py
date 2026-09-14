"""Frozen host-selected experiments; generated shell commands are not accepted."""
from dataclasses import dataclass
from .campaign import RedStatus
from .verification import run_command, confirm_red, passed
from .controller import protects_verification

@dataclass(frozen=True)
class ExperimentPlan:
    identifier: str
    focused: tuple[tuple[str, ...], ...]
    holdout: tuple[tuple[str, ...], ...]
    regression: tuple[tuple[str, ...], ...]
    expected_failure: str
    allowed_paths: frozenset[str]
    version: str = '1'
    timeout: float = 60

    def __post_init__(self):
        commands = self.focused + self.holdout + self.regression
        if (not all((self.focused, self.holdout, self.regression, self.expected_failure, self.allowed_paths, self.version))
            or not 0 < self.timeout <= 300 or len(commands) > 32
            or any(not isinstance(c, tuple) or not c or any(not isinstance(t, str) for t in c) for c in commands)
            or not protects_verification(self.allowed_paths, commands)):
            raise ValueError('Incomplete or unsafe frozen experiment policy')

@dataclass(frozen=True)
class ExperimentResult:
    red_status: RedStatus
    runs: tuple

class VerificationCancelled(RuntimeError):
    pass


class DeterministicExperimentRunner:
    def __init__(self, command_runner=None, cancelled=None):
        self.command_runner = command_runner or run_command
        self.cancelled = cancelled or (lambda: False)

    def _check_cancelled(self):
        if self.cancelled():
            raise VerificationCancelled('verification cancelled')

    def red(self, plan, path):
        runs = []
        for _ in range(2):
            self._check_cancelled()
            runs.append(
                self.command_runner(
                    plan.focused[0],
                    path,
                    timeout=plan.timeout,
                )
            )
        runs = tuple(runs)
        if len({r.exit_code for r in runs}) > 1:
            status = RedStatus.RED_FLAKY_OR_NONDETERMINISTIC
        elif all(confirm_red(r, plan.expected_failure) for r in runs):
            status = RedStatus.RED_CONFIRMED
        elif all(r.exit_code == 0 for r in runs):
            status = RedStatus.RED_ALREADY_GREEN
        else:
            status = RedStatus.RED_UNRELATED
        return ExperimentResult(status, runs)

    def checks(self, commands, path, timeout):
        runs = []
        for command in commands:
            self._check_cancelled()
            runs.append(
                self.command_runner(
                    command,
                    path,
                    timeout=timeout,
                )
            )
        return tuple(runs)
