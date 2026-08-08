from __future__ import annotations

import asyncio
from email.message import EmailMessage
import os
import smtplib
import uuid

import psycopg
from psycopg import sql

from sophyane.mail_engine.accounts import AccountStore
from sophyane.mail_engine.smtp_server import SMTPServer
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


async def _server(
    *,
    require_auth: bool,
):
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

    protocol = SMTPServer(
        accounts,
        store,
        hostname="mail.nifdu.com",
        require_auth=require_auth,
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

    return (
        server,
        port,
        store,
    )


def _send(
    port: int,
    message: EmailMessage,
) -> None:
    with smtplib.SMTP(
        "127.0.0.1",
        port,
        timeout=5,
    ) as client:
        client.send_message(
            message
        )


def _authenticated_send(
    port: int,
) -> None:
    with smtplib.SMTP(
        "127.0.0.1",
        port,
        timeout=5,
    ) as client:
        client.login(
            ADDRESS,
            PASSWORD,
        )

        message = EmailMessage()

        message[
            "From"
        ] = ADDRESS

        message[
            "To"
        ] = ADDRESS

        message[
            "Subject"
        ] = "smtp-auth-proof"

        message.set_content(
            "authenticated SMTP reached PostgreSQL"
        )

        client.send_message(
            message
        )


def test_native_smtp_receives_real_message(
    monkeypatch,
) -> None:
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

    schema = (
        "smtp_test_"
        + uuid.uuid4().hex[:16]
    )

    monkeypatch.setenv(
        "SOPHYANE_MAIL_SCHEMA",
        schema,
    )

    async def scenario() -> None:
        server, port, store = await _server(
            require_auth=False,
        )

        async with server:
            message = EmailMessage()

            message[
                "From"
            ] = "outside@example.net"

            message[
                "To"
            ] = ADDRESS

            message[
                "Subject"
            ] = "smtp-engine-proof"

            message.set_content(
                "real SMTP DATA reached PostgreSQL"
            )

            await asyncio.to_thread(
                _send,
                port,
                message,
            )

            assert store.count(
                ADDRESS
            ) == 1

            raw = store.messages(
                ADDRESS
            )[
                0
            ][
                2
            ]

            assert b"smtp-engine-proof" in raw
            assert b"real SMTP DATA reached PostgreSQL" in raw

    try:
        asyncio.run(
            scenario()
        )

    finally:
        _drop_schema(
            dsn,
            schema,
        )


def test_submission_requires_authentication(
    monkeypatch,
) -> None:
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

    schema = (
        "smtp_auth_test_"
        + uuid.uuid4().hex[:16]
    )

    monkeypatch.setenv(
        "SOPHYANE_MAIL_SCHEMA",
        schema,
    )

    async def scenario() -> None:
        server, port, store = await _server(
            require_auth=True,
        )

        async with server:
            # Negative proof first.
            message = EmailMessage()

            message[
                "From"
            ] = ADDRESS

            message[
                "To"
            ] = ADDRESS

            message[
                "Subject"
            ] = "must-not-arrive"

            message.set_content(
                "unauthenticated submission"
            )

            try:
                await asyncio.to_thread(
                    _send,
                    port,
                    message,
                )

            except smtplib.SMTPResponseException as error:
                assert error.smtp_code == 530

            else:
                raise AssertionError(
                    "unauthenticated submission unexpectedly succeeded"
                )

            assert store.count(
                ADDRESS
            ) == 0

            await asyncio.to_thread(
                _authenticated_send,
                port,
            )

            assert store.count(
                ADDRESS
            ) == 1

            raw = store.messages(
                ADDRESS
            )[
                0
            ][
                2
            ]

            assert b"smtp-auth-proof" in raw

    try:
        asyncio.run(
            scenario()
        )

    finally:
        _drop_schema(
            dsn,
            schema,
        )
