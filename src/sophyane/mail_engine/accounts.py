"""PostgreSQL-backed Nifdu mail accounts.

PostgreSQL is the sole durable database for this subsystem.

There is deliberately:
- no SQLite fallback
- no filesystem account database
- no Maildir account metadata
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

import psycopg
from psycopg import sql


_ITERATIONS = 310_000
_ALGORITHM = "pbkdf2-sha256"

_SCHEMA = re.compile(
    r"^[a-z][a-z0-9_]{0,62}$"
)


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


def mail_schema() -> str:
    value = os.environ.get(
        "SOPHYANE_MAIL_SCHEMA",
        "mail",
    ).strip().casefold()

    if not _SCHEMA.fullmatch(
        value
    ):
        raise ValueError(
            "invalid PostgreSQL mail schema"
        )

    return value


class AccountStore:
    """PostgreSQL-backed account registry for one mail domain."""

    def __init__(
        self,
        *,
        domain: str,
        dsn: str | None = None,
        schema: str | None = None,
    ) -> None:
        self.domain = str(
            domain
        ).strip().casefold()

        if (
            not self.domain
            or "."
            not in self.domain
        ):
            raise ValueError(
                "mail domain is invalid"
            )

        self.dsn = (
            str(
                dsn
            ).strip()
            if dsn
            else postgres_dsn()
        )

        self.schema = (
            str(
                schema
            ).strip().casefold()
            if schema
            else mail_schema()
        )

        if not _SCHEMA.fullmatch(
            self.schema
        ):
            raise ValueError(
                "invalid PostgreSQL mail schema"
            )

        self.ensure_schema()

    def connect(
        self,
    ) -> psycopg.Connection:
        return psycopg.connect(
            self.dsn,
            connect_timeout=3,
        )

    def ensure_schema(
        self,
    ) -> None:
        schema = sql.Identifier(
            self.schema
        )

        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE SCHEMA IF NOT EXISTS {}
                        """
                    ).format(
                        schema
                    )
                )

                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.accounts (
                            address TEXT PRIMARY KEY,
                            local_part TEXT NOT NULL,
                            domain TEXT NOT NULL,

                            algorithm TEXT NOT NULL,
                            iterations INTEGER NOT NULL,
                            salt BYTEA NOT NULL,
                            digest BYTEA NOT NULL,

                            enabled BOOLEAN NOT NULL
                                DEFAULT TRUE,

                            created_at TIMESTAMPTZ NOT NULL
                                DEFAULT now(),

                            updated_at TIMESTAMPTZ NOT NULL
                                DEFAULT now(),

                            UNIQUE (
                                local_part,
                                domain
                            )
                        )
                        """
                    ).format(
                        schema
                    )
                )

                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.mailboxes (
                            id BIGINT GENERATED ALWAYS AS IDENTITY
                                PRIMARY KEY,

                            account_address TEXT NOT NULL
                                REFERENCES {}.accounts(address)
                                ON DELETE CASCADE,

                            name TEXT NOT NULL,

                            uid_validity BIGINT NOT NULL
                                DEFAULT 1,

                            uid_next BIGINT NOT NULL
                                DEFAULT 1,

                            created_at TIMESTAMPTZ NOT NULL
                                DEFAULT now(),

                            UNIQUE (
                                account_address,
                                name
                            ),

                            CHECK (
                                uid_validity >= 1
                            ),

                            CHECK (
                                uid_next >= 1
                            )
                        )
                        """
                    ).format(
                        schema,
                        schema,
                    )
                )

                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.messages (
                            id BIGINT GENERATED ALWAYS AS IDENTITY
                                PRIMARY KEY,

                            message_id TEXT NOT NULL,

                            envelope_sender TEXT NOT NULL,

                            raw_message BYTEA NOT NULL,

                            size_bytes BIGINT NOT NULL,

                            metadata JSONB NOT NULL
                                DEFAULT '{{}}'::jsonb,

                            created_at TIMESTAMPTZ NOT NULL
                                DEFAULT now(),

                            CHECK (
                                size_bytes >= 0
                            )
                        )
                        """
                    ).format(
                        schema
                    )
                )

                # RFC Message-ID is searchable but is not a PostgreSQL
                # identity key. Redelivery of a message may legitimately
                # contain the same RFC Message-ID.
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS
                        mail_messages_message_id_idx
                        ON {}.messages(message_id)
                        """
                    ).format(
                        schema
                    )
                )

                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS
                        {}.mailbox_messages (
                            mailbox_id BIGINT NOT NULL
                                REFERENCES {}.mailboxes(id)
                                ON DELETE CASCADE,

                            message_id BIGINT NOT NULL
                                REFERENCES {}.messages(id)
                                ON DELETE CASCADE,

                            uid BIGINT NOT NULL,

                            flags JSONB NOT NULL
                                DEFAULT '[]'::jsonb,

                            internal_date TIMESTAMPTZ NOT NULL
                                DEFAULT now(),

                            PRIMARY KEY (
                                mailbox_id,
                                uid
                            ),

                            UNIQUE (
                                mailbox_id,
                                message_id
                            ),

                            CHECK (
                                uid >= 1
                            )
                        )
                        """
                    ).format(
                        schema,
                        schema,
                        schema,
                    )
                )

                cursor.execute(
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS
                        mail_mailbox_messages_message_idx
                        ON {}.mailbox_messages(message_id)
                        """
                    ).format(
                        schema
                    )
                )

    def normalize_address(
        self,
        value: str,
    ) -> str:
        address = str(
            value
            or ""
        ).strip().casefold()

        if "@" not in address:
            address = (
                address
                + "@"
                + self.domain
            )

        local, separator, domain = address.rpartition(
            "@"
        )

        if (
            not separator
            or not local
            or domain != self.domain
        ):
            raise ValueError(
                "account must belong to local mail domain"
            )

        if any(
            character.isspace()
            for character in local
        ):
            raise ValueError(
                "invalid account local part"
            )

        return address

    @staticmethod
    def _derive(
        password: str,
        salt: bytes,
        iterations: int,
    ) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256",
            str(
                password
            ).encode(
                "utf-8"
            ),
            salt,
            int(
                iterations
            ),
        )

    def create(
        self,
        address: str,
        password: str,
    ) -> str:
        normalized = self.normalize_address(
            address
        )

        if len(
            password
        ) < 8:
            raise ValueError(
                "mail password must contain at least 8 characters"
            )

        local = normalized.split(
            "@",
            1,
        )[0]

        salt = secrets.token_bytes(
            32
        )

        digest = self._derive(
            password,
            salt,
            _ITERATIONS,
        )

        schema = sql.Identifier(
            self.schema
        )

        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.accounts (
                            address,
                            local_part,
                            domain,
                            algorithm,
                            iterations,
                            salt,
                            digest,
                            enabled
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            TRUE
                        )
                        """
                    ).format(
                        schema
                    ),
                    (
                        normalized,
                        local,
                        self.domain,
                        _ALGORITHM,
                        _ITERATIONS,
                        salt,
                        digest,
                    ),
                )

                cursor.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.mailboxes (
                            account_address,
                            name
                        )
                        VALUES (
                            %s,
                            'INBOX'
                        )
                        ON CONFLICT (
                            account_address,
                            name
                        )
                        DO NOTHING
                        """
                    ).format(
                        schema
                    ),
                    (
                        normalized,
                    ),
                )

        return normalized

    def ensure(
        self,
        address: str,
        password: str,
    ) -> str:
        normalized = self.normalize_address(
            address
        )

        if self.exists(
            normalized
        ):
            return normalized

        return self.create(
            normalized,
            password,
        )

    def exists(
        self,
        address: str,
    ) -> bool:
        try:
            normalized = self.normalize_address(
                address
            )

        except ValueError:
            return False

        schema = sql.Identifier(
            self.schema
        )

        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT 1
                        FROM {}.accounts
                        WHERE address = %s
                          AND enabled = TRUE
                        """
                    ).format(
                        schema
                    ),
                    (
                        normalized,
                    ),
                )

                return (
                    cursor.fetchone()
                    is not None
                )

    def verify(
        self,
        address: str,
        password: str,
    ) -> bool:
        try:
            normalized = self.normalize_address(
                address
            )

        except ValueError:
            return False

        schema = sql.Identifier(
            self.schema
        )

        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT
                            algorithm,
                            iterations,
                            salt,
                            digest,
                            enabled
                        FROM {}.accounts
                        WHERE address = %s
                        """
                    ).format(
                        schema
                    ),
                    (
                        normalized,
                    ),
                )

                row = cursor.fetchone()

        if (
            row is None
            or not bool(
                row[4]
            )
            or str(
                row[0]
            ) != _ALGORITHM
        ):
            return False

        candidate = self._derive(
            password,
            bytes(
                row[2]
            ),
            int(
                row[1]
            ),
        )

        return hmac.compare_digest(
            candidate,
            bytes(
                row[3]
            ),
        )

    def list_accounts(
        self,
    ) -> list[str]:
        schema = sql.Identifier(
            self.schema
        )

        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT address
                        FROM {}.accounts
                        WHERE enabled = TRUE
                        ORDER BY address
                        """
                    ).format(
                        schema
                    )
                )

                return [
                    str(
                        row[0]
                    )
                    for row in cursor.fetchall()
                ]
