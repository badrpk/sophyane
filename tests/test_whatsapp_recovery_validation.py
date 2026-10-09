from __future__ import annotations

import hashlib
import json

import pytest

import sophyane.cloud.messaging as messaging


class RecordingFuture:
    def __init__(self):
        self.callback = None

    def add_done_callback(self, callback):
        self.callback = callback

    def result(self):
        return {
            "ok": True,
        }

    def exception(self):
        return None


class RecordingExecutor:
    def __init__(self):
        self.submissions = []
        self.futures = []

    def submit(self, fn, message):
        future = RecordingFuture()

        self.submissions.append(
            (fn, dict(message))
        )
        self.futures.append(future)

        return future


@pytest.fixture
def isolated_recovery(monkeypatch, tmp_path):
    spool = tmp_path / "inbound"
    executor = RecordingExecutor()

    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        spool,
    )
    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_capacity_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()
    messaging._whatsapp_inbound_futures.clear()

    yield spool, executor

    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_capacity_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()
    messaging._whatsapp_inbound_futures.clear()


def _path_for(spool, key):
    digest = hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()

    return spool / f"{digest}.json"


def _write_payload(spool, key, payload):
    spool.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = _path_for(
        spool,
        key,
    )

    path.write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    return path


def _write_message(
    spool,
    key,
    *,
    message_id,
    sender,
    text,
):
    return _write_payload(
        spool,
        key,
        {
            "message": {
                "message_id": message_id,
                "sender": sender,
                "text": text,
            }
        },
    )


@pytest.mark.parametrize(
    (
        "key",
        "message_id",
        "sender",
        "text",
    ),
    [
        (
            "empty-id",
            "",
            "923001234567",
            "hello",
        ),
        (
            "empty-sender",
            "wamid.empty-sender",
            "",
            "hello",
        ),
        (
            "empty-text",
            "wamid.empty-text",
            "923001234567",
            "",
        ),
    ],
)
def test_recovery_rejects_incomplete_message(
    isolated_recovery,
    key,
    message_id,
    sender,
    text,
):
    spool, _ = isolated_recovery

    path = _write_message(
        spool,
        key,
        message_id=message_id,
        sender=sender,
        text=text,
    )

    recovered = (
        messaging._recover_whatsapp_inbound_spool()
    )

    assert recovered == []

    # Validation failure must not silently erase durable
    # evidence. Cleanup/quarantine is a separate authority.
    assert path.exists()


def test_recovery_rejects_non_string_message_fields(
    isolated_recovery,
):
    spool, _ = isolated_recovery

    path = _write_payload(
        spool,
        "non-string-fields",
        {
            "message": {
                "message_id": 123,
                "sender": ["923001234567"],
                "text": {
                    "body": "hello",
                },
            }
        },
    )

    recovered = (
        messaging._recover_whatsapp_inbound_spool()
    )

    assert recovered == []
    assert path.exists()


def test_replay_does_not_submit_incomplete_durable_jobs(
    isolated_recovery,
):
    spool, executor = isolated_recovery

    paths = [
        _write_message(
            spool,
            "replay-empty-id",
            message_id="",
            sender="923001234567",
            text="hello",
        ),
        _write_message(
            spool,
            "replay-empty-sender",
            message_id="wamid.replay-empty-sender",
            sender="",
            text="hello",
        ),
        _write_message(
            spool,
            "replay-empty-text",
            message_id="wamid.replay-empty-text",
            sender="923001234567",
            text="",
        ),
    ]

    results = (
        messaging._replay_whatsapp_inbound_spool()
    )

    assert results == []
    assert executor.submissions == []
    assert messaging._whatsapp_inbound_pending == 0
    assert messaging._whatsapp_inbound_futures == set()
    assert messaging._whatsapp_inbound_admitted == {}

    assert all(
        path.exists()
        for path in paths
    )


def test_recovery_accepts_complete_message(
    isolated_recovery,
):
    spool, _ = isolated_recovery

    message = {
        "message_id": "wamid.recovery-valid",
        "sender": "923001234567",
        "text": "hello",
    }

    _write_payload(
        spool,
        "valid",
        {
            "message": message,
        },
    )

    recovered = (
        messaging._recover_whatsapp_inbound_spool()
    )

    assert recovered == [message]


def test_corrupt_durable_record_remains_non_executable(
    isolated_recovery,
):
    spool, executor = isolated_recovery

    spool.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = _path_for(
        spool,
        "corrupt",
    )

    path.write_text(
        "{not-json\n",
        encoding="utf-8",
    )

    recovered = (
        messaging._recover_whatsapp_inbound_spool()
    )

    assert recovered == []
    assert executor.submissions == []
    assert path.exists()


def test_recovery_validation_does_not_use_outbound_outbox():
    import inspect

    recovery = inspect.getsource(
        messaging._recover_whatsapp_inbound_spool
    )
    replay = inspect.getsource(
        messaging._replay_whatsapp_inbound_spool
    )

    assert "WA_OUTBOX" not in recovery
    assert "WA_OUTBOX" not in replay
