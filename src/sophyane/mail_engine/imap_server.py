"""Native PostgreSQL-backed IMAP service with TLS support."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
import ssl

from .accounts import AccountStore
from .store import MailStore


_FETCH_NUMBER = re.compile(
    r"^\s*(\d+)"
)


class IMAPServer:
    def __init__(
        self,
        accounts: AccountStore,
        store: MailStore,
        *,
        starttls_context: ssl.SSLContext | None = None,
        require_tls_for_login: bool = False,
        implicit_tls: bool = False,
    ) -> None:
        self.accounts = accounts
        self.store = store
        self.starttls_context = starttls_context
        self.require_tls_for_login = require_tls_for_login
        self.implicit_tls = implicit_tls

    async def _line(
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

    def _capabilities(
        self,
        *,
        tls_active: bool,
    ) -> list[str]:
        values = [
            "IMAP4rev1",
        ]

        if (
            self.starttls_context is not None
            and not tls_active
        ):
            values.append(
                "STARTTLS"
            )

        if (
            not self.require_tls_for_login
            or tls_active
        ):
            values.append(
                "AUTH=PLAIN"
            )

        if (
            self.require_tls_for_login
            and not tls_active
        ):
            values.append(
                "LOGINDISABLED"
            )

        return values

    async def handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        authenticated = ""
        selected = False
        tls_active = self.implicit_tls

        await self._line(
            writer,
            (
                "* OK [CAPABILITY "
                + " ".join(
                    self._capabilities(
                        tls_active=tls_active
                    )
                )
                + "] Sophyane Nifdu IMAP ready"
            ),
        )

        try:
            while True:
                raw = await reader.readline()

                if not raw:
                    break

                text = raw.decode(
                    "utf-8",
                    errors="replace",
                ).rstrip(
                    "\r\n"
                )

                parts = text.split(
                    " ",
                    2,
                )

                if len(
                    parts
                ) < 2:
                    await self._line(
                        writer,
                        "* BAD malformed command",
                    )
                    continue

                tag = parts[
                    0
                ]

                command = parts[
                    1
                ].upper()

                argument = (
                    parts[
                        2
                    ]
                    if len(
                        parts
                    ) > 2
                    else ""
                )

                if command == "CAPABILITY":
                    await self._line(
                        writer,
                        (
                            "* CAPABILITY "
                            + " ".join(
                                self._capabilities(
                                    tls_active=tls_active
                                )
                            )
                        ),
                    )

                    await self._line(
                        writer,
                        f"{tag} OK CAPABILITY completed",
                    )
                    continue

                if command == "NOOP":
                    await self._line(
                        writer,
                        f"{tag} OK NOOP completed",
                    )
                    continue

                if command == "LOGOUT":
                    await self._line(
                        writer,
                        "* BYE Sophyane IMAP logging out",
                    )

                    await self._line(
                        writer,
                        f"{tag} OK LOGOUT completed",
                    )
                    break

                if command == "STARTTLS":
                    if self.starttls_context is None:
                        await self._line(
                            writer,
                            f"{tag} NO STARTTLS unavailable",
                        )
                        continue

                    if tls_active:
                        await self._line(
                            writer,
                            f"{tag} BAD TLS already active",
                        )
                        continue

                    if authenticated:
                        await self._line(
                            writer,
                            (
                                f"{tag} BAD STARTTLS not permitted "
                                "after authentication"
                            ),
                        )
                        continue

                    await self._line(
                        writer,
                        f"{tag} OK Begin TLS negotiation now",
                    )

                    await writer.start_tls(
                        self.starttls_context,
                        ssl_handshake_timeout=10.0,
                    )

                    tls_active = True
                    selected = False

                    continue

                if command == "LOGIN":
                    if (
                        self.require_tls_for_login
                        and not tls_active
                    ):
                        await self._line(
                            writer,
                            (
                                f"{tag} NO "
                                "[PRIVACYREQUIRED] "
                                "TLS required before LOGIN"
                            ),
                        )
                        continue

                    login_parts = argument.split()

                    if len(
                        login_parts
                    ) != 2:
                        await self._line(
                            writer,
                            (
                                f"{tag} BAD LOGIN requires "
                                "user and password"
                            ),
                        )
                        continue

                    username = login_parts[
                        0
                    ].strip(
                        '"'
                    )

                    password = login_parts[
                        1
                    ].strip(
                        '"'
                    )

                    if not self.accounts.verify(
                        username,
                        password,
                    ):
                        await self._line(
                            writer,
                            f"{tag} NO authentication failed",
                        )
                        continue

                    authenticated = (
                        self.accounts.normalize_address(
                            username
                        )
                    )

                    await self._line(
                        writer,
                        f"{tag} OK LOGIN completed",
                    )
                    continue

                if not authenticated:
                    await self._line(
                        writer,
                        f"{tag} NO authenticate first",
                    )
                    continue

                if command == "LIST":
                    await self._line(
                        writer,
                        '* LIST (\\HasNoChildren) "/" "INBOX"',
                    )

                    await self._line(
                        writer,
                        f"{tag} OK LIST completed",
                    )
                    continue

                if command in {
                    "SELECT",
                    "EXAMINE",
                }:
                    mailbox_name = argument.strip(
                        '"'
                    ).upper()

                    if mailbox_name != "INBOX":
                        await self._line(
                            writer,
                            f"{tag} NO only INBOX is available",
                        )
                        continue

                    messages = self.store.messages(
                        authenticated
                    )

                    count = len(
                        messages
                    )

                    selected = True

                    await self._line(
                        writer,
                        f"* {count} EXISTS",
                    )

                    await self._line(
                        writer,
                        "* 0 RECENT",
                    )

                    await self._line(
                        writer,
                        '* FLAGS (\\Seen)',
                    )

                    await self._line(
                        writer,
                        (
                            "* OK [UIDVALIDITY 1] "
                            "stable PostgreSQL mailbox"
                        ),
                    )

                    uid_next = (
                        max(
                            (
                                int(
                                    item[
                                        0
                                    ]
                                )
                                for item in messages
                            ),
                            default=0,
                        )
                        + 1
                    )

                    await self._line(
                        writer,
                        f"* OK [UIDNEXT {uid_next}] next UID",
                    )

                    await self._line(
                        writer,
                        (
                            f"{tag} OK [READ-WRITE] "
                            "SELECT completed"
                        ),
                    )
                    continue

                if not selected:
                    await self._line(
                        writer,
                        f"{tag} NO select mailbox first",
                    )
                    continue

                if command == "SEARCH":
                    messages = self.store.messages(
                        authenticated
                    )

                    numbers = " ".join(
                        str(
                            sequence
                        )
                        for sequence, _key, _raw in messages
                    )

                    await self._line(
                        writer,
                        (
                            "* SEARCH"
                            + (
                                " "
                                + numbers
                                if numbers
                                else ""
                            )
                        ),
                    )

                    await self._line(
                        writer,
                        f"{tag} OK SEARCH completed",
                    )
                    continue

                if command == "UID":
                    nested, _, nested_args = argument.partition(
                        " "
                    )

                    if nested.upper() != "SEARCH":
                        await self._line(
                            writer,
                            f"{tag} BAD unsupported UID command",
                        )
                        continue

                    del nested_args

                    messages = self.store.messages(
                        authenticated
                    )

                    numbers = " ".join(
                        str(
                            sequence
                        )
                        for sequence, _key, _raw in messages
                    )

                    await self._line(
                        writer,
                        (
                            "* SEARCH"
                            + (
                                " "
                                + numbers
                                if numbers
                                else ""
                            )
                        ),
                    )

                    await self._line(
                        writer,
                        f"{tag} OK UID SEARCH completed",
                    )
                    continue

                if command == "FETCH":
                    match = _FETCH_NUMBER.match(
                        argument
                    )

                    if not match:
                        await self._line(
                            writer,
                            (
                                f"{tag} BAD FETCH requires "
                                "message number"
                            ),
                        )
                        continue

                    sequence = int(
                        match.group(
                            1
                        )
                    )

                    messages = self.store.messages(
                        authenticated
                    )

                    chosen = None

                    for item in messages:
                        if int(
                            item[
                                0
                            ]
                        ) == sequence:
                            chosen = item
                            break

                    if chosen is None:
                        await self._line(
                            writer,
                            f"{tag} NO no such message",
                        )
                        continue

                    _sequence, _key, data = chosen

                    size = len(
                        data
                    )

                    writer.write(
                        (
                            f"* {sequence} FETCH "
                            f"(FLAGS () RFC822.SIZE {size} "
                            f"BODY[] {{{size}}}\r\n"
                        ).encode(
                            "utf-8"
                        )
                    )

                    writer.write(
                        data
                    )

                    if not data.endswith(
                        b"\r\n"
                    ):
                        writer.write(
                            b"\r\n"
                        )

                    writer.write(
                        b")\r\n"
                    )

                    await writer.drain()

                    await self._line(
                        writer,
                        f"{tag} OK FETCH completed",
                    )
                    continue

                await self._line(
                    writer,
                    f"{tag} BAD command not implemented",
                )

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
    certfile: str = "",
    keyfile: str = "",
    starttls: bool = False,
    require_tls_for_login: bool = False,
) -> None:
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

    protocol = IMAPServer(
        accounts,
        store,
        starttls_context=starttls_context,
        require_tls_for_login=require_tls_for_login,
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

    print(
        "Sophyane IMAP listening:",
        ", ".join(
            str(
                socket.getsockname()
            )
            for socket in (
                server.sockets
                or []
            )
        ),
        "implicit_tls=",
        bool(
            implicit_context
        ),
        "starttls=",
        bool(
            starttls_context
        ),
        "tls_required_for_login=",
        require_tls_for_login,
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
        default=1993,
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
        "--require-tls-for-login",
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

    asyncio.run(
        serve(
            root=Path(
                args.root
            ).resolve(),
            domain=args.domain,
            host=args.host,
            port=args.port,
            certfile=args.certfile,
            keyfile=args.keyfile,
            starttls=args.starttls,
            require_tls_for_login=args.require_tls_for_login,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
