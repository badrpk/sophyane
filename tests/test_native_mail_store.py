from __future__ import annotations

from email.message import EmailMessage
import os
import uuid

import psycopg
from psycopg import sql

from sophyane.mail_engine.accounts import AccountStore
from sophyane.mail_engine.store import MailStore


def _drop_schema(
    dsn: str,
    schema: str,
) -> None:
    with psycopg.connect(
        dsn
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "DROP SCHEMA IF EXISTS {} CASCADE"
                ).format(
                    sql.Identifier(
                        schema
                    )
                )
            )


def test_account_hash_and_postgres_mail_round_trip(
    monkeypatch,
) -> None:
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

    schema = (
        "mail_store_test_"
        + uuid.uuid4().hex[:16]
    )

    monkeypatch.setenv(
        "SOPHYANE_MAIL_SCHEMA",
        schema,
    )

    try:
        accounts = AccountStore(
            domain="nifdu.com",
        )

        accounts.create(
            "owner@nifdu.com",
            "password-123",
        )

        assert accounts.exists(
            "owner@nifdu.com"
        )

        assert accounts.verify(
            "owner@nifdu.com",
            "password-123",
        )

        assert not accounts.verify(
            "owner@nifdu.com",
            "wrong-password",
        )

        store = MailStore(
            accounts,
        )

        message = EmailMessage()

        message[
            "From"
        ] = "outside@example.net"

        message[
            "To"
        ] = "owner@nifdu.com"

        message[
            "Subject"
        ] = "postgres-mail-round-trip"

        message.set_content(
            "real PostgreSQL mail durability proof"
        )

        store.deliver(
            sender="outside@example.net",
            recipients=[
                "owner@nifdu.com",
            ],
            data=message.as_bytes(),
        )

        assert store.count(
            "owner@nifdu.com"
        ) == 1

        rows = store.messages(
            "owner@nifdu.com"
        )

        assert len(
            rows
        ) == 1

        assert int(
            rows[
                0
            ][
                0
            ]
        ) == 1

        raw = rows[
            0
        ][
            2
        ]

        assert b"postgres-mail-round-trip" in raw
        assert b"real PostgreSQL mail durability proof" in raw

        with psycopg.connect(
            dsn
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT
                            uid_validity,
                            uid_next
                        FROM {}.mailboxes
                        WHERE account_address = %s
                          AND name = 'INBOX'
                        """
                    ).format(
                        sql.Identifier(
                            schema
                        )
                    ),
                    (
                        "owner@nifdu.com",
                    ),
                )

                row = cursor.fetchone()

        assert row is not None

        uid_validity, uid_next = row

        assert int(
            uid_validity
        ) == 1

        assert int(
            uid_next
        ) == 2

    finally:
        _drop_schema(
            dsn,
            schema,
        )
