from __future__ import annotations

import json
from pathlib import Path

import pytest

import sophyane.cloud.messaging as messaging


MESSAGE = {
    "message_id": "wamid.durable-retry-budget",
    "sender": "15550000001",
    "text": "durable retry budget",
}


def _reset_process_local_state() -> None:
    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_admission_for_tests",
        None,
    )
    if callable(reset):
        reset()

    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_idempotency_for_tests",
        None,
    )
    if callable(reset):
        reset()


@pytest.fixture
def isolated_spool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spool = tmp_path / "whatsapp-inbound"
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        spool,
    )

    _reset_process_local_state()
    yield spool
    _reset_process_local_state()


def _payload_for(message_id: str) -> dict:
    path = messaging._whatsapp_inbound_spool_path(message_id)
    return json.loads(path.read_text(encoding="utf-8"))


def test_new_durable_job_starts_with_zero_failed_attempts(
    isolated_spool: Path,
) -> None:
    """
    Retry history belongs to the durable job.

    A freshly persisted inbound message has made zero failed processing
    attempts.  The value must live in the spool payload rather than only
    in process-local memory.
    """
    messaging._persist_whatsapp_inbound_message(dict(MESSAGE))

    payload = _payload_for(MESSAGE["message_id"])

    assert payload["message"] == MESSAGE
    assert payload["attempts"] == 0


class _FailedFuture:
    def result(self):
        return {
            "ok": False,
            "stage": "send",
            "message_id": MESSAGE["message_id"],
        }


def test_failed_worker_completion_is_recorded_durably(
    isolated_spool: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A completed worker failure consumes one durable retry attempt.

    The accounting must happen before another live/startup replay can
    decide whether the job is still eligible.
    """
    messaging._persist_whatsapp_inbound_message(dict(MESSAGE))

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_future_done",
        lambda _future: None,
    )

    callback = messaging._whatsapp_inbound_completion_callback(
        MESSAGE["message_id"]
    )
    callback(_FailedFuture())

    payload = _payload_for(MESSAGE["message_id"])

    assert payload["attempts"] == 1


class _RecordingFuture:
    def __init__(self) -> None:
        self.callbacks = []

    def add_done_callback(self, callback) -> None:
        self.callbacks.append(callback)


class _RecordingExecutor:
    def __init__(self) -> None:
        self.submit_calls = []

    def submit(self, function, *args, **kwargs):
        self.submit_calls.append((function, args, kwargs))
        return _RecordingFuture()


def test_exhausted_durable_job_is_not_resubmitted_after_restart(
    isolated_spool: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Durable retry exhaustion survives loss of all process-local state.

    An exhausted job remains durable evidence, but replay must not submit
    it to another worker indefinitely.

    The test supplies a policy ceiling of three attempts without requiring
    the production constant to exist yet.  The implementation may expose
    that constant in the minimal GREEN patch.
    """
    message_id = MESSAGE["message_id"]

    path = messaging._whatsapp_inbound_spool_path(message_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "message": dict(MESSAGE),
                "attempts": 3,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    # Simulate a fresh process: durable disk state survives, local
    # admission/idempotency state does not.
    _reset_process_local_state()

    monkeypatch.setattr(
        messaging,
        "_WHATSAPP_INBOUND_MAX_ATTEMPTS",
        3,
        raising=False,
    )

    executor = _RecordingExecutor()
    monkeypatch.setattr(
        messaging,
        "_WHATSAPP_INBOUND_EXECUTOR",
        executor,
        raising=False,
    )

    # Some revisions expose the executor under the generic worker name.
    # Patch it as well if replay uses that authority.
    for name in (
        "_whatsapp_inbound_executor",
        "WHATSAPP_INBOUND_EXECUTOR",
    ):
        if hasattr(messaging, name):
            monkeypatch.setattr(
                messaging,
                name,
                executor,
            )

    results = messaging._replay_whatsapp_inbound_spool()

    assert executor.submit_calls == []
    assert path.exists()
    assert _payload_for(message_id)["attempts"] == 3

    # Replay may report terminal/exhausted state in its result, but the
    # essential contract is deliberately representation-independent:
    # no worker submission is allowed after durable exhaustion.
    assert isinstance(results, list)


def test_retry_budget_is_enforced_by_live_retry_authority_too(
    isolated_spool: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Startup replay and same-process live retry share one durable policy.

    The live retry authority must not bypass the durable attempt ceiling.
    """
    message_id = MESSAGE["message_id"]

    path = messaging._whatsapp_inbound_spool_path(message_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "message": dict(MESSAGE),
                "attempts": 3,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    _reset_process_local_state()

    monkeypatch.setattr(
        messaging,
        "_WHATSAPP_INBOUND_MAX_ATTEMPTS",
        3,
        raising=False,
    )

    executor = _RecordingExecutor()

    monkeypatch.setattr(
        messaging,
        "_WHATSAPP_INBOUND_EXECUTOR",
        executor,
        raising=False,
    )

    for name in (
        "_whatsapp_inbound_executor",
        "WHATSAPP_INBOUND_EXECUTOR",
    ):
        if hasattr(messaging, name):
            monkeypatch.setattr(
                messaging,
                name,
                executor,
            )

    results = messaging._retry_whatsapp_inbound_spool()

    assert executor.submit_calls == []
    assert path.exists()
    assert _payload_for(message_id)["attempts"] == 3
    assert isinstance(results, list)
