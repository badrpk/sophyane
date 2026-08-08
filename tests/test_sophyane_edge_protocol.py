import pytest

from sophyane.edge.protocol import (
    EdgeFrame,
    decode_frame,
    encode_frame,
)


def test_edge_protocol_round_trip() -> None:
    original = EdgeFrame(
        kind="data",
        stream_id="stream-42",
        payload=b"\x00hello\xff",
        metadata={
            "service":
                "smtp",

            "local_port":
                2525,
        },
    )

    encoded = encode_frame(
        original
    )

    decoded = decode_frame(
        encoded
    )

    assert decoded == original


def test_edge_protocol_rejects_unknown_kind() -> None:
    with pytest.raises(
        ValueError,
        match="unsupported edge frame",
    ):
        encode_frame(
            EdgeFrame(
                kind="execute-shell",
            )
        )


def test_edge_protocol_rejects_corruption() -> None:
    encoded = bytearray(
        encode_frame(
            EdgeFrame(
                kind="ping",
            )
        )
    )

    encoded[
        0
    ] ^= 0xFF

    with pytest.raises(
        ValueError,
        match="magic",
    ):
        decode_frame(
            bytes(
                encoded
            )
        )
