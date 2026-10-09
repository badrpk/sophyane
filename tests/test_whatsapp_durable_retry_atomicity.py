from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

import sophyane.cloud.messaging as messaging


MESSAGE = {
    "message_id": "wamid.retry-atomicity",
    "sender": "15550000002",
    "text": "retry atomicity",
}


@pytest.fixture
def isolated_spool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    spool = tmp_path / "whatsapp-inbound"

    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        spool,
    )

    return spool


def _payload() -> dict:
    path = messaging._whatsapp_inbound_spool_path(
        MESSAGE["message_id"]
    )

    return json.JSONDecoder().decode(
        path.read_text(
            encoding="utf-8"
        )
    )


def test_concurrent_failed_attempt_updates_are_not_lost(
    isolated_spool: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Two completed failures for one durable job consume two attempts.

    Force both writers to observe attempts=0 before either may continue
    to its write. A correct durable accounting authority must serialize
    the read-modify-write transaction rather than allowing both writers
    to replace the spool with attempts=1.
    """
    messaging._persist_whatsapp_inbound_message(
        dict(MESSAGE)
    )

    start_barrier = threading.Barrier(
        3,
        timeout=5,
    )

    errors: list[BaseException] = []

    def record_failure() -> None:
        try:
            # Release both worker threads from the same rendezvous.
            # The production retry-attempt lock must then serialize
            # their complete durable read/modify/write transactions.
            start_barrier.wait()

            messaging._record_whatsapp_inbound_failed_attempt(
                MESSAGE["message_id"]
            )
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(
        target=record_failure,
        name="retry-attempt-first",
    )
    second = threading.Thread(
        target=record_failure,
        name="retry-attempt-second",
    )

    first.start()
    second.start()

    # Main thread is the third rendezvous participant. Once all three
    # arrive, both workers become runnable concurrently without placing
    # synchronization inside the production critical section.
    start_barrier.wait()

    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []

    payload = _payload()

    assert payload["message"] == MESSAGE

    # The durable counter represents completed failures, not the last
    # writer that happened to win os.replace().
    assert payload["attempts"] == 2


def test_sequential_failed_attempt_updates_remain_additive(
    isolated_spool: Path,
) -> None:
    """
    Establish the non-concurrent control case.

    The current implementation already supports ordinary sequential
    increments; the concurrency contract above must fail specifically
    because of lost-update atomicity rather than basic arithmetic.
    """
    messaging._persist_whatsapp_inbound_message(
        dict(MESSAGE)
    )

    messaging._record_whatsapp_inbound_failed_attempt(
        MESSAGE["message_id"]
    )
    messaging._record_whatsapp_inbound_failed_attempt(
        MESSAGE["message_id"]
    )

    payload = _payload()

    assert payload["message"] == MESSAGE
    assert payload["attempts"] == 2
