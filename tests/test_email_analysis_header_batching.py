from sophyane.connectors.email_imap.analysis import (
    HEADER_FETCH_BATCH,
    _fetch_header_batch,
)


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def uid(self, *args):
        self.calls.append(args)

        return (
            "OK",
            [
                (
                    b'10 (UID 101 BODY[HEADER.FIELDS (FROM TO)] {35}',
                    (
                        b"From: One <one@example.com>\r\n"
                        b"To: Owner <owner@example.com>\r\n"
                        b"\r\n"
                    ),
                ),
                b")",
                (
                    b'11 (UID 102 BODY[HEADER.FIELDS (FROM TO)] {35}',
                    (
                        b"From: Two <two@example.com>\r\n"
                        b"To: Owner <owner@example.com>\r\n"
                        b"\r\n"
                    ),
                ),
                b")",
            ],
        )


def test_header_batch_constant_is_bounded() -> None:
    assert HEADER_FETCH_BATCH == 100


def test_header_batch_uses_one_uid_fetch() -> None:
    client = FakeClient()

    result = _fetch_header_batch(
        client,
        [
            b"101",
            b"102",
        ],
    )

    assert len(client.calls) == 1

    call = client.calls[0]

    assert call[0] == "fetch"
    assert call[1] == "101,102"
    assert "BODY.PEEK[HEADER.FIELDS" in call[2]

    assert [
        uid
        for uid, _message in result
    ] == [
        b"101",
        b"102",
    ]


def test_header_batch_preserves_message_bytes() -> None:
    client = FakeClient()

    result = _fetch_header_batch(
        client,
        [b"101", b"102"],
    )

    assert b"one@example.com" in result[0][1]
    assert b"two@example.com" in result[1][1]
