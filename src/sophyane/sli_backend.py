"""Backend-neutral Sophyane Learning Intelligence access.

SQLite remains the default backend.

PostgreSQL is selected only when SOPHYANE_SLI_BACKEND is explicitly
set to ``postgres``. Merely having PostgreSQL configured or prepared
never changes runtime behavior.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import Any, Iterator

from sophyane import sli
from sophyane.config import load_config
from sophyane.sli_postgres import PostgresSLIStore


BACKEND_ENV = "SOPHYANE_SLI_BACKEND"

SQLITE_BACKEND = "sqlite"
POSTGRES_BACKEND = "postgres"

_ALLOWED = {
    SQLITE_BACKEND,
    POSTGRES_BACKEND,
}


def _atomic_learning_value(
    value: Any,
    *,
    source: str,
) -> bool:
    """Parse one explicit atomic-learning configuration value."""
    if isinstance(
        value,
        bool,
    ):
        return value

    normalized = str(
        value
        if value is not None
        else ""
    ).strip().lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "",
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    raise RuntimeError(
        "Unsupported atomic-learning value "
        f"{value!r} from {source}; expected "
        "true/false, 1/0, yes/no, or on/off."
    )


def atomic_learning_enabled() -> bool:
    """Return whether the PostgreSQL atomic learner path is enabled.

    Selection precedence is explicit and reversible:

    1. Non-empty SOPHYANE_SLI_ATOMIC_LEARNING environment value.
    2. Persistent ``sli_atomic_learning`` Sophyane config value.
    3. False when neither selector is configured.

    Schema presence alone never activates atomic learning.
    """
    environment_value = os.environ.get(
        "SOPHYANE_SLI_ATOMIC_LEARNING"
    )

    if (
        environment_value is not None
        and str(
            environment_value
        ).strip()
    ):
        return _atomic_learning_value(
            environment_value,
            source=(
                "SOPHYANE_SLI_ATOMIC_LEARNING"
            ),
        )

    try:
        config = load_config()
    except Exception:
        config = {}

    return _atomic_learning_value(
        config.get(
            "sli_atomic_learning",
            False,
        ),
        source=(
            "persistent sli_atomic_learning config"
        ),
    )


def selected_backend() -> str:
    """Return the selected SLI backend.

    Selection precedence is intentionally explicit and reversible:

    1. SOPHYANE_SLI_BACKEND environment variable, when non-empty.
    2. Persistent ``sli_backend`` value in Sophyane config.
    3. SQLite when neither selector is configured.

    Merely having PostgreSQL available never changes the runtime backend.
    """
    environment_value = (
        os.environ.get(
            BACKEND_ENV,
            "",
        )
        .strip()
        .lower()
    )

    if environment_value:
        value = environment_value

    else:
        try:
            config = load_config()
        except Exception:
            config = {}

        value = str(
            config.get(
                "sli_backend",
                SQLITE_BACKEND,
            )
            or SQLITE_BACKEND
        ).strip().lower()

    if not value:
        value = SQLITE_BACKEND

    if value not in _ALLOWED:
        raise RuntimeError(
            "Unsupported SLI backend "
            f"{value!r}; expected one of "
            f"{sorted(_ALLOWED)!r}."
        )

    return value


def backend_name() -> str:
    return selected_backend()


def postgres_store() -> PostgresSLIStore:
    return PostgresSLIStore(
        schema="sli"
    )


@contextmanager
def connect(
    path: Path | str | None = None,
) -> Iterator[Any]:
    """Yield the selected backend handle.

    Explicit SQLite paths always preserve the historical SQLite
    compatibility contract, regardless of environment selection.
    """
    if path is not None:
        with sli.connect(
            path
        ) as db:
            yield db

        return

    backend = selected_backend()

    if backend == SQLITE_BACKEND:
        with sli.connect() as db:
            yield db

        return

    store = postgres_store()

    if not store.schema_exists():
        raise RuntimeError(
            "PostgreSQL SLI backend selected but "
            "production schema 'sli' does not exist."
        )

    yield store


def atomic_learn_execution(
    db: Any,
    *,
    trace_id: str,
    payload_digest: str,
    memory: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(
        db,
        PostgresSLIStore,
    ):
        raise RuntimeError(
            "Atomic learner events require "
            "the PostgreSQL SLI backend."
        )

    return db.atomic_learn_execution(
        trace_id=trace_id,
        payload_digest=payload_digest,
        memory=memory,
        trace=trace,
    )


def record(
    db: Any,
    *,
    request: str,
    action: str,
    reward: float,
    state: str = "",
    result: str = "",
    confidence: float = 0.5,
    elapsed_seconds: float = 0.0,
    source_type: str = "unknown",
) -> int:
    if isinstance(
        db,
        PostgresSLIStore,
    ):
        return db.record(
            request=request,
            action=action,
            reward=reward,
            state=state,
            result=result,
            confidence=confidence,
            elapsed_seconds=elapsed_seconds,
            source_type=source_type,
        )

    return sli.record(
        db,
        request=request,
        action=action,
        reward=reward,
        state=state,
        result=result,
        confidence=confidence,
        elapsed_seconds=elapsed_seconds,
        source_type=source_type,
    )


def recommend_actions(
    db: Any,
    *,
    request: str,
    state: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    if isinstance(
        db,
        PostgresSLIStore,
    ):
        return db.recommend_actions(
            request=request,
            state=state,
            limit=limit,
        )

    return sli.recommend_actions(
        db,
        request=request,
        state=state,
        limit=limit,
    )


def stats(
    db: Any,
) -> dict[str, Any]:
    if isinstance(
        db,
        PostgresSLIStore,
    ):
        return db.stats()

    return sli.stats(
        db
    )


def store_trace(
    db: Any,
    payload: dict[str, Any],
) -> None:
    if isinstance(
        db,
        PostgresSLIStore,
    ):
        db.store_trace(
            payload
        )

        return

    sli.store_trace(
        db,
        payload,
    )


def list_traces(
    db: Any,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if isinstance(
        db,
        PostgresSLIStore,
    ):
        return db.list_traces(
            limit=limit
        )

    return sli.list_traces(
        db,
        limit=limit,
    )



def synchronize_rollback_mirror() -> dict[str, Any] | None:
    """Synchronize PostgreSQL learning into retained SQLite.

    SQLite needs no mirror operation because it is already the historical
    rollback store. PostgreSQL uses the existing append-only cutover
    synchronizer so the SQLite rollback copy follows every completed
    production learning event.

    Importing the cutover module lazily avoids a module-level dependency
    cycle between backend selection and cutover management.
    """
    if selected_backend() != POSTGRES_BACKEND:
        return None

    from sophyane.sli_cutover import (
        synchronize_postgres_to_sqlite,
    )

    return synchronize_postgres_to_sqlite(
        sqlite_path=sli.DB_PATH,
        store=postgres_store(),
    )
