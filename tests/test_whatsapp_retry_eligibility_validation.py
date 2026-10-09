from __future__ import annotations

import json
import math
from concurrent.futures import Future

import pytest

import sophyane.cloud.messaging as messaging


class RecordingExecutor:
    def __init__(self) -> None:
        self.submissions: list[dict] = []

    def submit(self, function, message):
        self.submissions.append(
            dict(message)
        )

        future = Future()
        future.set_result(
            {
                "ok": True,
                "message_id": message["message_id"],
                "sender": message["sender"],
            }
        )
        return future

    def shutdown(self, wait=True):
        return None


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    messaging._reset_whatsapp_inbound_worker_for_tests()
    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()

    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "whatsapp_inbound",
    )

    yield

    messaging._drain_whatsapp_inbound_worker_for_tests()
    messaging._reset_whatsapp_inbound_worker_for_tests()
    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()


def _write_durable_job(
    message_id: str,
    next_attempt_at,
) -> None:
    path = messaging._whatsapp_inbound_spool_path(
        message_id
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            {
                "message": {
                    "message_id": message_id,
                    "sender": "923001234567",
                    "text": "retry eligibility validation",
                },
                "attempts": 1,
                "next_attempt_at": next_attempt_at,
            },
            allow_nan=True,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("message_id", "next_attempt_at"),
    [
        (
            "wamid.retry-eligibility-positive-infinity",
            math.inf,
        ),
        (
            "wamid.retry-eligibility-negative-infinity",
            -math.inf,
        ),
        (
            "wamid.retry-eligibility-nan",
            math.nan,
        ),
    ],
)
def test_nonfinite_retry_eligibility_is_treated_as_absent_metadata(
    monkeypatch,
    message_id,
    next_attempt_at,
):
    """
    Non-finite retry timestamps cannot represent a real durable eligibility
    instant.

    Treat malformed/non-finite metadata like legacy absent metadata: the
    durable job remains replayable instead of becoming permanently stranded.
    """

    _write_durable_job(
        message_id,
        next_attempt_at,
    )

    executor = RecordingExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    results = messaging._replay_whatsapp_inbound_spool()

    assert len(executor.submissions) == 1

    assert executor.submissions[0]["message_id"] == message_id

    assert len(results) == 1
    assert results[0]["ok"] is True
    assert results[0]["queued"] is True
    assert results[0]["message_id"] == message_id


def test_finite_future_retry_eligibility_still_enforces_backoff(
    monkeypatch,
):
    """
    The non-finite hardening contract must not weaken valid finite backoff.
    """

    message_id = "wamid.retry-eligibility-finite-future"

    _write_durable_job(
        message_id,
        4_000_000_000.0,
    )

    executor = RecordingExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    results = messaging._replay_whatsapp_inbound_spool()

    assert executor.submissions == []

    assert len(results) == 1
    assert results[0]["ok"] is False
    assert results[0]["queued"] is False
    assert results[0]["message_id"] == message_id
    assert results[0]["stage"] == "retry_backoff"
    assert results[0]["next_attempt_at"] == 4_000_000_000.0
