import multiprocessing
import os
from pathlib import Path

from sophyane.repository_mutation_lease import (
    RepositoryMutationBusy,
    repository_mutation_lease,
    repository_mutation_lock_path,
)


def _attempt_lease(
    repository: str,
    state_home: str,
    output,
) -> None:
    os.environ["XDG_STATE_HOME"] = state_home

    try:
        with repository_mutation_lease(
            Path(repository),
        ):
            output.put("ACQUIRED")
    except RepositoryMutationBusy:
        output.put("BUSY")


def _acquire_then_exit(
    repository: str,
    state_home: str,
    ready,
) -> None:
    os.environ["XDG_STATE_HOME"] = state_home

    with repository_mutation_lease(
        Path(repository),
    ):
        ready.set()


def test_lock_path_is_deterministic_and_external(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv(
        "XDG_STATE_HOME",
        str(state_home),
    )

    repository = tmp_path / "repo"
    repository.mkdir()

    equivalent = repository / "." / ".." / "repo"

    first = repository_mutation_lock_path(
        repository,
    )
    second = repository_mutation_lock_path(
        equivalent,
    )

    assert first == second
    assert first.parent == (
        state_home
        / "sophyane"
        / "repository-mutation-locks"
    )

    resolved_repository = repository.resolve()
    resolved_lock = first.resolve()

    assert resolved_repository not in resolved_lock.parents
    assert resolved_lock != resolved_repository
    assert first.suffix == ".lock"


def test_same_process_can_reacquire_after_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "XDG_STATE_HOME",
        str(tmp_path / "state"),
    )

    repository = tmp_path / "repo"
    repository.mkdir()

    with repository_mutation_lease(repository):
        pass

    with repository_mutation_lease(repository):
        pass


def test_competing_process_for_same_repository_is_busy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv(
        "XDG_STATE_HOME",
        str(state_home),
    )

    repository = tmp_path / "repo"
    repository.mkdir()

    context = multiprocessing.get_context("fork")
    output = context.Queue()

    with repository_mutation_lease(repository):
        worker = context.Process(
            target=_attempt_lease,
            args=(
                str(repository),
                str(state_home),
                output,
            ),
        )
        worker.start()
        worker.join(10)

        assert worker.exitcode == 0
        assert output.get(timeout=2) == "BUSY"


def test_different_repositories_do_not_contend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv(
        "XDG_STATE_HOME",
        str(state_home),
    )

    first_repository = tmp_path / "repo-a"
    second_repository = tmp_path / "repo-b"

    first_repository.mkdir()
    second_repository.mkdir()

    context = multiprocessing.get_context("fork")
    output = context.Queue()

    with repository_mutation_lease(
        first_repository,
    ):
        worker = context.Process(
            target=_attempt_lease,
            args=(
                str(second_repository),
                str(state_home),
                output,
            ),
        )
        worker.start()
        worker.join(10)

        assert worker.exitcode == 0
        assert output.get(timeout=2) == "ACQUIRED"


def test_process_exit_releases_kernel_lease(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv(
        "XDG_STATE_HOME",
        str(state_home),
    )

    repository = tmp_path / "repo"
    repository.mkdir()

    context = multiprocessing.get_context("fork")
    ready = context.Event()

    worker = context.Process(
        target=_acquire_then_exit,
        args=(
            str(repository),
            str(state_home),
            ready,
        ),
    )

    worker.start()

    assert ready.wait(5)

    worker.join(10)
    assert worker.exitcode == 0

    # The child process is gone. Kernel flock ownership must therefore
    # have disappeared even though the lock file itself remains.
    with repository_mutation_lease(repository):
        pass
