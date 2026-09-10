"""PostgreSQL coordination backend for Sophyane multi-agent execution.

PostgreSQL is authoritative for:
- registered agents;
- heartbeats;
- durable task queues;
- atomic task claiming;
- leases and crash recovery;
- inter-agent messages;
- lifecycle events.

Agent process memory is disposable. Durable coordination state is not.

LISTEN/NOTIFY may be added as a wake-up optimization later. Tables remain
authoritative so missed notifications cannot lose work.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from psycopg.types.json import Jsonb

from sophyane.enterprise.postgres import (
    EnterprisePostgres,
)


AgentState = Literal[
    "created",
    "starting",
    "running",
    "waiting",
    "paused",
    "completed",
    "failed",
    "stopped",
]

TaskState = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
]


SCHEMA = "agent_runtime"
COMPONENT = "multiagent-postgres"
VERSION = 1


@dataclass(frozen=True)
class ClaimedTask:
    task_id: str
    run_id: str | None
    task_type: str
    payload: dict[str, Any]
    priority: int
    attempts: int
    lease_owner: str
    lease_expires_at: Any


class PostgresMultiAgentStore:
    """Durable PostgreSQL coordination plane for Sophyane agents."""

    def __init__(
        self,
        postgres: EnterprisePostgres | None = None,
    ) -> None:
        self.postgres = postgres or EnterprisePostgres()

    def ensure_schema(self) -> None:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE SCHEMA IF NOT EXISTS agent_runtime
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runtime.schema_versions (
                        component TEXT PRIMARY KEY,
                        version INTEGER NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )

                cursor.execute(
                    """
                    SELECT version
                    FROM agent_runtime.schema_versions
                    WHERE component = %s
                    """,
                    (COMPONENT,),
                )
                row = cursor.fetchone()

                if row and int(row["version"]) > VERSION:
                    raise RuntimeError(
                        "multi-agent PostgreSQL schema is newer "
                        "than this runtime"
                    )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runtime.agents (
                        agent_id TEXT PRIMARY KEY,
                        role TEXT NOT NULL,
                        objective TEXT NOT NULL DEFAULT '',
                        state TEXT NOT NULL,
                        capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        worker_pid BIGINT,
                        worker_instance TEXT,
                        heartbeat_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        CHECK (
                            state IN (
                                'created',
                                'starting',
                                'running',
                                'waiting',
                                'paused',
                                'completed',
                                'failed',
                                'stopped'
                            )
                        )
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    agents_state_heartbeat_idx
                    ON agent_runtime.agents (
                        state,
                        heartbeat_at
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runtime.tasks (
                        task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        run_id TEXT,
                        task_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        state TEXT NOT NULL DEFAULT 'queued',
                        priority INTEGER NOT NULL DEFAULT 0,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        max_attempts INTEGER NOT NULL DEFAULT 3,
                        idempotency_key TEXT UNIQUE,
                        lease_owner TEXT,
                        lease_expires_at TIMESTAMPTZ,
                        last_error TEXT NOT NULL DEFAULT '',
                        result JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        started_at TIMESTAMPTZ,
                        finished_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        CHECK (
                            state IN (
                                'queued',
                                'running',
                                'completed',
                                'failed',
                                'cancelled'
                            )
                        ),
                        CHECK (max_attempts >= 1),
                        CHECK (attempts >= 0)
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    tasks_claim_idx
                    ON agent_runtime.tasks (
                        priority DESC,
                        available_at,
                        created_at
                    )
                    WHERE state = 'queued'
                    """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    tasks_lease_idx
                    ON agent_runtime.tasks (
                        lease_expires_at
                    )
                    WHERE state = 'running'
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runtime.messages (
                        message_id UUID PRIMARY KEY
                            DEFAULT gen_random_uuid(),
                        sender_id TEXT NOT NULL,
                        recipient_id TEXT NOT NULL,
                        topic TEXT NOT NULL DEFAULT '',
                        payload JSONB NOT NULL,
                        correlation_id TEXT,
                        idempotency_key TEXT UNIQUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        claimed_by TEXT,
                        claimed_at TIMESTAMPTZ,
                        consumed_at TIMESTAMPTZ
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    messages_recipient_pending_idx
                    ON agent_runtime.messages (
                        recipient_id,
                        created_at
                    )
                    WHERE consumed_at IS NULL
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runtime.events (
                        event_id BIGINT GENERATED ALWAYS AS IDENTITY
                            PRIMARY KEY,
                        agent_id TEXT,
                        event_type TEXT NOT NULL,
                        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    events_agent_time_idx
                    ON agent_runtime.events (
                        agent_id,
                        created_at
                    )
                    """
                )

                cursor.execute(
                    """
                    INSERT INTO agent_runtime.schema_versions (
                        component,
                        version
                    )
                    VALUES (%s, %s)
                    ON CONFLICT (component)
                    DO UPDATE SET
                        version = EXCLUDED.version,
                        applied_at = now()
                    """,
                    (
                        COMPONENT,
                        VERSION,
                    ),
                )

    def register_agent(
        self,
        agent_id: str,
        role: str,
        *,
        objective: str = "",
        capabilities: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        worker_pid: int | None = None,
        worker_instance: str | None = None,
        state: AgentState = "created",
    ) -> None:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_runtime.agents (
                        agent_id,
                        role,
                        objective,
                        state,
                        capabilities,
                        metadata,
                        worker_pid,
                        worker_instance,
                        heartbeat_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        CASE
                            WHEN %s IN ('starting', 'running', 'waiting')
                            THEN now()
                            ELSE NULL
                        END
                    )
                    ON CONFLICT (agent_id)
                    DO UPDATE SET
                        role = EXCLUDED.role,
                        objective = EXCLUDED.objective,
                        state = EXCLUDED.state,
                        capabilities = EXCLUDED.capabilities,
                        metadata = EXCLUDED.metadata,
                        worker_pid = EXCLUDED.worker_pid,
                        worker_instance = EXCLUDED.worker_instance,
                        heartbeat_at = EXCLUDED.heartbeat_at,
                        updated_at = now()
                    """,
                    (
                        agent_id,
                        role,
                        objective,
                        state,
                        Jsonb(capabilities or {}),
                        Jsonb(metadata or {}),
                        worker_pid,
                        worker_instance,
                        state,
                    ),
                )

    def heartbeat(
        self,
        agent_id: str,
        *,
        state: AgentState = "running",
        worker_pid: int | None = None,
        worker_instance: str | None = None,
    ) -> bool:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_runtime.agents
                    SET
                        state = %s,
                        heartbeat_at = now(),
                        worker_pid = COALESCE(%s, worker_pid),
                        worker_instance = COALESCE(
                            %s,
                            worker_instance
                        ),
                        updated_at = now()
                    WHERE agent_id = %s
                    """,
                    (
                        state,
                        worker_pid,
                        worker_instance,
                        agent_id,
                    ),
                )
                return cursor.rowcount == 1

    def enqueue_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        run_id: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> str:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                if idempotency_key:
                    cursor.execute(
                        """
                        INSERT INTO agent_runtime.tasks (
                            run_id,
                            task_type,
                            payload,
                            priority,
                            max_attempts,
                            idempotency_key
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (idempotency_key)
                        DO UPDATE SET
                            idempotency_key =
                                EXCLUDED.idempotency_key
                        RETURNING task_id
                        """,
                        (
                            run_id,
                            task_type,
                            Jsonb(payload),
                            int(priority),
                            max(1, int(max_attempts)),
                            idempotency_key,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO agent_runtime.tasks (
                            run_id,
                            task_type,
                            payload,
                            priority,
                            max_attempts
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING task_id
                        """,
                        (
                            run_id,
                            task_type,
                            Jsonb(payload),
                            int(priority),
                            max(1, int(max_attempts)),
                        ),
                    )

                row = cursor.fetchone()

        return str(row["task_id"])

    def claim_task(
        self,
        agent_id: str,
        *,
        lease_seconds: int = 120,
        task_types: tuple[str, ...] = (),
    ) -> ClaimedTask | None:
        lease_seconds = max(
            10,
            int(lease_seconds),
        )

        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                if task_types:
                    cursor.execute(
                        """
                        WITH candidate AS (
                            SELECT task_id
                            FROM agent_runtime.tasks
                            WHERE
                                state = 'queued'
                                AND available_at <= now()
                                AND attempts < max_attempts
                                AND task_type = ANY(%s)
                            ORDER BY
                                priority DESC,
                                created_at,
                                task_id
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE agent_runtime.tasks AS task
                        SET
                            state = 'running',
                            lease_owner = %s,
                            lease_expires_at =
                                now() + (%s * interval '1 second'),
                            attempts = task.attempts + 1,
                            started_at = COALESCE(
                                task.started_at,
                                now()
                            ),
                            updated_at = now()
                        FROM candidate
                        WHERE task.task_id = candidate.task_id
                        RETURNING task.*
                        """,
                        (
                            list(task_types),
                            agent_id,
                            lease_seconds,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        WITH candidate AS (
                            SELECT task_id
                            FROM agent_runtime.tasks
                            WHERE
                                state = 'queued'
                                AND available_at <= now()
                                AND attempts < max_attempts
                            ORDER BY
                                priority DESC,
                                created_at,
                                task_id
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE agent_runtime.tasks AS task
                        SET
                            state = 'running',
                            lease_owner = %s,
                            lease_expires_at =
                                now() + (%s * interval '1 second'),
                            attempts = task.attempts + 1,
                            started_at = COALESCE(
                                task.started_at,
                                now()
                            ),
                            updated_at = now()
                        FROM candidate
                        WHERE task.task_id = candidate.task_id
                        RETURNING task.*
                        """,
                        (
                            agent_id,
                            lease_seconds,
                        ),
                    )

                row = cursor.fetchone()

                if not row:
                    return None

                cursor.execute(
                    """
                    INSERT INTO agent_runtime.events (
                        agent_id,
                        event_type,
                        payload
                    )
                    VALUES (%s, 'task_claimed', %s)
                    """,
                    (
                        agent_id,
                        Jsonb(
                            {
                                "task_id": str(row["task_id"]),
                                "task_type": row["task_type"],
                            }
                        ),
                    ),
                )

        return ClaimedTask(
            task_id=str(row["task_id"]),
            run_id=row["run_id"],
            task_type=row["task_type"],
            payload=dict(row["payload"]),
            priority=int(row["priority"]),
            attempts=int(row["attempts"]),
            lease_owner=str(row["lease_owner"]),
            lease_expires_at=row["lease_expires_at"],
        )

    def renew_lease(
        self,
        task_id: str,
        agent_id: str,
        *,
        lease_seconds: int = 120,
    ) -> bool:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_runtime.tasks
                    SET
                        lease_expires_at =
                            now() + (%s * interval '1 second'),
                        updated_at = now()
                    WHERE
                        task_id = %s::uuid
                        AND state = 'running'
                        AND lease_owner = %s
                        AND lease_expires_at > now()
                    """,
                    (
                        max(10, int(lease_seconds)),
                        task_id,
                        agent_id,
                    ),
                )
                return cursor.rowcount == 1

    def complete_task(
        self,
        task_id: str,
        agent_id: str,
        result: dict[str, Any],
    ) -> bool:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_runtime.tasks
                    SET
                        state = 'completed',
                        result = %s,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        finished_at = now(),
                        updated_at = now()
                    WHERE
                        task_id = %s::uuid
                        AND state = 'running'
                        AND lease_owner = %s
                        AND lease_expires_at > now()
                    """,
                    (
                        Jsonb(result),
                        task_id,
                        agent_id,
                    ),
                )
                return cursor.rowcount == 1

    def fail_task(
        self,
        task_id: str,
        agent_id: str,
        error: str,
        *,
        retry_delay_seconds: int = 0,
    ) -> bool:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_runtime.tasks
                    SET
                        state = CASE
                            WHEN attempts < max_attempts
                            THEN 'queued'
                            ELSE 'failed'
                        END,
                        last_error = %s,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        available_at =
                            now() + (%s * interval '1 second'),
                        finished_at = CASE
                            WHEN attempts >= max_attempts
                            THEN now()
                            ELSE NULL
                        END,
                        updated_at = now()
                    WHERE
                        task_id = %s::uuid
                        AND state = 'running'
                        AND lease_owner = %s
                    """,
                    (
                        str(error)[:8000],
                        max(0, int(retry_delay_seconds)),
                        task_id,
                        agent_id,
                    ),
                )
                return cursor.rowcount == 1

    def requeue_expired_leases(self) -> int:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_runtime.tasks
                    SET
                        state = CASE
                            WHEN attempts < max_attempts
                            THEN 'queued'
                            ELSE 'failed'
                        END,
                        last_error = CASE
                            WHEN attempts < max_attempts
                            THEN 'worker lease expired; task requeued'
                            ELSE 'worker lease expired; retries exhausted'
                        END,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        available_at = now(),
                        finished_at = CASE
                            WHEN attempts >= max_attempts
                            THEN now()
                            ELSE NULL
                        END,
                        updated_at = now()
                    WHERE
                        state = 'running'
                        AND lease_expires_at <= now()
                    """
                )
                return int(cursor.rowcount)

    def send_message(
        self,
        sender_id: str,
        recipient_id: str,
        payload: dict[str, Any],
        *,
        topic: str = "",
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                if idempotency_key:
                    cursor.execute(
                        """
                        INSERT INTO agent_runtime.messages (
                            sender_id,
                            recipient_id,
                            topic,
                            payload,
                            correlation_id,
                            idempotency_key
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (idempotency_key)
                        DO UPDATE SET
                            idempotency_key =
                                EXCLUDED.idempotency_key
                        RETURNING message_id
                        """,
                        (
                            sender_id,
                            recipient_id,
                            topic,
                            Jsonb(payload),
                            correlation_id,
                            idempotency_key,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO agent_runtime.messages (
                            sender_id,
                            recipient_id,
                            topic,
                            payload,
                            correlation_id
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING message_id
                        """,
                        (
                            sender_id,
                            recipient_id,
                            topic,
                            Jsonb(payload),
                            correlation_id,
                        ),
                    )

                row = cursor.fetchone()

        return str(row["message_id"])

    def claim_messages(
        self,
        recipient_id: str,
        agent_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        limit = max(
            1,
            min(
                100,
                int(limit),
            ),
        )

        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH candidate AS (
                        SELECT message_id
                        FROM agent_runtime.messages
                        WHERE
                            recipient_id = %s
                            AND consumed_at IS NULL
                            AND claimed_by IS NULL
                        ORDER BY created_at, message_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                    )
                    UPDATE agent_runtime.messages AS message
                    SET
                        claimed_by = %s,
                        claimed_at = now()
                    FROM candidate
                    WHERE
                        message.message_id =
                            candidate.message_id
                    RETURNING message.*
                    """,
                    (
                        recipient_id,
                        limit,
                        agent_id,
                    ),
                )

                rows = cursor.fetchall()

        return [
            {
                **dict(row),
                "message_id": str(row["message_id"]),
                "payload": dict(row["payload"]),
            }
            for row in rows
        ]

    def consume_message(
        self,
        message_id: str,
        agent_id: str,
    ) -> bool:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_runtime.messages
                    SET consumed_at = now()
                    WHERE
                        message_id = %s::uuid
                        AND claimed_by = %s
                        AND consumed_at IS NULL
                    """,
                    (
                        message_id,
                        agent_id,
                    ),
                )
                return cursor.rowcount == 1

    def set_agent_state(
        self,
        agent_id: str,
        state: AgentState,
    ) -> bool:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_runtime.agents
                    SET
                        state = %s,
                        updated_at = now()
                    WHERE agent_id = %s
                    """,
                    (
                        state,
                        agent_id,
                    ),
                )
                return cursor.rowcount == 1

    def list_agents(
        self,
        *,
        state: AgentState | None = None,
    ) -> list[dict[str, Any]]:
        with self.postgres.connect() as connection:
            with connection.cursor() as cursor:
                if state:
                    cursor.execute(
                        """
                        SELECT *
                        FROM agent_runtime.agents
                        WHERE state = %s
                        ORDER BY created_at, agent_id
                        """,
                        (state,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT *
                        FROM agent_runtime.agents
                        ORDER BY created_at, agent_id
                        """
                    )

                rows = cursor.fetchall()

        return [
            {
                **dict(row),
                "capabilities": dict(row["capabilities"]),
                "metadata": dict(row["metadata"]),
            }
            for row in rows
        ]


def new_worker_instance() -> str:
    return f"worker-{uuid.uuid4().hex[:16]}"


__all__ = [
    "ClaimedTask",
    "PostgresMultiAgentStore",
    "new_worker_instance",
]
