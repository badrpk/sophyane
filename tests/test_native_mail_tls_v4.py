from __future__ import annotations

from email.message import EmailMessage
import imaplib
import os
from pathlib import Path
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import time
import uuid

import psycopg
import pytest
from psycopg import sql

from sophyane.mail_engine.accounts import AccountStore
from sophyane.mail_engine.store import MailStore


PASSWORD = "native-mail-v4-test-password"
ADDRESS = "owner@nifdu.com"
DOMAIN = "nifdu.com"


def _free_port() -> int:
    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    )

    try:
        sock.bind(
            (
                "127.0.0.1",
                0,
            )
        )

        return int(
            sock.getsockname()[1]
        )

    finally:
        sock.close()


def _wait_port(
    port: int,
    *,
    timeout: float = 10.0,
) -> None:
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            connection = socket.create_connection(
                (
                    "127.0.0.1",
                    port,
                ),
                timeout=0.25,
            )

        except OSError:
            time.sleep(
                0.05
            )

        else:
            connection.close()
            return

    raise RuntimeError(
        f"port did not become ready: {port}"
    )


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


@pytest.fixture
def mail_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    dsn = os.environ[
        "SOPHYANE_POSTGRES_DSN"
    ]

    schema = (
        "mail_v4_test_"
        + uuid.uuid4().hex[:16]
    )

    monkeypatch.setenv(
        "SOPHYANE_MAIL_SCHEMA",
        schema,
    )

    accounts = AccountStore(
        domain=DOMAIN,
    )

    accounts.create(
        ADDRESS,
        PASSWORD,
    )

    cert = (
        tmp_path
        / "mail.crt"
    )

    key = (
        tmp_path
        / "mail.key"
    )

    openssl = shutil.which(
        "openssl"
    )

    if not openssl:
        pytest.skip(
            "openssl unavailable"
        )

    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=mail.nifdu.com",
            "-keyout",
            str(
                key
            ),
            "-out",
            str(
                cert
            ),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    environment = dict(
        os.environ
    )

    environment[
        "SOPHYANE_MAIL_SCHEMA"
    ] = schema

    processes: list[
        subprocess.Popen
    ] = []

    try:
        yield {
            "dsn": dsn,
            "schema": schema,
            "accounts": accounts,
            "cert": cert,
            "key": key,
            "environment": environment,
            "processes": processes,
        }

    finally:
        for process in reversed(
            processes
        ):
            if process.poll() is None:
                process.terminate()

        for process in reversed(
            processes
        ):
            try:
                process.wait(
                    timeout=3
                )

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(
                    timeout=3
                )

        _drop_schema(
            dsn,
            schema,
        )


def _start(
    environment: dict,
    processes: list[subprocess.Popen],
    module: str,
    arguments: list[str],
) -> subprocess.Popen:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            module,
            *arguments,
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    processes.append(
        process
    )

    return process


def _client_context() -> ssl.SSLContext:
    context = ssl.create_default_context()

    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    return context


def test_smtp_starttls_security_and_sender_binding(
    mail_environment,
) -> None:
    port = _free_port()

    process = _start(
        mail_environment[
            "environment"
        ],
        mail_environment[
            "processes"
        ],
        "sophyane.mail_engine.smtp_server",
        [
            "--domain",
            DOMAIN,
            "--host",
            "127.0.0.1",
            "--port",
            str(
                port
            ),
            "--require-auth",
            "--starttls",
            "--require-tls-for-auth",
            "--certfile",
            str(
                mail_environment[
                    "cert"
                ]
            ),
            "--keyfile",
            str(
                mail_environment[
                    "key"
                ]
            ),
        ],
    )

    _wait_port(
        port
    )

    assert process.poll() is None

    client = smtplib.SMTP(
        "127.0.0.1",
        port,
        timeout=8,
    )

    try:
        code, _ = client.ehlo()

        assert code == 250
        assert "starttls" in client.esmtp_features
        assert "auth" not in client.esmtp_features

        # Prove AUTH command itself is rejected before TLS,
        # independent of smtplib feature discovery.
        auth_code, _ = client.docmd(
            "AUTH",
            "PLAIN AG93bmVyQG5pZmR1LmNvbQBiYWQ="
        )

        assert auth_code == 538

        client.starttls(
            context=_client_context()
        )

        client.ehlo()

        assert "starttls" not in client.esmtp_features
        assert "auth" in client.esmtp_features

        client.login(
            ADDRESS,
            PASSWORD,
        )

        # Evidence-grade negative sender-binding proof.
        code, _ = client.mail(
            "other@nifdu.com"
        )

        assert code == 553

        client.rset()

        message = EmailMessage()

        message[
            "From"
        ] = ADDRESS

        message[
            "To"
        ] = ADDRESS

        message[
            "Subject"
        ] = "permanent SMTP STARTTLS acceptance"

        message[
            "Message-ID"
        ] = "<permanent-starttls@nifdu.com>"

        message.set_content(
            "STARTTLS acceptance body."
        )

        client.send_message(
            message
        )

    finally:
        try:
            client.quit()

        except Exception:
            pass

    store = MailStore(
        mail_environment[
            "accounts"
        ]
    )

    rows = store.messages(
        ADDRESS
    )

    assert len(
        rows
    ) == 1

    assert b"permanent SMTP STARTTLS acceptance" in rows[
        0
    ][
        2
    ]


def test_implicit_tls_smtp(
    mail_environment,
) -> None:
    port = _free_port()

    process = _start(
        mail_environment[
            "environment"
        ],
        mail_environment[
            "processes"
        ],
        "sophyane.mail_engine.smtp_server",
        [
            "--domain",
            DOMAIN,
            "--host",
            "127.0.0.1",
            "--port",
            str(
                port
            ),
            "--require-auth",
            "--require-tls-for-auth",
            "--certfile",
            str(
                mail_environment[
                    "cert"
                ]
            ),
            "--keyfile",
            str(
                mail_environment[
                    "key"
                ]
            ),
        ],
    )

    _wait_port(
        port
    )

    assert process.poll() is None

    with smtplib.SMTP_SSL(
        "127.0.0.1",
        port,
        timeout=8,
        context=_client_context(),
    ) as client:
        code, _ = client.ehlo()

        assert code == 250

        assert client.sock.version() in {
            "TLSv1.2",
            "TLSv1.3",
        }

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
        ] = "permanent implicit SMTP TLS acceptance"

        message[
            "Message-ID"
        ] = "<permanent-implicit-smtp@nifdu.com>"

        message.set_content(
            "Implicit SMTP TLS acceptance body."
        )

        client.send_message(
            message
        )

    store = MailStore(
        mail_environment[
            "accounts"
        ]
    )

    rows = store.messages(
        ADDRESS
    )

    assert len(
        rows
    ) == 1

    assert b"permanent implicit SMTP TLS acceptance" in rows[
        0
    ][
        2
    ]


def _seed_message(
    environment,
    subject: str,
) -> None:
    store = MailStore(
        environment[
            "accounts"
        ]
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
    ] = subject

    message.set_content(
        "IMAP transport acceptance body."
    )

    store.deliver(
        sender=ADDRESS,
        recipients=[
            ADDRESS,
        ],
        data=message.as_bytes(),
    )


def test_imap_starttls_security_and_fetch(
    mail_environment,
) -> None:
    _seed_message(
        mail_environment,
        "permanent IMAP STARTTLS acceptance",
    )

    port = _free_port()

    process = _start(
        mail_environment[
            "environment"
        ],
        mail_environment[
            "processes"
        ],
        "sophyane.mail_engine.imap_server",
        [
            "--domain",
            DOMAIN,
            "--host",
            "127.0.0.1",
            "--port",
            str(
                port
            ),
            "--starttls",
            "--require-tls-for-login",
            "--certfile",
            str(
                mail_environment[
                    "cert"
                ]
            ),
            "--keyfile",
            str(
                mail_environment[
                    "key"
                ]
            ),
        ],
    )

    _wait_port(
        port
    )

    assert process.poll() is None

    client = imaplib.IMAP4(
        "127.0.0.1",
        port,
    )

    try:
        assert "STARTTLS" in client.capabilities
        assert "LOGINDISABLED" in client.capabilities

        with pytest.raises(
            imaplib.IMAP4.error
        ):
            client.login(
                ADDRESS,
                PASSWORD,
            )

        status, _ = client.starttls(
            ssl_context=_client_context()
        )

        assert status == "OK"

        status, capabilities = client.capability()

        assert status == "OK"

        blob = b" ".join(
            capabilities
        ).upper()

        assert b"AUTH=PLAIN" in blob
        assert b"STARTTLS" not in blob
        assert b"LOGINDISABLED" not in blob

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

        assert b"permanent IMAP STARTTLS acceptance" in raw

    finally:
        try:
            client.logout()

        except Exception:
            pass


def test_implicit_tls_imap_fetch(
    mail_environment,
) -> None:
    _seed_message(
        mail_environment,
        "permanent implicit IMAP TLS acceptance",
    )

    port = _free_port()

    process = _start(
        mail_environment[
            "environment"
        ],
        mail_environment[
            "processes"
        ],
        "sophyane.mail_engine.imap_server",
        [
            "--domain",
            DOMAIN,
            "--host",
            "127.0.0.1",
            "--port",
            str(
                port
            ),
            "--require-tls-for-login",
            "--certfile",
            str(
                mail_environment[
                    "cert"
                ]
            ),
            "--keyfile",
            str(
                mail_environment[
                    "key"
                ]
            ),
        ],
    )

    _wait_port(
        port
    )

    assert process.poll() is None

    client = imaplib.IMAP4_SSL(
        "127.0.0.1",
        port,
        ssl_context=_client_context(),
    )

    try:
        assert "STARTTLS" not in client.capabilities
        assert "LOGINDISABLED" not in client.capabilities

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

        assert b"permanent implicit IMAP TLS acceptance" in raw

    finally:
        try:
            client.logout()

        except Exception:
            pass


def test_postgres_uidnext_is_authoritative(
    mail_environment,
) -> None:
    store = MailStore(
        mail_environment[
            "accounts"
        ]
    )

    for number in range(
        1,
        4,
    ):
        message = EmailMessage()

        message[
            "From"
        ] = ADDRESS

        message[
            "To"
        ] = ADDRESS

        message[
            "Subject"
        ] = f"uid-next-{number}"

        message[
            "Message-ID"
        ] = f"<uid-next-{number}@nifdu.com>"

        message.set_content(
            f"message {number}"
        )

        store.deliver(
            sender=ADDRESS,
            recipients=[
                ADDRESS,
            ],
            data=message.as_bytes(),
        )

    rows = store.messages(
        ADDRESS
    )

    assert [
        int(
            row[
                0
            ]
        )
        for row in rows
    ] == [
        1,
        2,
        3,
    ]

    schema = mail_environment[
        "schema"
    ]

    with psycopg.connect(
        mail_environment[
            "dsn"
        ]
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
                    ADDRESS,
                ),
            )

            uid_validity, uid_next = cursor.fetchone()

    assert int(
        uid_validity
    ) == 1

    assert int(
        uid_next
    ) == 4
