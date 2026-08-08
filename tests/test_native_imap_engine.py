from __future__ import annotations

import asyncio
from email.message import EmailMessage
import imaplib
import os
import uuid

import psycopg
from psycopg import sql

from sophyane.mail_engine.accounts import AccountStore
from sophyane.mail_engine.imap_server import IMAPServer
from sophyane.mail_engine.store import MailStore


ADDRESS = "owner@nifdu.com"
PASSWORD = "password-123"


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


def _client(
    port: int,
) -> None:
    client = imaplib.IMAP4(
        "127.0.0.1",
        port,
    )

    try:
        status, _ = client.login(
            ADDRESS,
            PASSWORD,
        )

        assert status == "OK"

        status, count = client.select(
            "INBOX"
        )

        assert status == "OK"
        assert count[
            0
        ] == b"1"

        status, identifiers = client.search(
            None,
            "ALL",
        )

        assert status == "OK"

        assert identifiers[
            0
        ].split() == [
            b"1",
        ]

        status, rows = client.fetch(
            "1",
            "(RFC822)",
        )

        assert status == "OK"

        raw = b"".join(
            item[
                1
            ]
            for item in rows
            if isinstance(
                item,
                tuple,
            )
        )

        assert b"imap-proof-message" in raw
        assert b"real IMAP fetch proof" in raw

    finally:
        try:
            client.logout()

        except Exception:
            pass


def test_real_imap_login_select_search_fetch(
    monkeypatch,
) -> None:
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

    schema = (
        "imap_test_"
        + uuid.uuid4().hex[:16]
    )

    monkeypatch.setenv(
        "SOPHYANE_MAIL_SCHEMA",
        schema,
    )

    async def scenario() -> None:
        accounts = AccountStore(
            domain="nifdu.com",
        )

        accounts.create(
            ADDRESS,
            PASSWORD,
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
        ] = ADDRESS

        message[
            "Subject"
        ] = "imap-proof-message"

        message.set_content(
            "real IMAP fetch proof"
        )

        store.deliver(
            sender="outside@example.net",
            recipients=[
                ADDRESS,
            ],
            data=message.as_bytes(),
        )

        protocol = IMAPServer(
            accounts,
            store,
        )

        server = await asyncio.start_server(
            protocol.handle,
            "127.0.0.1",
            0,
        )

        port = int(
            server.sockets[
                0
            ].getsockname()[
                1
            ]
        )

        async with server:
            await asyncio.to_thread(
                _client,
                port,
            )

    try:
        asyncio.run(
            scenario()
        )

    finally:
        _drop_schema(
            dsn,
            schema,
        )
