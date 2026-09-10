"""Enterprise PostgreSQL foundation.

Shared cross-domain schemas only.
Specialist repositories own their business-domain services.
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

CORE_SCHEMAS = (
    "platform",
    "identity",
    "iam",
    "audit",
    "integration",
)

CORE_COMPONENT = "enterprise-core"
CORE_VERSION = 2

FINANCE_COMPONENT = "finance-core"
FINANCE_VERSION = 1


def postgres_dsn() -> str:
    explicit = os.environ.get(
        "SOPHYANE_POSTGRES_DSN",
        "",
    ).strip()

    if explicit:
        return explicit

    prefix = os.environ.get(
        "PREFIX",
        "/data/data/com.termux/files/usr",
    )

    return (
        f"host={prefix}/tmp "
        "port=5432 "
        "dbname=sophyane"
    )


class EnterprisePostgres:
    def __init__(
        self,
        dsn: str | None = None,
    ) -> None:
        self.dsn = (
            str(dsn).strip()
            if dsn
            else postgres_dsn()
        )

    def connect(self):
        return psycopg.connect(
            self.dsn,
            row_factory=dict_row,
            connect_timeout=3,
        )

    @contextmanager
    def tenant_transaction(
        self,
        tenant_id: str,
    ):
        normalized_tenant_id = str(
            UUID(str(tenant_id))
        )

        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT set_config(
                        'sophyane.tenant_id',
                        %s,
                        true
                    )
                    """,
                    (normalized_tenant_id,),
                )

                yield cursor

    def health(self) -> dict[str, Any]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_database() AS database,
                        current_user AS user,
                        current_setting(
                            'server_version'
                        ) AS server_version
                    """
                )

                row = cursor.fetchone()

        return {
            "ok": True,
            **dict(row),
        }

    def ensure_core(self) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE EXTENSION IF NOT EXISTS pgcrypto"
                )

                for name in CORE_SCHEMAS:
                    if not _SCHEMA.fullmatch(name):
                        raise ValueError(
                            f"invalid schema: {name}"
                        )

                    cursor.execute(
                        sql.SQL(
                            "CREATE SCHEMA IF NOT EXISTS {}"
                        ).format(
                            sql.Identifier(name)
                        )
                    )

                self._ensure_platform(cursor)
                self._ensure_identity(cursor)
                self._ensure_iam(cursor)
                self._ensure_audit(cursor)
                self._ensure_integration(cursor)
                self._upgrade_core(cursor)
                finance_version = (
                    self._current_finance_version(cursor)
                )
                self._ensure_finance(cursor)
                self._record_finance_version(
                    cursor,
                    finance_version,
                )

    @staticmethod
    def _current_core_version(cursor) -> int:
        cursor.execute(
            """
            SELECT version
            FROM platform.schema_versions
            WHERE component = %s
            """,
            (CORE_COMPONENT,),
        )
        row = cursor.fetchone()

        if not row:
            return 1

        version = int(row["version"])

        if version > CORE_VERSION:
            raise RuntimeError(
                "enterprise core schema is newer than this runtime"
            )

        return version

    @classmethod
    def _upgrade_core(cls, cursor) -> None:
        version = cls._current_core_version(cursor)

        if version < 2:
            cls._upgrade_core_v1_to_v2(cursor)
            version = 2

        cursor.execute(
            """
            INSERT INTO platform.schema_versions (
                component,
                version
            )
            VALUES (%s, %s)
            ON CONFLICT (component)
            DO UPDATE SET
                version = EXCLUDED.version,
                applied_at = now()
            """,
            (CORE_COMPONENT, version),
        )

    @staticmethod
    def _upgrade_core_v1_to_v2(cursor) -> None:
        cursor.execute(
            """
            ALTER TABLE identity.parties
            ADD CONSTRAINT parties_tenant_id_id_key
            UNIQUE (tenant_id, id)
            """
        )

        cursor.execute(
            """
            ALTER TABLE identity.user_accounts
            DROP CONSTRAINT IF EXISTS
            user_accounts_party_id_fkey
            """
        )

        cursor.execute(
            """
            ALTER TABLE identity.user_accounts
            ADD CONSTRAINT user_accounts_tenant_party_fkey
            FOREIGN KEY (tenant_id, party_id)
            REFERENCES identity.parties (tenant_id, id)
            """
        )

        cursor.execute(
            """
            ALTER TABLE identity.user_accounts
            ADD CONSTRAINT user_accounts_tenant_id_id_key
            UNIQUE (tenant_id, id)
            """
        )

        cursor.execute(
            """
            ALTER TABLE iam.roles
            ADD CONSTRAINT roles_tenant_id_id_key
            UNIQUE (tenant_id, id)
            """
        )

        cursor.execute(
            """
            ALTER TABLE iam.user_roles
            ADD COLUMN tenant_id UUID
            """
        )

        cursor.execute(
            """
            UPDATE iam.user_roles ur
            SET tenant_id = u.tenant_id
            FROM identity.user_accounts u
            WHERE u.id = ur.user_id
            """
        )

        cursor.execute(
            """
            ALTER TABLE iam.user_roles
            ALTER COLUMN tenant_id SET NOT NULL
            """
        )

        cursor.execute(
            """
            ALTER TABLE iam.user_roles
            ADD CONSTRAINT user_roles_tenant_user_fkey
            FOREIGN KEY (tenant_id, user_id)
            REFERENCES identity.user_accounts (tenant_id, id)
            ON DELETE CASCADE
            """
        )

        cursor.execute(
            """
            ALTER TABLE iam.user_roles
            ADD CONSTRAINT user_roles_tenant_role_fkey
            FOREIGN KEY (tenant_id, role_id)
            REFERENCES iam.roles (tenant_id, id)
            ON DELETE CASCADE
            """
        )

        cursor.execute(
            """
            ALTER TABLE audit.events
            DROP CONSTRAINT IF EXISTS
            events_actor_party_id_fkey
            """
        )

        cursor.execute(
            """
            ALTER TABLE audit.events
            ADD CONSTRAINT events_tenant_actor_fkey
            FOREIGN KEY (tenant_id, actor_party_id)
            REFERENCES identity.parties (tenant_id, id)
            """
        )

        tenant_tables = (
            "platform.tenants",
            "identity.parties",
            "identity.user_accounts",
            "iam.roles",
            "iam.user_roles",
            "audit.events",
            "integration.idempotency_keys",
            "integration.outbox_events",
        )

        for table in tenant_tables:
            cursor.execute(
                sql.SQL(
                    "ALTER TABLE {} ENABLE ROW LEVEL SECURITY"
                ).format(
                    sql.SQL(table)
                )
            )
            cursor.execute(
                sql.SQL(
                    "ALTER TABLE {} FORCE ROW LEVEL SECURITY"
                ).format(
                    sql.SQL(table)
                )
            )

        direct_tenant_tables = (
            "identity.parties",
            "identity.user_accounts",
            "iam.roles",
            "iam.user_roles",
            "audit.events",
            "integration.idempotency_keys",
            "integration.outbox_events",
        )

        for table in direct_tenant_tables:
            schema_name, table_name = table.split(".", 1)
            policy_name = (
                f"{schema_name}_{table_name}_tenant_isolation"
            )

            cursor.execute(
                sql.SQL(
                    "DROP POLICY IF EXISTS {} ON {}"
                ).format(
                    sql.Identifier(policy_name),
                    sql.SQL(table),
                )
            )

            cursor.execute(
                sql.SQL(
                    """
                    CREATE POLICY {}
                    ON {}
                    USING (
                        tenant_id = NULLIF(
                            current_setting(
                                'sophyane.tenant_id',
                                true
                            ),
                            ''
                        )::uuid
                    )
                    WITH CHECK (
                        tenant_id = NULLIF(
                            current_setting(
                                'sophyane.tenant_id',
                                true
                            ),
                            ''
                        )::uuid
                    )
                    """
                ).format(
                    sql.Identifier(policy_name),
                    sql.SQL(table),
                )
            )

        cursor.execute(
            """
            DROP POLICY IF EXISTS
            platform_tenants_tenant_isolation
            ON platform.tenants
            """
        )

        cursor.execute(
            """
            CREATE POLICY
            platform_tenants_tenant_isolation
            ON platform.tenants
            USING (
                id = NULLIF(
                    current_setting(
                        'sophyane.tenant_id',
                        true
                    ),
                    ''
                )::uuid
            )
            WITH CHECK (
                id = NULLIF(
                    current_setting(
                        'sophyane.tenant_id',
                        true
                    ),
                    ''
                )::uuid
            )
            """
        )

    @staticmethod
    def _ensure_platform(cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            platform.schema_versions (
                component TEXT PRIMARY KEY,
                version INTEGER NOT NULL
                    CHECK (version >= 1),
                applied_at TIMESTAMPTZ NOT NULL
                    DEFAULT now()
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            platform.organizations (
                id UUID PRIMARY KEY
                    DEFAULT gen_random_uuid(),

                name TEXT NOT NULL,

                legal_name TEXT,

                metadata JSONB NOT NULL
                    DEFAULT '{}'::jsonb,

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                updated_at TIMESTAMPTZ NOT NULL
                    DEFAULT now()
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            platform.tenants (
                id UUID PRIMARY KEY
                    DEFAULT gen_random_uuid(),

                organization_id UUID NOT NULL
                    REFERENCES
                    platform.organizations(id),

                slug TEXT NOT NULL UNIQUE,

                name TEXT NOT NULL,

                enabled BOOLEAN NOT NULL
                    DEFAULT TRUE,

                metadata JSONB NOT NULL
                    DEFAULT '{}'::jsonb,

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                updated_at TIMESTAMPTZ NOT NULL
                    DEFAULT now()
            )
            """
        )

    @staticmethod
    def _ensure_identity(cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            identity.parties (
                id UUID PRIMARY KEY
                    DEFAULT gen_random_uuid(),

                tenant_id UUID NOT NULL
                    REFERENCES platform.tenants(id),

                party_type TEXT NOT NULL
                    CHECK (
                        party_type IN (
                            'person',
                            'organization'
                        )
                    ),

                display_name TEXT NOT NULL,

                external_key TEXT,

                metadata JSONB NOT NULL
                    DEFAULT '{}'::jsonb,

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                updated_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                UNIQUE (
                    tenant_id,
                    external_key
                )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            identity.user_accounts (
                id UUID PRIMARY KEY
                    DEFAULT gen_random_uuid(),

                tenant_id UUID NOT NULL
                    REFERENCES platform.tenants(id),

                party_id UUID NOT NULL
                    REFERENCES identity.parties(id),

                username TEXT NOT NULL,

                email TEXT,

                enabled BOOLEAN NOT NULL
                    DEFAULT TRUE,

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                updated_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                UNIQUE (
                    tenant_id,
                    username
                )
            )
            """
        )

    @staticmethod
    def _ensure_iam(cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS iam.roles (
                id UUID PRIMARY KEY
                    DEFAULT gen_random_uuid(),

                tenant_id UUID NOT NULL
                    REFERENCES platform.tenants(id),

                name TEXT NOT NULL,

                description TEXT NOT NULL
                    DEFAULT '',

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                UNIQUE (
                    tenant_id,
                    name
                )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            iam.permissions (
                id UUID PRIMARY KEY
                    DEFAULT gen_random_uuid(),

                capability TEXT NOT NULL UNIQUE,

                description TEXT NOT NULL
                    DEFAULT '',

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now()
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            iam.role_permissions (
                role_id UUID NOT NULL
                    REFERENCES iam.roles(id)
                    ON DELETE CASCADE,

                permission_id UUID NOT NULL
                    REFERENCES iam.permissions(id)
                    ON DELETE CASCADE,

                PRIMARY KEY (
                    role_id,
                    permission_id
                )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            iam.user_roles (
                user_id UUID NOT NULL
                    REFERENCES
                    identity.user_accounts(id)
                    ON DELETE CASCADE,

                role_id UUID NOT NULL
                    REFERENCES iam.roles(id)
                    ON DELETE CASCADE,

                PRIMARY KEY (
                    user_id,
                    role_id
                )
            )
            """
        )

    @staticmethod
    def _ensure_audit(cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit.events (
                id UUID PRIMARY KEY
                    DEFAULT gen_random_uuid(),

                tenant_id UUID
                    REFERENCES platform.tenants(id),

                actor_party_id UUID
                    REFERENCES identity.parties(id),

                event_type TEXT NOT NULL,

                subject_type TEXT NOT NULL,

                subject_id TEXT NOT NULL,

                payload JSONB NOT NULL
                    DEFAULT '{}'::jsonb,

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now()
            )
            """
        )

        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
            audit.reject_event_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'audit.events is append-only';
            END
            $$
            """
        )

        cursor.execute(
            """
            DROP TRIGGER IF EXISTS
            audit_events_no_update
            ON audit.events
            """
        )

        cursor.execute(
            """
            CREATE TRIGGER
            audit_events_no_update
            BEFORE UPDATE OR DELETE
            ON audit.events
            FOR EACH ROW
            EXECUTE FUNCTION
            audit.reject_event_mutation()
            """
        )



    @staticmethod
    def _current_finance_version(cursor) -> int:
        cursor.execute(
            """
            SELECT version
            FROM platform.schema_versions
            WHERE component = %s
            """,
            (FINANCE_COMPONENT,),
        )
        row = cursor.fetchone()

        if not row:
            return 0

        version = int(row["version"])

        if version > FINANCE_VERSION:
            raise RuntimeError(
                "finance core schema is newer than this runtime"
            )

        return version

    @staticmethod
    def _record_finance_version(
        cursor,
        current_version: int,
    ) -> None:
        if current_version == FINANCE_VERSION:
            return

        if current_version != 0:
            raise RuntimeError(
                "unsupported finance core migration path"
            )

        cursor.execute(
            """
            INSERT INTO platform.schema_versions (
                component,
                version
            )
            VALUES (%s, %s)
            ON CONFLICT (component)
            DO NOTHING
            """,
            (
                FINANCE_COMPONENT,
                FINANCE_VERSION,
            ),
        )

        cursor.execute(
            """
            SELECT version
            FROM platform.schema_versions
            WHERE component = %s
            """,
            (FINANCE_COMPONENT,),
        )
        row = cursor.fetchone()

        if (
            not row
            or int(row["version"]) != FINANCE_VERSION
        ):
            raise RuntimeError(
                "finance core version registration failed"
            )

    @staticmethod
    def _ensure_finance(cursor) -> None:
        cursor.execute(
            """
            CREATE SCHEMA IF NOT EXISTS finance
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS finance.accounts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                party_id UUID,
                account_type TEXT NOT NULL,
                currency TEXT NOT NULL
                    CHECK (
                        currency ~ '^[A-Z]{3,8}$'
                    ),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (
                        status IN (
                            'active',
                            'frozen',
                            'closed'
                        )
                    ),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, id),
                FOREIGN KEY (tenant_id)
                    REFERENCES platform.tenants(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (
                    tenant_id,
                    party_id
                )
                    REFERENCES identity.parties(
                        tenant_id,
                        id
                    )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS finance.transactions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                transaction_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (
                        status IN (
                            'draft',
                            'posted',
                            'reversed'
                        )
                    ),
                external_reference TEXT,
                reversal_of UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                posted_at TIMESTAMPTZ,
                UNIQUE (tenant_id, id),
                UNIQUE (
                    tenant_id,
                    external_reference
                ),
                FOREIGN KEY (tenant_id)
                    REFERENCES platform.tenants(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (
                    tenant_id,
                    reversal_of
                )
                    REFERENCES finance.transactions(
                        tenant_id,
                        id
                    )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS finance.entries (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                transaction_id UUID NOT NULL,
                account_id UUID NOT NULL,
                side TEXT NOT NULL
                    CHECK (
                        side IN ('debit', 'credit')
                    ),
                amount_minor BIGINT NOT NULL
                    CHECK (
                        amount_minor > 0
                    ),
                currency TEXT NOT NULL
                    CHECK (
                        currency ~ '^[A-Z]{3,8}$'
                    ),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, id),
                FOREIGN KEY (
                    tenant_id,
                    transaction_id
                )
                    REFERENCES finance.transactions(
                        tenant_id,
                        id
                    )
                    ON DELETE CASCADE,
                FOREIGN KEY (
                    tenant_id,
                    account_id
                )
                    REFERENCES finance.accounts(
                        tenant_id,
                        id
                    )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS finance.holds (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                account_id UUID NOT NULL,
                amount_minor BIGINT NOT NULL
                    CHECK (
                        amount_minor > 0
                    ),
                currency TEXT NOT NULL
                    CHECK (
                        currency ~ '^[A-Z]{3,8}$'
                    ),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (
                        status IN (
                            'active',
                            'released',
                            'captured',
                            'expired'
                        )
                    ),
                reference TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                released_at TIMESTAMPTZ,
                UNIQUE (tenant_id, id),
                FOREIGN KEY (
                    tenant_id,
                    account_id
                )
                    REFERENCES finance.accounts(
                        tenant_id,
                        id
                    )
                    ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS finance.settlements (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                account_id UUID NOT NULL,
                amount_minor BIGINT NOT NULL
                    CHECK (
                        amount_minor > 0
                    ),
                currency TEXT NOT NULL
                    CHECK (
                        currency ~ '^[A-Z]{3,8}$'
                    ),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (
                        status IN (
                            'pending',
                            'settled',
                            'failed',
                            'reversed'
                        )
                    ),
                external_reference TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                settled_at TIMESTAMPTZ,
                UNIQUE (tenant_id, id),
                UNIQUE (
                    tenant_id,
                    external_reference
                ),
                FOREIGN KEY (
                    tenant_id,
                    account_id
                )
                    REFERENCES finance.accounts(
                        tenant_id,
                        id
                    )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS finance.payouts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                account_id UUID NOT NULL,
                amount_minor BIGINT NOT NULL
                    CHECK (
                        amount_minor > 0
                    ),
                currency TEXT NOT NULL
                    CHECK (
                        currency ~ '^[A-Z]{3,8}$'
                    ),
                status TEXT NOT NULL DEFAULT 'requested'
                    CHECK (
                        status IN (
                            'requested',
                            'reserved',
                            'submitted',
                            'paid',
                            'failed',
                            'cancelled'
                        )
                    ),
                provider TEXT,
                provider_reference TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ,
                UNIQUE (tenant_id, id),
                FOREIGN KEY (
                    tenant_id,
                    account_id
                )
                    REFERENCES finance.accounts(
                        tenant_id,
                        id
                    )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS finance.payment_attempts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                transaction_id UUID,
                provider TEXT NOT NULL,
                provider_reference TEXT,
                status TEXT NOT NULL DEFAULT 'created'
                    CHECK (
                        status IN (
                            'created',
                            'pending',
                            'verified',
                            'failed',
                            'cancelled'
                        )
                    ),
                evidence JSONB NOT NULL
                    DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                verified_at TIMESTAMPTZ,
                UNIQUE (tenant_id, id),
                UNIQUE (
                    tenant_id,
                    provider,
                    provider_reference
                ),
                FOREIGN KEY (
                    tenant_id,
                    transaction_id
                )
                    REFERENCES finance.transactions(
                        tenant_id,
                        id
                    )
            )
            """
        )

        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
            finance.reject_posted_entry_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                account_currency TEXT;
            BEGIN
                IF TG_OP IN ('UPDATE', 'DELETE')
                   AND EXISTS (
                        SELECT 1
                        FROM finance.transactions AS transaction
                        WHERE
                            transaction.id =
                                OLD.transaction_id
                            AND transaction.tenant_id =
                                OLD.tenant_id
                            AND transaction.status IN (
                                'posted',
                                'reversed'
                            )
                   )
                THEN
                    RAISE EXCEPTION
                        'posted financial journal is immutable';
                END IF;

                IF TG_OP IN ('INSERT', 'UPDATE')
                THEN
                    IF EXISTS (
                        SELECT 1
                        FROM finance.transactions AS transaction
                        WHERE
                            transaction.id =
                                NEW.transaction_id
                            AND transaction.tenant_id =
                                NEW.tenant_id
                            AND transaction.status IN (
                                'posted',
                                'reversed'
                            )
                    )
                    THEN
                        RAISE EXCEPTION
                            'posted financial journal is immutable';
                    END IF;

                    SELECT account.currency
                    INTO account_currency
                    FROM finance.accounts AS account
                    WHERE
                        account.id = NEW.account_id
                        AND account.tenant_id =
                            NEW.tenant_id;

                    IF account_currency IS NOT NULL
                       AND account_currency <> NEW.currency
                    THEN
                        RAISE EXCEPTION
                            'entry currency must match account currency';
                    END IF;
                END IF;

                IF TG_OP = 'DELETE'
                THEN
                    RETURN OLD;
                END IF;

                RETURN NEW;
            END
            $$
            """
        )

        cursor.execute(
            """
            DROP TRIGGER IF EXISTS
            finance_entries_no_posted_mutation
            ON finance.entries
            """
        )

        cursor.execute(
            """
            CREATE TRIGGER
            finance_entries_no_posted_mutation
            BEFORE INSERT OR UPDATE OR DELETE
            ON finance.entries
            FOR EACH ROW
            EXECUTE FUNCTION
            finance.reject_posted_entry_mutation()
            """
        )

        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
            finance.assert_transaction_balanced()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                entry_count BIGINT;
                unbalanced_currency TEXT;
            BEGIN
                IF TG_OP = 'INSERT'
                THEN
                    IF NEW.status <> 'draft'
                    THEN
                        RAISE EXCEPTION
                            'financial transaction must be created as draft';
                    END IF;

                    RETURN NEW;
                END IF;

                IF OLD.status IN ('posted', 'reversed')
                THEN
                    RAISE EXCEPTION
                        'posted financial transaction is immutable';
                END IF;

                IF NEW.status NOT IN ('draft', 'posted')
                THEN
                    RAISE EXCEPTION
                        'invalid financial transaction state transition';
                END IF;

                IF NEW.status = 'posted'
                   AND OLD.status IS DISTINCT FROM 'posted'
                THEN
                    SELECT COUNT(*)
                    INTO entry_count
                    FROM finance.entries
                    WHERE
                        tenant_id = NEW.tenant_id
                        AND transaction_id = NEW.id;

                    IF entry_count = 0
                    THEN
                        RAISE EXCEPTION
                            'financial transaction has no entries';
                    END IF;

                    SELECT currency
                    INTO unbalanced_currency
                    FROM finance.entries
                    WHERE
                        tenant_id = NEW.tenant_id
                        AND transaction_id = NEW.id
                    GROUP BY currency
                    HAVING
                        COALESCE(
                            SUM(amount_minor)
                            FILTER (
                                WHERE side = 'debit'
                            ),
                            0
                        )
                        <>
                        COALESCE(
                            SUM(amount_minor)
                            FILTER (
                                WHERE side = 'credit'
                            ),
                            0
                        )
                    LIMIT 1;

                    IF unbalanced_currency IS NOT NULL
                    THEN
                        RAISE EXCEPTION
                            'financial transaction is not balanced for currency %',
                            unbalanced_currency;
                    END IF;

                    NEW.posted_at = COALESCE(
                        NEW.posted_at,
                        now()
                    );
                END IF;

                RETURN NEW;
            END
            $$
            """
        )

        cursor.execute(
            """
            DROP TRIGGER IF EXISTS
            finance_transactions_balance_check
            ON finance.transactions
            """
        )

        cursor.execute(
            """
            CREATE TRIGGER
            finance_transactions_balance_check
            BEFORE INSERT OR UPDATE
            ON finance.transactions
            FOR EACH ROW
            EXECUTE FUNCTION
            finance.assert_transaction_balanced()
            """
        )

        tenant_tables = (
            "accounts",
            "transactions",
            "entries",
            "holds",
            "settlements",
            "payouts",
            "payment_attempts",
        )

        for table in tenant_tables:
            cursor.execute(
                f"""
                ALTER TABLE finance.{table}
                ENABLE ROW LEVEL SECURITY
                """
            )

            cursor.execute(
                f"""
                ALTER TABLE finance.{table}
                FORCE ROW LEVEL SECURITY
                """
            )

            policy = (
                f"finance_{table}_tenant_isolation"
            )

            cursor.execute(
                f"""
                DROP POLICY IF EXISTS
                {policy}
                ON finance.{table}
                """
            )

            cursor.execute(
                f"""
                CREATE POLICY
                {policy}
                ON finance.{table}
                USING (
                    tenant_id =
                    current_setting(
                        'sophyane.tenant_id',
                        true
                    )::uuid
                )
                WITH CHECK (
                    tenant_id =
                    current_setting(
                        'sophyane.tenant_id',
                        true
                    )::uuid
                )
                """
            )

        # Shared enterprise authorities:
        # integration.outbox_events
        # audit.events

    @staticmethod
    def _ensure_integration(cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            integration.idempotency_keys (
                tenant_id UUID NOT NULL
                    REFERENCES platform.tenants(id),

                scope TEXT NOT NULL,

                key TEXT NOT NULL,

                request_hash TEXT NOT NULL,

                response JSONB,

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                expires_at TIMESTAMPTZ,

                PRIMARY KEY (
                    tenant_id,
                    scope,
                    key
                )
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
            integration.outbox_events (
                id UUID PRIMARY KEY
                    DEFAULT gen_random_uuid(),

                tenant_id UUID NOT NULL
                    REFERENCES platform.tenants(id),

                topic TEXT NOT NULL,

                aggregate_type TEXT NOT NULL,

                aggregate_id TEXT NOT NULL,

                payload JSONB NOT NULL,

                created_at TIMESTAMPTZ NOT NULL
                    DEFAULT now(),

                published_at TIMESTAMPTZ,

                attempts INTEGER NOT NULL
                    DEFAULT 0
                    CHECK (attempts >= 0)
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            outbox_unpublished_idx
            ON integration.outbox_events (
                created_at
            )
            WHERE published_at IS NULL
            """
        )

