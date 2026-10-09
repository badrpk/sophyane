from __future__ import annotations

import json
from concurrent.futures import Future
from pathlib import Path

import pytest

import sophyane.cloud.messaging as messaging


MESSAGE_ID = "wamid.durable-retry-backoff"
SENDER = "923001234567"
TEXT = "retry me later"


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
            }
        )

        return future


def _message() -> dict:
    return {
        "message_id": MESSAGE_ID,
        "sender": SENDER,
        "text": TEXT,
    }


def _payload(path: Path) -> dict:
    return json.JSONDecoder().decode(
        path.read_text(
            encoding="utf-8"
        )
    )


def _configure_spool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    spool = tmp_path / "whatsapp-inbound"

    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        spool,
    )

    return spool


def _persist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    _configure_spool(
        monkeypatch,
        tmp_path,
    )

    messaging._persist_whatsapp_inbound_message(
        _message()
    )

    return messaging._whatsapp_inbound_spool_path(
        MESSAGE_ID
    )


def test_failed_attempt_records_durable_retry_eligibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    A failed worker must durably record not only the consumed attempt,
    but when that durable job may next become replay-eligible.
    """
    path = _persist(
        monkeypatch,
        tmp_path,
    )

    messaging._record_whatsapp_inbound_failed_attempt(
        MESSAGE_ID
    )

    payload = _payload(path)

    assert payload["attempts"] == 1

    next_attempt_at = payload["next_attempt_at"]

    assert isinstance(
        next_attempt_at,
        (int, float),
    )

    assert not isinstance(
        next_attempt_at,
        bool,
    )

    assert next_attempt_at > 0


def test_immediate_replay_skips_job_still_in_backoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    The live retry owner's 100 ms polling cadence must not itself define
    retry timing. Durable eligibility must suppress premature replay.
    """
    path = _persist(
        monkeypatch,
        tmp_path,
    )

    payload = _payload(path)
    payload["attempts"] = 1
    payload["next_attempt_at"] = 4_000_000_000.0

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
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

    assert results[0]["queued"] is False
    assert results[0]["stage"] == "retry_backoff"


def test_backoff_eligibility_survives_restart_state_reset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Retry timing belongs to the durable envelope. Clearing process-local
    admission/future state must not make a backed-off job executable.
    """
    path = _persist(
        monkeypatch,
        tmp_path,
    )

    payload = _payload(path)
    payload["attempts"] = 1
    payload["next_attempt_at"] = 4_000_000_000.0

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    # The durable spool is the restart authority. Do not couple this
    # contract to the implementation shape of process-local admission
    # synchronization. A replay call here represents a fresh-process
    # recovery decision over the persisted envelope.
    executor = RecordingExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    results = messaging._replay_whatsapp_inbound_spool()

    assert executor.submissions == []

    assert len(results) == 1
    assert results[0]["stage"] == "retry_backoff"


def test_eligible_durable_job_still_replays(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    GREEN control: the new policy must delay jobs, not disable durable
    replay itself. A legacy job with no backoff metadata remains eligible.
    """
    _persist(
        monkeypatch,
        tmp_path,
    )

    executor = RecordingExecutor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    results = messaging._replay_whatsapp_inbound_spool()

    assert executor.submissions == [
        _message()
    ]

    assert len(results) == 1
    assert results[0]["queued"] is True
