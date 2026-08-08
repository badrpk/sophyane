"""Transactional PostgreSQL mailbox/message store.

Authoritative persistence:
    PostgreSQL BYTEA + relational mailbox state.

There is deliberately no Maildir or filesystem UID counter.
"""
from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
import json
import uuid

from psycopg import sql

from .accounts import AccountStore


@dataclass(frozen=True)
class StoredMessage:
    uid: int
    key: str
    size: int
    sender: str
    recipients: tuple[str, ...]
    subject: str
    message_id: str


class MailStore:
    def __init__(
        self,
        accounts: AccountStore,
    ) -> None:
        self.accounts = accounts

    def _schema(
        self,
    ) -> sql.Identifier:
        return sql.Identifier(
            self.accounts.schema
        )

    def deliver(
        self,
        *,
        sender: str,
        recipients: list[str] | tuple[str, ...],
        data: bytes,
    ) -> list[StoredMessage]:
        if not data:
            raise ValueError(
                "empty message"
            )

        normalized_recipients = [
            self.accounts.normalize_address(
                recipient
            )
            for recipient in recipients
        ]

        if not normalized_recipients:
            raise ValueError(
                "message requires a local recipient"
            )

        parsed = BytesParser(
            policy=policy.default
        ).parsebytes(
            data
        )

        subject = str(
            parsed.get(
                "Subject",
                "",
            )
        )

        message_id_header = str(
            parsed.get(
                "Message-ID",
                "",
            )
        ).strip()

        if not message_id_header:
            message_id_header = (
                "<"
                + uuid.uuid4().hex
                + "@"
                + self.accounts.domain
                + ">"
            )

            parsed[
                "Message-ID"
            ] = message_id_header

            data = parsed.as_bytes(
                policy=policy.SMTP
            )

        schema = self._schema()

        stored: list[
            StoredMessage
        ] = []

        with self.accounts.connect() as connection:
            with connection.cursor() as cursor:
                #
                # Validate every recipient inside the same
                # transaction as delivery.
                #
                for recipient in normalized_recipients:
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
                            recipient,
                        ),
                    )

                    if cursor.fetchone() is None:
                        raise ValueError(
                            "unknown local recipient: "
                            + recipient
                        )

                cursor.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.messages (
                            message_id,
                            envelope_sender,
                            raw_message,
                            size_bytes,
                            metadata
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s::jsonb
                        )
                        RETURNING id
                        """
                    ).format(
                        schema
                    ),
                    (
                        message_id_header,
                        str(
                            sender
                        ),
                        data,
                        len(
                            data
                        ),
                        json.dumps(
                            {
                                "subject":
                                    subject,

                                "recipients":
                                    normalized_recipients,

                                "source":
                                    "sophyane-native-mail",
                            }
                        ),
                    ),
                )

                internal_message_id = int(
                    cursor.fetchone()[
                        0
                    ]
                )

                for recipient in normalized_recipients:
                    #
                    # Lock/advance the mailbox UID allocator
                    # atomically.
                    #
                    cursor.execute(
                        sql.SQL(
                            """
                            UPDATE {}.mailboxes
                            SET uid_next = uid_next + 1
                            WHERE account_address = %s
                              AND name = 'INBOX'
                            RETURNING
                                id,
                                uid_next - 1
                            """
                        ).format(
                            schema
                        ),
                        (
                            recipient,
                        ),
                    )

                    mailbox = cursor.fetchone()

                    if mailbox is None:
                        raise RuntimeError(
                            "recipient INBOX is missing"
                        )

                    mailbox_id = int(
                        mailbox[0]
                    )

                    uid = int(
                        mailbox[1]
                    )

                    cursor.execute(
                        sql.SQL(
                            """
                            INSERT INTO
                            {}.mailbox_messages (
                                mailbox_id,
                                message_id,
                                uid,
                                flags
                            )
                            VALUES (
                                %s,
                                %s,
                                %s,
                                '[]'::jsonb
                            )
                            """
                        ).format(
                            schema
                        ),
                        (
                            mailbox_id,
                            internal_message_id,
                            uid,
                        ),
                    )

                    stored.append(
                        StoredMessage(
                            uid=uid,
                            key=str(
                                internal_message_id
                            ),
                            size=len(
                                data
                            ),
                            sender=str(
                                sender
                            ),
                            recipients=tuple(
                                normalized_recipients
                            ),
                            subject=subject,
                            message_id=message_id_header,
                        )
                    )

        return stored

    def messages(
        self,
        address: str,
    ) -> list[tuple[int, str, bytes]]:
        normalized = self.accounts.normalize_address(
            address
        )

        schema = self._schema()

        with self.accounts.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT
                            mm.uid,
                            m.id,
                            m.raw_message
                        FROM {}.mailboxes AS mb
                        JOIN {}.mailbox_messages AS mm
                          ON mm.mailbox_id = mb.id
                        JOIN {}.messages AS m
                          ON m.id = mm.message_id
                        WHERE mb.account_address = %s
                          AND mb.name = 'INBOX'
                        ORDER BY mm.uid
                        """
                    ).format(
                        schema,
                        schema,
                        schema,
                    ),
                    (
                        normalized,
                    ),
                )

                return [
                    (
                        int(
                            uid
                        ),
                        str(
                            message_key
                        ),
                        bytes(
                            raw_message
                        ),
                    )
                    for (
                        uid,
                        message_key,
                        raw_message,
                    ) in cursor.fetchall()
                ]

    def count(
        self,
        address: str,
    ) -> int:
        normalized = self.accounts.normalize_address(
            address
        )

        schema = self._schema()

        with self.accounts.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT COUNT(*)
                        FROM {}.mailboxes AS mb
                        JOIN {}.mailbox_messages AS mm
                          ON mm.mailbox_id = mb.id
                        WHERE mb.account_address = %s
                          AND mb.name = 'INBOX'
                        """
                    ).format(
                        schema,
                        schema,
                    ),
                    (
                        normalized,
                    ),
                )

                return int(
                    cursor.fetchone()[
                        0
                    ]
                )

    def uid_next(
        self,
        address: str,
    ) -> int:
        normalized = self.accounts.normalize_address(
            address
        )

        schema = self._schema()

        with self.accounts.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT uid_next
                        FROM {}.mailboxes
                        WHERE account_address = %s
                          AND name = 'INBOX'
                        """
                    ).format(
                        schema
                    ),
                    (
                        normalized,
                    ),
                )

                row = cursor.fetchone()

                if row is None:
                    raise RuntimeError(
                        "INBOX does not exist"
                    )

                return int(
                    row[0]
                )
