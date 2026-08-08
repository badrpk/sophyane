"""Native asyncio SMTP receive/submission service.

Security modes:

Inbound SMTP:
    plaintext local transport is permitted.
    Public exposure is a separate Sophyane Edge concern.

Submission STARTTLS:
    AUTH is not advertised before TLS.
    AUTH before TLS is rejected.
    STARTTLS upgrades the active asyncio stream.
    AUTH is advertised after TLS.

Implicit TLS:
    asyncio.start_server(..., ssl=context) performs the TLS
    handshake before the SMTP greeting.

Mail durability is PostgreSQL-only.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import dataclass
from pathlib import Path
import re
import ssl

from .accounts import AccountStore
from .store import MailStore


_PATH = re.compile(
    r"<([^>]*)>"
)


@dataclass
class SMTPSession:
    authenticated: str = ""
    sender: str = ""
    recipients: list[str] | None = None
    tls_active: bool = False
    greeted: bool = False

    def __post_init__(
        self,
    ) -> None:
        if self.recipients is None:
            self.recipients = []


class SMTPServer:
    def __init__(
        self,
        accounts: AccountStore,
        store: MailStore,
        *,
        hostname: str,
        require_auth: bool = False,
        starttls_context: ssl.SSLContext | None = None,
        require_tls_for_auth: bool = False,
        implicit_tls: bool = False,
    ) -> None:
        self.accounts = accounts
        self.store = store
        self.hostname = hostname
        self.require_auth = require_auth
        self.starttls_context = starttls_context
        self.require_tls_for_auth = require_tls_for_auth
        self.implicit_tls = implicit_tls

    async def _write(
        self,
        writer: asyncio.StreamWriter,
        value: str,
    ) -> None:
        writer.write(
            (
                value
                + "\r\n"
            ).encode(
                "utf-8"
            )
        )

        await writer.drain()

    async def _ehlo(
        self,
        writer: asyncio.StreamWriter,
        session: SMTPSession,
    ) -> None:
        lines = [
            self.hostname,
            "PIPELINING",
            "8BITMIME",
            "SIZE 26214400",
        ]

        if (
            self.starttls_context is not None
            and not session.tls_active
        ):
            lines.append(
                "STARTTLS"
            )

        if (
            not self.require_tls_for_auth
            or session.tls_active
        ):
            lines.append(
                "AUTH PLAIN"
            )

        lines.append(
            "HELP"
        )

        for index, line in enumerate(
            lines
        ):
            separator = (
                "-"
                if index < len(
                    lines
                ) - 1
                else " "
            )

            writer.write(
                (
                    "250"
                    + separator
                    + line
                    + "\r\n"
                ).encode(
                    "utf-8"
                )
            )

        await writer.drain()

    @staticmethod
    def _extract_path(
        text: str,
    ) -> str:
        match = _PATH.search(
            text
        )

        if not match:
            return ""

        return match.group(
            1
        ).strip().casefold()

    async def _auth_plain(
        self,
        argument: str,
    ) -> tuple[bool, str]:
        try:
            decoded = base64.b64decode(
                argument,
                validate=True,
            )

            parts = decoded.split(
                b"\x00"
            )

            if len(
                parts
            ) < 3:
                return (
                    False,
                    "",
                )

            username = parts[
                -2
            ].decode(
                "utf-8"
            )

            password = parts[
                -1
            ].decode(
                "utf-8"
            )

        except Exception:
            return (
                False,
                "",
            )

        if self.accounts.verify(
            username,
            password,
        ):
            return (
                True,
                self.accounts.normalize_address(
                    username
                ),
            )

        return (
            False,
            "",
        )

    async def handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        session = SMTPSession(
            tls_active=self.implicit_tls
        )

        await self._write(
            writer,
            (
                f"220 {self.hostname} "
                "Sophyane Nifdu SMTP ready"
            ),
        )

        try:
            while True:
                line = await reader.readline()

                if not line:
                    break

                text = line.decode(
                    "utf-8",
                    errors="replace",
                ).rstrip(
                    "\r\n"
                )

                if not text:
                    await self._write(
                        writer,
                        "500 Empty command",
                    )
                    continue

                command, separator, argument = text.partition(
                    " "
                )

                command = command.upper()

                argument = (
                    argument.strip()
                    if separator
                    else ""
                )

                if command in {
                    "EHLO",
                    "HELO",
                }:
                    session.greeted = True

                    if command == "EHLO":
                        await self._ehlo(
                            writer,
                            session,
                        )

                    else:
                        await self._write(
                            writer,
                            "250 " + self.hostname,
                        )

                    continue

                if command == "NOOP":
                    await self._write(
                        writer,
                        "250 OK",
                    )
                    continue

                if command == "RSET":
                    session.sender = ""
                    session.recipients = []

                    await self._write(
                        writer,
                        "250 Reset",
                    )
                    continue

                if command == "QUIT":
                    await self._write(
                        writer,
                        "221 Bye",
                    )
                    break

                if command == "STARTTLS":
                    if self.starttls_context is None:
                        await self._write(
                            writer,
                            "454 4.7.0 TLS not available",
                        )
                        continue

                    if session.tls_active:
                        await self._write(
                            writer,
                            "503 5.5.1 TLS already active",
                        )
                        continue

                    await self._write(
                        writer,
                        "220 2.0.0 Ready to start TLS",
                    )

                    await writer.start_tls(
                        self.starttls_context,
                        ssl_handshake_timeout=10.0,
                    )

                    session.tls_active = True

                    # RFC-style state reset after TLS negotiation.
                    session.authenticated = ""
                    session.sender = ""
                    session.recipients = []
                    session.greeted = False

                    continue

                if command == "AUTH":
                    if (
                        self.require_tls_for_auth
                        and not session.tls_active
                    ):
                        await self._write(
                            writer,
                            (
                                "538 5.7.11 "
                                "Encryption required for requested "
                                "authentication mechanism"
                            ),
                        )
                        continue

                    mechanism, _, payload = argument.partition(
                        " "
                    )

                    if mechanism.upper() != "PLAIN":
                        await self._write(
                            writer,
                            "504 Only AUTH PLAIN is supported",
                        )
                        continue

                    if not payload:
                        await self._write(
                            writer,
                            "334",
                        )

                        response = await reader.readline()

                        payload = response.decode(
                            "ascii",
                            errors="ignore",
                        ).strip()

                    ok, address = await self._auth_plain(
                        payload
                    )

                    if not ok:
                        await self._write(
                            writer,
                            (
                                "535 5.7.8 "
                                "Authentication credentials invalid"
                            ),
                        )
                        continue

                    session.authenticated = address

                    await self._write(
                        writer,
                        "235 2.7.0 Authentication successful",
                    )
                    continue

                if command == "MAIL":
                    if (
                        self.require_auth
                        and not session.authenticated
                    ):
                        await self._write(
                            writer,
                            "530 5.7.0 Authentication required",
                        )
                        continue

                    if not argument.upper().startswith(
                        "FROM:"
                    ):
                        await self._write(
                            writer,
                            "501 Syntax: MAIL FROM:<address>",
                        )
                        continue

                    sender = self._extract_path(
                        argument
                    )

                    if not sender:
                        await self._write(
                            writer,
                            "501 Invalid sender",
                        )
                        continue

                    if (
                        self.require_auth
                        and session.authenticated
                        and sender.casefold()
                        != session.authenticated.casefold()
                    ):
                        await self._write(
                            writer,
                            (
                                "553 5.7.1 "
                                "Authenticated sender mismatch"
                            ),
                        )
                        continue

                    session.sender = sender
                    session.recipients = []

                    await self._write(
                        writer,
                        "250 2.1.0 Sender accepted",
                    )
                    continue

                if command == "RCPT":
                    if not session.sender:
                        await self._write(
                            writer,
                            "503 MAIL required first",
                        )
                        continue

                    if not argument.upper().startswith(
                        "TO:"
                    ):
                        await self._write(
                            writer,
                            "501 Syntax: RCPT TO:<address>",
                        )
                        continue

                    recipient = self._extract_path(
                        argument
                    )

                    if not self.accounts.exists(
                        recipient
                    ):
                        await self._write(
                            writer,
                            "550 5.1.1 No such local mailbox",
                        )
                        continue

                    session.recipients.append(
                        self.accounts.normalize_address(
                            recipient
                        )
                    )

                    await self._write(
                        writer,
                        "250 2.1.5 Recipient accepted",
                    )
                    continue

                if command == "DATA":
                    if (
                        not session.sender
                        or not session.recipients
                    ):
                        await self._write(
                            writer,
                            "503 MAIL and RCPT required first",
                        )
                        continue

                    await self._write(
                        writer,
                        (
                            "354 End data with "
                            "<CR><LF>.<CR><LF>"
                        ),
                    )

                    chunks: list[
                        bytes
                    ] = []

                    total = 0

                    while True:
                        data_line = await reader.readline()

                        if not data_line:
                            raise ConnectionError(
                                "client disconnected during DATA"
                            )

                        if data_line in {
                            b".\r\n",
                            b".\n",
                        }:
                            break

                        if data_line.startswith(
                            b".."
                        ):
                            data_line = data_line[
                                1:
                            ]

                        total += len(
                            data_line
                        )

                        if total > 26_214_400:
                            raise ValueError(
                                "message exceeds size limit"
                            )

                        chunks.append(
                            data_line
                        )

                    raw = b"".join(
                        chunks
                    )

                    self.store.deliver(
                        sender=session.sender,
                        recipients=session.recipients,
                        data=raw,
                    )

                    session.sender = ""
                    session.recipients = []

                    await self._write(
                        writer,
                        "250 2.0.0 Message stored locally",
                    )
                    continue

                await self._write(
                    writer,
                    "502 Command not implemented",
                )

        except Exception:
            try:
                await self._write(
                    writer,
                    "451 4.3.0 Local server error",
                )
            except Exception:
                pass

        finally:
            writer.close()

            try:
                await writer.wait_closed()
            except Exception:
                pass


def tls_context(
    certfile: str,
    keyfile: str,
) -> ssl.SSLContext:
    if not (
        certfile
        and keyfile
    ):
        raise ValueError(
            "both certfile and keyfile are required"
        )

    context = ssl.SSLContext(
        ssl.PROTOCOL_TLS_SERVER
    )

    context.minimum_version = (
        ssl.TLSVersion.TLSv1_2
    )

    context.load_cert_chain(
        certfile,
        keyfile,
    )

    return context


async def serve(
    *,
    root: Path,
    domain: str,
    host: str,
    port: int,
    require_auth: bool,
    certfile: str = "",
    keyfile: str = "",
    starttls: bool = False,
    require_tls_for_auth: bool = False,
) -> None:
    # root remains a compatibility argument.
    # All durable mail state is PostgreSQL-backed.
    del root

    accounts = AccountStore(
        domain=domain,
    )

    store = MailStore(
        accounts,
    )

    context = None

    if certfile or keyfile:
        context = tls_context(
            certfile,
            keyfile,
        )

    starttls_context = (
        context
        if starttls
        else None
    )

    implicit_context = (
        context
        if (
            context is not None
            and not starttls
        )
        else None
    )

    protocol = SMTPServer(
        accounts,
        store,
        hostname=(
            "mail."
            + domain
        ),
        require_auth=require_auth,
        starttls_context=starttls_context,
        require_tls_for_auth=require_tls_for_auth,
        implicit_tls=(
            implicit_context is not None
        ),
    )

    listener_options = {}

    if implicit_context is not None:
        listener_options[
            "ssl"
        ] = implicit_context

        listener_options[
            "ssl_handshake_timeout"
        ] = 10.0

    server = await asyncio.start_server(
        protocol.handle,
        host,
        port,
        **listener_options,
    )

    sockets = ", ".join(
        str(
            item.getsockname()
        )
        for item in (
            server.sockets
            or []
        )
    )

    print(
        "Sophyane SMTP listening:",
        sockets,
        "auth=",
        require_auth,
        "implicit_tls=",
        bool(
            implicit_context
        ),
        "starttls=",
        bool(
            starttls_context
        ),
        "tls_required_for_auth=",
        require_tls_for_auth,
        flush=True,
    )

    async with server:
        await server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--root",
        default=".",
    )

    parser.add_argument(
        "--domain",
        required=True,
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=2525,
    )

    parser.add_argument(
        "--require-auth",
        action="store_true",
    )

    parser.add_argument(
        "--certfile",
        default="",
    )

    parser.add_argument(
        "--keyfile",
        default="",
    )

    parser.add_argument(
        "--starttls",
        action="store_true",
    )

    parser.add_argument(
        "--require-tls-for-auth",
        action="store_true",
    )

    args = parser.parse_args()

    if args.starttls and not (
        args.certfile
        and args.keyfile
    ):
        parser.error(
            "--starttls requires --certfile and --keyfile"
        )

    if (
        args.require_tls_for_auth
        and not args.starttls
        and not (
            args.certfile
            and args.keyfile
        )
    ):
        parser.error(
            "TLS-required AUTH requires STARTTLS or implicit TLS"
        )

    asyncio.run(
        serve(
            root=Path(
                args.root
            ).resolve(),
            domain=args.domain,
            host=args.host,
            port=args.port,
            require_auth=args.require_auth,
            certfile=args.certfile,
            keyfile=args.keyfile,
            starttls=args.starttls,
            require_tls_for_auth=args.require_tls_for_auth,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
