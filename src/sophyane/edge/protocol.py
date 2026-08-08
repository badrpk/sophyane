"""Versioned framing for Sophyane Edge control/data messages."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import struct


_MAGIC = b"SPHE"
_VERSION = 1

_HEADER = struct.Struct(
    "!4sBI"
)

_ALLOWED_TYPES = {
    "hello",
    "hello_ack",
    "open",
    "open_ack",
    "data",
    "close",
    "ping",
    "pong",
    "error",
}


@dataclass(frozen=True)
class EdgeFrame:
    kind: str
    stream_id: str = ""
    payload: bytes = b""
    metadata: dict[str, object] | None = None


def _wire_payload(
    frame: EdgeFrame,
) -> bytes:
    if frame.kind not in _ALLOWED_TYPES:
        raise ValueError(
            f"unsupported edge frame: {frame.kind}"
        )

    body = {
        "kind":
            frame.kind,

        "stream_id":
            frame.stream_id,

        "payload":
            base64.b64encode(
                frame.payload
            ).decode(
                "ascii"
            ),

        "metadata":
            frame.metadata
            or {},
    }

    return json.dumps(
        body,
        separators=(
            ",",
            ":",
        ),
        sort_keys=True,
    ).encode(
        "utf-8"
    )


def encode_frame(
    frame: EdgeFrame,
) -> bytes:
    body = _wire_payload(
        frame
    )

    return (
        _HEADER.pack(
            _MAGIC,
            _VERSION,
            len(
                body
            ),
        )
        + body
    )


def decode_frame(
    blob: bytes,
) -> EdgeFrame:
    if len(
        blob
    ) < _HEADER.size:
        raise ValueError(
            "incomplete edge frame"
        )

    magic, version, length = _HEADER.unpack(
        blob[
            :_HEADER.size
        ]
    )

    if magic != _MAGIC:
        raise ValueError(
            "invalid edge frame magic"
        )

    if version != _VERSION:
        raise ValueError(
            f"unsupported edge protocol version: {version}"
        )

    body = blob[
        _HEADER.size:
    ]

    if len(
        body
    ) != length:
        raise ValueError(
            "edge frame length mismatch"
        )

    payload = json.loads(
        body.decode(
            "utf-8"
        )
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "edge payload must be object"
        )

    kind = str(
        payload.get(
            "kind",
            ""
        )
    )

    if kind not in _ALLOWED_TYPES:
        raise ValueError(
            f"unsupported edge frame: {kind}"
        )

    metadata = payload.get(
        "metadata",
        {}
    )

    if not isinstance(
        metadata,
        dict,
    ):
        raise ValueError(
            "edge metadata must be object"
        )

    encoded = str(
        payload.get(
            "payload",
            ""
        )
    )

    try:
        data = base64.b64decode(
            encoded,
            validate=True,
        )

    except Exception as error:
        raise ValueError(
            "invalid edge payload encoding"
        ) from error

    return EdgeFrame(
        kind=kind,
        stream_id=str(
            payload.get(
                "stream_id",
                ""
            )
        ),
        payload=data,
        metadata=metadata,
    )
