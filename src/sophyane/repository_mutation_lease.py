"""Canonical external mutation lease for a repository checkout."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
from hashlib import sha256
import os
from pathlib import Path
from typing import Iterator, BinaryIO


class RepositoryMutationLeaseError(RuntimeError):
    """Base error for repository mutation lease failures."""


class RepositoryMutationBusy(RepositoryMutationLeaseError):
    """Raised when another process owns the repository mutation lease."""


def _state_home() -> Path:
    configured = os.environ.get(
        "XDG_STATE_HOME",
        "",
    ).strip()

    if configured:
        return Path(configured).expanduser()

    return Path.home() / ".local" / "state"


def _repository_identity(
    repository: Path,
) -> tuple[Path, str]:
    resolved = Path(repository).expanduser().resolve()

    digest = sha256(
        str(resolved).encode("utf-8")
    ).hexdigest()

    return resolved, digest


def repository_mutation_lock_path(
    repository: Path,
) -> Path:
    """Return the canonical external lock path for *repository*."""

    resolved, digest = _repository_identity(
        repository,
    )

    lock_directory = (
        _state_home()
        / "sophyane"
        / "repository-mutation-locks"
    )

    lock_path = lock_directory / f"{digest}.lock"

    # Fail closed if configuration somehow places state beneath the
    # repository being protected.
    resolved_lock = lock_path.expanduser().resolve()

    if (
        resolved_lock == resolved
        or resolved in resolved_lock.parents
    ):
        raise RepositoryMutationLeaseError(
            "repository mutation lock is inside repository"
        )

    return lock_path


@contextmanager
def repository_mutation_lease(
    repository: Path,
) -> Iterator[Path]:
    """Acquire the non-blocking mutation lease for *repository*."""

    lock_path = repository_mutation_lock_path(
        repository,
    )

    try:
        lock_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        handle: BinaryIO = lock_path.open("a+b")
    except OSError as error:
        raise RepositoryMutationLeaseError(
            f"cannot open repository mutation lock: {error}"
        ) from error

    acquired = False

    try:
        try:
            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
            acquired = True
        except BlockingIOError as error:
            raise RepositoryMutationBusy(
                "REPOSITORY_MUTATION_BUSY: "
                f"{Path(repository).expanduser().resolve()}"
            ) from error
        except OSError as error:
            if error.errno in (
                errno.EACCES,
                errno.EAGAIN,
            ):
                raise RepositoryMutationBusy(
                    "REPOSITORY_MUTATION_BUSY: "
                    f"{Path(repository).expanduser().resolve()}"
                ) from error

            raise RepositoryMutationLeaseError(
                f"cannot acquire repository mutation lock: {error}"
            ) from error

        yield lock_path

    finally:
        if acquired:
            try:
                fcntl.flock(
                    handle.fileno(),
                    fcntl.LOCK_UN,
                )
            except OSError:
                pass

        handle.close()


__all__ = [
    "RepositoryMutationBusy",
    "RepositoryMutationLeaseError",
    "repository_mutation_lease",
    "repository_mutation_lock_path",
]
