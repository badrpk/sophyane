from __future__ import annotations

import inspect
from pathlib import Path

import sophyane.cloud.messaging as messaging


def _message(
    message_id: str,
) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "backpressure proof",
    }


def _use_spool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path,
    )

    messaging._reset_whatsapp_inbound_admission_for_tests()
    messaging._reset_whatsapp_inbound_idempotency_for_tests()


def test_backpressure_limit_exists():
    limit = getattr(
        messaging,
        "_WHATSAPP_INBOUND_PENDING_LIMIT",
        None,
    )

    assert isinstance(limit, int)
    assert 1 <= limit <= 4096


def test_backpressure_claim_and_release_seams_exist():
    claim = getattr(
        messaging,
        "_claim_whatsapp_inbound_capacity",
        None,
    )

    release = getattr(
        messaging,
        "_release_whatsapp_inbound_capacity",
        None,
    )

    assert callable(claim)
    assert callable(release)


def test_backpressure_reset_seam_exists():
    reset = getattr(
        messaging,
        "_reset_whatsapp_inbound_capacity_for_tests",
        None,
    )

    assert callable(reset)


def test_capacity_has_hard_bound():
    reset = messaging._reset_whatsapp_inbound_capacity_for_tests
    claim = messaging._claim_whatsapp_inbound_capacity
    release = messaging._release_whatsapp_inbound_capacity
    limit = messaging._WHATSAPP_INBOUND_PENDING_LIMIT

    reset()

    claimed = 0

    for _ in range(limit):
        assert claim() is True
        claimed += 1

    assert claimed == limit
    assert claim() is False

    release()

    assert claim() is True

    reset()


def test_enqueue_persists_before_capacity_decision(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    events = []

    def fake_persist(message):
        events.append("persist")

        path = tmp_path / "durable.json"
        path.write_text(
            "{}",
            encoding="utf-8",
        )

        return path

    def reject_capacity():
        events.append("capacity")
        return False

    monkeypatch.setattr(
        messaging,
        "_persist_whatsapp_inbound_message",
        fake_persist,
    )

    monkeypatch.setattr(
        messaging,
        "_claim_whatsapp_inbound_capacity",
        reject_capacity,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.persist-before-capacity")
    )

    assert events == [
        "persist",
        "capacity",
    ]

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["stage"] == "backpressure"


def test_backpressure_does_not_submit_to_executor(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    class ForbiddenExecutor:
        def submit(self, *args, **kwargs):
            raise AssertionError(
                "executor must not receive work "
                "after capacity rejection"
            )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        ForbiddenExecutor(),
    )

    monkeypatch.setattr(
        messaging,
        "_claim_whatsapp_inbound_capacity",
        lambda: False,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.capacity-reject")
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["stage"] == "backpressure"


def test_backpressure_keeps_durable_job(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    monkeypatch.setattr(
        messaging,
        "_claim_whatsapp_inbound_capacity",
        lambda: False,
    )

    message = _message(
        "wamid.durable-backpressure"
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    path = messaging._whatsapp_inbound_spool_path(
        message["message_id"]
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["stage"] == "backpressure"
    assert path.exists()


def test_backpressure_releases_admission_for_retry(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    decisions = iter(
        [
            False,
            True,
        ]
    )

    monkeypatch.setattr(
        messaging,
        "_claim_whatsapp_inbound_capacity",
        lambda: next(decisions),
    )

    class Future:
        def add_done_callback(
            self,
            callback,
        ):
            pass

        def exception(self):
            return None

    class Executor:
        def __init__(self):
            self.calls = 0

        def submit(
            self,
            function,
            *args,
            **kwargs,
        ):
            self.calls += 1
            return Future()

    executor = Executor()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        executor,
    )

    message = _message(
        "wamid.retry-after-backpressure"
    )

    first = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    second = messaging.enqueue_whatsapp_inbound_message(
        message
    )

    assert first["ok"] is False
    assert first["queued"] is False
    assert first["stage"] == "backpressure"

    assert second["ok"] is True
    assert second["queued"] is True
    assert "duplicate" not in second

    assert executor.calls == 1


def test_executor_submission_failure_releases_capacity(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    claimed = []
    released = []

    def claim():
        claimed.append(True)
        return True

    def release():
        released.append(True)

    monkeypatch.setattr(
        messaging,
        "_claim_whatsapp_inbound_capacity",
        claim,
    )

    monkeypatch.setattr(
        messaging,
        "_release_whatsapp_inbound_capacity",
        release,
    )

    class RejectingExecutor:
        def submit(
            self,
            function,
            *args,
            **kwargs,
        ):
            raise RuntimeError(
                "executor unavailable"
            )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        RejectingExecutor(),
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message("wamid.submit-release")
    )

    assert result["ok"] is False
    assert result["stage"] == "handoff"

    assert len(claimed) == 1
    assert len(released) == 1


def test_completed_future_releases_capacity(
    monkeypatch,
):
    released = []

    monkeypatch.setattr(
        messaging,
        "_release_whatsapp_inbound_capacity",
        lambda: released.append(True),
    )

    class Future:
        def exception(self):
            return None

    messaging._whatsapp_inbound_future_done(
        Future()
    )

    assert released == [True]


def test_replay_obeys_same_capacity_bound(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.replay-backpressure"
    )

    path = messaging._persist_whatsapp_inbound_message(
        message
    )

    assert path.exists()

    monkeypatch.setattr(
        messaging,
        "_claim_whatsapp_inbound_capacity",
        lambda: False,
    )

    class ForbiddenExecutor:
        def submit(self, *args, **kwargs):
            raise AssertionError(
                "replay must obey capacity bound"
            )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        ForbiddenExecutor(),
    )

    result = messaging._replay_whatsapp_inbound_spool()

    matching = [
        item
        for item in result
        if item["message_id"]
        == "wamid.replay-backpressure"
    ]

    assert len(matching) == 1

    assert matching[0]["ok"] is False
    assert matching[0]["queued"] is False
    assert matching[0]["stage"] == "backpressure"

    assert path.exists()


def test_backpressure_does_not_move_processor_idempotency():
    enqueue_source = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )

    processor_source = inspect.getsource(
        messaging.process_whatsapp_inbound_message
    )

    assert "_begin_whatsapp_inbound(" not in enqueue_source
    assert "_finish_whatsapp_inbound(" not in enqueue_source

    assert "_begin_whatsapp_inbound(" in processor_source
    assert "_finish_whatsapp_inbound(" in processor_source


def test_backpressure_never_uses_outbound_outbox():
    functions = (
        getattr(
            messaging,
            "_claim_whatsapp_inbound_capacity",
            None,
        ),
        getattr(
            messaging,
            "_release_whatsapp_inbound_capacity",
            None,
        ),
    )

    for function in functions:
        assert callable(function)

        source = inspect.getsource(
            function
        )

        assert "WA_OUTBOX" not in source
