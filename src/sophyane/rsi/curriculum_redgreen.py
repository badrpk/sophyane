"""Repository-bound, sandboxed RED/GREEN preverification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import subprocess

from .curriculum import CurriculumTask
from .models import CommandResult
from .repository_inventory import RepositoryRecord
from .verification import confirm_red, run_command


@dataclass(frozen=True)
class RedGreenResult:
    status: str
    base_result: CommandResult | None = None
    candidate_results: tuple[CommandResult, ...] = ()
    evidence: tuple[str, ...] = ()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ("git", "-C", str(root), *args), text=True, stderr=subprocess.DEVNULL, timeout=3
    ).strip()


def _relative_path(root: Path, value: str) -> bool:
    pure = PurePosixPath(value)
    return (bool(value) and not pure.is_absolute() and "\\" not in value
            and all(part not in {"", ".", ".."} for part in value.split("/"))
            and (root / value).resolve().is_relative_to(root))


def _command_safe(command: tuple[str, ...], roots: tuple[Path, Path]) -> bool:
    if not isinstance(command, tuple) or not command or len(command) > 32 or any(
        not isinstance(arg, str) or not arg.strip() or len(arg) > 512 or "\x00" in arg for arg in command
    ):
        return False
    executable = Path(command[0]).name
    args = command[1:]
    if executable in {"python", "python3", "pytest"}:
        if executable != "pytest" and (len(args) < 2 or args[:2] != ("-m", "pytest")):
            return False
    elif executable == "cargo":
        if not args or args[0] != "test":
            return False
    elif executable == "go":
        if not args or args[0] != "test":
            return False
    elif executable == "npm":
        if not args or args[0] != "test":
            return False
    else:
        return False
    if command[0] != executable:
        return False
    for arg in args:
        if arg in {"-c", "--pyargs", "--override-ini", "--ignore-glob"}:
            return False
        if arg.startswith("-"):
            if "=" in arg and ("/" in arg or "\\" in arg):
                return False
            continue
        if arg in {"test", "pytest", "./..."}:
            continue
        if arg.startswith("/") or "\\" in arg or ".." in PurePosixPath(arg).parts:
            return False
        if "/" in arg or arg.endswith((".py", ".rs", ".go", ".js", ".ts")):
            if not all(_relative_path(root, arg) for root in roots):
                return False
    return True


def _validate(task: CurriculumTask, repository: RepositoryRecord, base: Path, candidate: Path) -> None:
    owner = Path(repository.path).resolve()
    if not task.repository_id or task.repository_id != repository.repo_id or task.base_commit != repository.commit:
        raise ValueError("task repository or base commit does not match inventory")
    if not owner.is_dir() or not base.is_dir() or not candidate.is_dir() or base == candidate:
        raise ValueError("repository worktrees are missing or overlap")
    common = _git(owner, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if any(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir") != common
           for root in (base, candidate)):
        raise ValueError("worktree belongs to another repository")
    if _git(owner, "rev-parse", "HEAD") != task.base_commit or _git(base, "rev-parse", "HEAD") != task.base_commit:
        raise ValueError("base worktree is stale")
    subprocess.run(("git", "-C", str(candidate), "merge-base", "--is-ancestor", task.base_commit, "HEAD"),
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    if _git(base, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("base worktree is mutable")
    if not task.red_failure_marker.strip() or not task.red_command or not task.green_commands or len(task.green_commands) > 16:
        raise ValueError("focused RED/GREEN command or marker missing")
    commands = (task.red_command, *task.green_commands)
    if any(not _command_safe(command, (base, candidate)) for command in commands):
        raise ValueError("unsafe verification command")
    if not task.editable_paths or any(not all(_relative_path(root, path) for root in (owner, base, candidate))
                                      for path in task.editable_paths):
        raise ValueError("unsafe editable path")
    for changed in filter(None, (_git(candidate, "diff", "--name-only", task.base_commit) + "\n"
                                 + _git(candidate, "ls-files", "--others", "--exclude-standard")).splitlines()):
        if changed not in task.editable_paths or not _relative_path(candidate, changed):
            raise ValueError("candidate changed a path outside task policy")


def preverify(
    task: CurriculumTask,
    repository: RepositoryRecord,
    base_worktree: Path,
    candidate_worktree: Path,
    *,
    timeout: int = 300,
    run=run_command,
) -> RedGreenResult:
    """Require the declared failure on the immutable base and success on the candidate."""
    base = Path(base_worktree).resolve()
    candidate = Path(candidate_worktree).resolve()
    try:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        _validate(task, repository, base, candidate)
        red = run(task.red_command, base, timeout=timeout)
        if red.exit_code == 124:
            return RedGreenResult("infrastructure_error", red, evidence=("base verification timed out",))
        if red.exit_code == 0:
            return RedGreenResult("already_green", red, evidence=("RED_ALREADY_GREEN",))
        if not confirm_red(red, task.red_failure_marker):
            return RedGreenResult("invalid_red", red, evidence=("base did not fail with declared marker",))
        commands = (task.red_command, *(cmd for cmd in task.green_commands if cmd != task.red_command))
        results: list[CommandResult] = []
        for command in commands:
            result = run(command, candidate, timeout=timeout)
            results.append(result)
            if result.exit_code == 124:
                return RedGreenResult("infrastructure_error", red, tuple(results), ("candidate verification timed out",))
            if result.exit_code != 0:
                return RedGreenResult("candidate_failed", red, tuple(results), ("candidate focused check failed",))
        return RedGreenResult("verified", red, tuple(results),
                              (f"base={task.base_commit}", f"red={red.digest}",
                               *(f"green={item.digest}" for item in results)))
    except (OSError, ValueError, subprocess.SubprocessError, PermissionError) as error:
        return RedGreenResult("infrastructure_error", evidence=(str(error),))
