"""Safe startup update authority for Sophyane source installations.

The updater is deliberately conservative:

* only the official badrpk/sophyane origin is trusted;
* only clean ``main`` checkouts are automatically updated;
* only fast-forward public-main advances are accepted;
* offline/update failures never prevent Sophyane from starting;
* dependency or smoke-test failure rolls source back;
* operator/developer interrupts remain authoritative;
* successful updates re-exec Sophyane from the updated installation.

Set SOPHYANE_AUTO_UPDATE=0 to disable startup updates.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


_OFFICIAL_ORIGINS = {
    "https://github.com/badrpk/sophyane.git",
    "https://github.com/badrpk/sophyane",
    "git@github.com:badrpk/sophyane.git",
    "ssh://git@github.com/badrpk/sophyane.git",
}

_REEXEC_GUARD = "SOPHYANE_UPDATE_REEXEC"
_DISABLE_FLAG = "SOPHYANE_AUTO_UPDATE"


@dataclass(frozen=True)
class StartupUpdateResult:
    status: str
    local_head: str = ""
    remote_head: str = ""
    message: str = ""
    updated: bool = False
    reexec_required: bool = False


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float = 30.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _git(
    repo: Path,
    *args: str,
    timeout: float = 30.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        ("git", *args),
        cwd=repo,
        timeout=timeout,
        check=check,
    )


def _git_text(
    repo: Path,
    *args: str,
    timeout: float = 30.0,
) -> str:
    return _git(
        repo,
        *args,
        timeout=timeout,
    ).stdout.strip()


def _official_origin(repo: Path) -> bool:
    try:
        origin = _git_text(
            repo,
            "remote",
            "get-url",
            "origin",
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return False

    return origin.rstrip("/") in _OFFICIAL_ORIGINS


def _clean_worktree(repo: Path) -> bool:
    result = _git_text(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )

    return not result


def _branch(repo: Path) -> str:
    return _git_text(
        repo,
        "symbolic-ref",
        "--short",
        "-q",
        "HEAD",
    )


def _head(repo: Path) -> str:
    return _git_text(
        repo,
        "rev-parse",
        "HEAD",
    )


def _remote_main(
    repo: Path,
    *,
    timeout: float,
) -> str:
    output = _git_text(
        repo,
        "ls-remote",
        "origin",
        "refs/heads/main",
        timeout=timeout,
    )

    if not output:
        raise RuntimeError(
            "official origin returned no main ref"
        )

    return output.split()[0]


def _fetch_candidate(
    repo: Path,
    *,
    timeout: float,
) -> None:
    _git(
        repo,
        "fetch",
        "--quiet",
        "--no-tags",
        "origin",
        "refs/heads/main",
        timeout=timeout,
    )


def _is_fast_forward(
    repo: Path,
    local_head: str,
    remote_head: str,
) -> bool:
    result = _git(
        repo,
        "merge-base",
        "--is-ancestor",
        local_head,
        remote_head,
        check=False,
    )

    return result.returncode == 0


def _termux_environment(
    env: Mapping[str, str],
) -> bool:
    return str(
        env.get("PREFIX", "")
    ).startswith(
        "/data/data/com.termux/"
    )


def _load_system_manifest(
    repo: Path,
) -> dict[str, list[str]]:
    path = (
        repo
        / "system-dependencies.json"
    )

    if not path.is_file():
        return {}

    raw = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(raw, dict):
        raise ValueError(
            "system-dependencies.json "
            "must contain an object"
        )

    result: dict[str, list[str]] = {}

    for key, value in raw.items():
        if not isinstance(value, list):
            continue

        result[str(key)] = [
            str(item)
            for item in value
            if str(item).strip()
        ]

    return result


def _termux_package_installed(
    package: str,
) -> bool:
    if shutil.which("dpkg-query") is None:
        return False

    result = subprocess.run(
        [
            "dpkg-query",
            "-W",
            "-f=${Status}",
            package,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    return (
        result.returncode == 0
        and "install ok installed"
        in result.stdout
    )


def _sync_termux_dependencies(
    repo: Path,
    env: Mapping[str, str],
) -> None:
    if not _termux_environment(env):
        return

    pkg = shutil.which("pkg")

    if pkg is None:
        raise RuntimeError(
            "Termux pkg command is unavailable"
        )

    manifest = _load_system_manifest(
        repo
    )

    required = manifest.get(
        "termux",
        [],
    )

    missing = [
        package
        for package in required
        if not _termux_package_installed(
            package
        )
    ]

    if not missing:
        return

    subprocess.run(
        [
            pkg,
            "install",
            "-y",
            *missing,
        ],
        check=True,
        timeout=900,
    )


def _sync_python_dependencies(
    repo: Path,
) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "-e",
            ".",
        ],
        cwd=repo,
        check=True,
        timeout=1200,
    )


def _smoke_updated_install(
    repo: Path,
) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sophyane; "
                "from sophyane.race_runtime "
                "import AdaptiveRace; "
                "from sophyane.evolution.engine "
                "import EvolutionEngine; "
                "print('SOPHYANE_UPDATE_SMOKE=PASS')"
            ),
        ],
        cwd=repo,
        check=True,
        timeout=120,
        capture_output=True,
        text=True,
    )


def _rollback(
    repo: Path,
    old_head: str,
) -> None:
    _git(
        repo,
        "reset",
        "--hard",
        old_head,
    )

    # Best-effort restoration of the old package/dependency
    # declaration after the source rollback.
    try:
        _sync_python_dependencies(
            repo
        )
    except Exception:
        pass


def _reexec(
    env: Mapping[str, str],
) -> None:
    next_env = dict(env)
    next_env[_REEXEC_GUARD] = "1"

    os.execve(
        sys.executable,
        [
            sys.executable,
            "-m",
            "sophyane.cli_entry",
            *sys.argv[1:],
        ],
        next_env,
    )


def check_and_apply_startup_update(
    *,
    repo: Path | None = None,
    env: Mapping[str, str] | None = None,
    reexec: bool = True,
    network_timeout: float = 5.0,
) -> StartupUpdateResult:
    environment = (
        os.environ
        if env is None
        else env
    )

    if (
        environment.get(
            _DISABLE_FLAG,
            "1",
        ).strip().lower()
        in {
            "0",
            "false",
            "no",
            "off",
        }
    ):
        return StartupUpdateResult(
            status="disabled",
        )

    if environment.get(
        _REEXEC_GUARD
    ) == "1":
        return StartupUpdateResult(
            status="reexec_guard",
        )

    root = (
        _repo_root()
        if repo is None
        else Path(repo).resolve()
    )

    if not (
        root
        / ".git"
    ).exists():
        return StartupUpdateResult(
            status="unmanaged_install",
            message=(
                "automatic Git update requires "
                "a source checkout"
            ),
        )

    try:
        if not _official_origin(root):
            return StartupUpdateResult(
                status="untrusted_origin",
                message=(
                    "origin is not the official "
                    "badrpk/sophyane repository"
                ),
            )

        branch = _branch(root)

        if branch != "main":
            return StartupUpdateResult(
                status="non_main_branch",
                message=(
                    "developer branch preserved"
                ),
            )

        if not _clean_worktree(root):
            return StartupUpdateResult(
                status="dirty_worktree",
                message=(
                    "local modifications preserved"
                ),
            )

        local_head = _head(root)

        remote_head = _remote_main(
            root,
            timeout=network_timeout,
        )

        if local_head == remote_head:
            return StartupUpdateResult(
                status="up_to_date",
                local_head=local_head,
                remote_head=remote_head,
            )

        _fetch_candidate(
            root,
            timeout=max(
                network_timeout,
                30.0,
            ),
        )

        if not _is_fast_forward(
            root,
            local_head,
            remote_head,
        ):
            return StartupUpdateResult(
                status="non_fast_forward",
                local_head=local_head,
                remote_head=remote_head,
                message=(
                    "automatic update refused: "
                    "public main is not a "
                    "fast-forward descendant"
                ),
            )

        print(
            "◆ Sophyane update: "
            + local_head[:7]
            + " → "
            + remote_head[:7],
            file=sys.stderr,
            flush=True,
        )

        updated_source = False

        try:
            _git(
                root,
                "merge",
                "--ff-only",
                remote_head,
            )

            updated_source = True

            _sync_termux_dependencies(
                root,
                environment,
            )

            _sync_python_dependencies(
                root
            )

            _smoke_updated_install(
                root
            )

        except (
            Exception,
        ) as error:
            if updated_source:
                _rollback(
                    root,
                    local_head,
                )

            return StartupUpdateResult(
                status="rolled_back",
                local_head=local_head,
                remote_head=remote_head,
                message=(
                    type(error).__name__
                    + ": "
                    + str(error)
                ),
            )

        result = StartupUpdateResult(
            status="updated",
            local_head=local_head,
            remote_head=remote_head,
            updated=True,
            reexec_required=True,
        )

        print(
            "◆ Sophyane update verified.",
            file=sys.stderr,
            flush=True,
        )

        if reexec:
            _reexec(
                environment
            )

        return result

    except KeyboardInterrupt:
        raise

    except (
        OSError,
        subprocess.TimeoutExpired,
        subprocess.SubprocessError,
        RuntimeError,
        ValueError,
    ) as error:
        return StartupUpdateResult(
            status="update_unavailable",
            message=(
                type(error).__name__
                + ": "
                + str(error)
            ),
        )


def maybe_update_before_startup() -> StartupUpdateResult:
    """Run startup update without making availability fatal."""

    result = check_and_apply_startup_update()

    if result.status in {
        "rolled_back",
        "non_fast_forward",
    }:
        print(
            "◆ Sophyane update warning: "
            + result.message,
            file=sys.stderr,
            flush=True,
        )

    return result
