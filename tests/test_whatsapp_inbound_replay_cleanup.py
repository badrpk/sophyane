from __future__ import annotations

import inspect
from pathlib import Path

import sophyane.cloud.messaging as messaging


def _message(
    message_id: str = "wamid.replay",
) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "restart replay proof",
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


def test_replay_seam_exists():
    replay = getattr(
        messaging,
        "_replay_whatsapp_inbound_spool",
        None,
    )

    assert callable(replay)


def test_success_cleanup_seam_exists():
    cleanup = getattr(
        messaging,
        "_remove_whatsapp_inbound_message",
        None,
    )

    assert callable(cleanup)


def test_cleanup_removes_exact_durable_job(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.cleanup-exact"
    )

    path = (
        messaging
        ._persist_whatsapp_inbound_message(
            message
        )
    )

    assert path.exists()

    messaging._remove_whatsapp_inbound_message(
        message["message_id"]
    )

    assert not path.exists()


def test_replay_submits_recovered_job_directly(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.direct-replay"
    )

    messaging._persist_whatsapp_inbound_message(
        message
    )

    submitted: list[tuple] = []

    class Future:
        def add_done_callback(
            self,
            callback,
        ):
            pass

        def exception(self):
            return None

    class Executor:
        def submit(
            self,
            function,
            *args,
            **kwargs,
        ):
            submitted.append(
                (
                    function,
                    args,
                    kwargs,
                )
            )
            return Future()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        Executor(),
    )

    def forbidden_enqueue(*args, **kwargs):
        raise AssertionError(
            "durable replay must not pass through "
            "ordinary admission/enqueue"
        )

    monkeypatch.setattr(
        messaging,
        "enqueue_whatsapp_inbound_message",
        forbidden_enqueue,
    )

    result = (
        messaging
        ._replay_whatsapp_inbound_spool()
    )

    assert len(submitted) == 1

    function, args, kwargs = submitted[0]

    assert callable(function)
    assert len(args) == 1
    assert args[0] == message
    assert kwargs == {}

    assert any(
        item["message_id"]
        == "wamid.direct-replay"
        for item in result
    )


def test_successful_worker_removes_durable_job(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.success-delete"
    )

    path = (
        messaging
        ._persist_whatsapp_inbound_message(
            message
        )
    )

    assert path.exists()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        lambda text: "reply",
    )

    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        lambda sender, reply: {
            "ok": True,
        },
    )

    result = (
        messaging
        .process_whatsapp_inbound_message(
            message
        )
    )

    assert result["ok"] is True
    assert not path.exists()


def test_conversation_failure_keeps_durable_job(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.conversation-failure"
    )

    path = (
        messaging
        ._persist_whatsapp_inbound_message(
            message
        )
    )

    def fail_conversation(text):
        raise RuntimeError(
            "conversation unavailable"
        )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        fail_conversation,
    )

    result = (
        messaging
        .process_whatsapp_inbound_message(
            message
        )
    )

    assert result["ok"] is False
    assert result["stage"] == "conversation"
    assert path.exists()


def test_send_exception_keeps_durable_job(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.send-exception"
    )

    path = (
        messaging
        ._persist_whatsapp_inbound_message(
            message
        )
    )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        lambda text: "reply",
    )

    def fail_send(sender, reply):
        raise RuntimeError(
            "send exploded"
        )

    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        fail_send,
    )

    result = (
        messaging
        .process_whatsapp_inbound_message(
            message
        )
    )

    assert result["ok"] is False
    assert result["stage"] == "send"
    assert path.exists()


def test_negative_send_keeps_durable_job(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.negative-send"
    )

    path = (
        messaging
        ._persist_whatsapp_inbound_message(
            message
        )
    )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_conversation_reply",
        lambda text: "reply",
    )

    monkeypatch.setattr(
        messaging,
        "send_whatsapp",
        lambda sender, reply: {
            "ok": False,
            "error": "not delivered",
        },
    )

    result = (
        messaging
        .process_whatsapp_inbound_message(
            message
        )
    )

    assert result["ok"] is False
    assert result["stage"] == "send"
    assert path.exists()


def test_replay_submission_failure_keeps_job_and_releases_admission(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.replay-submit-failure"
    )

    path = (
        messaging
        ._persist_whatsapp_inbound_message(
            message
        )
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

    result = (
        messaging
        ._replay_whatsapp_inbound_spool()
    )

    assert path.exists()

    matching = [
        item
        for item in result
        if item["message_id"]
        == "wamid.replay-submit-failure"
    ]

    assert len(matching) == 1
    assert matching[0]["ok"] is False
    assert matching[0]["queued"] is False
    assert matching[0]["stage"] == "handoff"

    class Future:
        def add_done_callback(
            self,
            callback,
        ):
            pass

        def exception(self):
            return None

    class AcceptingExecutor:
        def submit(
            self,
            function,
            *args,
            **kwargs,
        ):
            return Future()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        AcceptingExecutor(),
    )

    retry = (
        messaging
        .enqueue_whatsapp_inbound_message(
            message
        )
    )

    assert retry["ok"] is True
    assert retry["queued"] is True
    assert "duplicate" not in retry


def test_replay_does_not_repersist_existing_job(
    monkeypatch,
    tmp_path,
):
    _use_spool(
        monkeypatch,
        tmp_path,
    )

    message = _message(
        "wamid.no-repersist"
    )

    messaging._persist_whatsapp_inbound_message(
        message
    )

    def forbidden_persist(*args, **kwargs):
        raise AssertionError(
            "replay job is already durable"
        )

    monkeypatch.setattr(
        messaging,
        "_persist_whatsapp_inbound_message",
        forbidden_persist,
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
        def submit(
            self,
            function,
            *args,
            **kwargs,
        ):
            return Future()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        Executor(),
    )

    result = (
        messaging
        ._replay_whatsapp_inbound_spool()
    )

    assert any(
        item["message_id"]
        == "wamid.no-repersist"
        and item["ok"] is True
        and item["queued"] is True
        for item in result
    )


def test_cleanup_and_replay_never_use_outbound_outbox():
    cleanup = getattr(
        messaging,
        "_remove_whatsapp_inbound_message",
        None,
    )

    replay = getattr(
        messaging,
        "_replay_whatsapp_inbound_spool",
        None,
    )

    assert callable(cleanup)
    assert callable(replay)

    cleanup_source = inspect.getsource(
        cleanup
    )

    replay_source = inspect.getsource(
        replay
    )

    assert "WA_OUTBOX" not in cleanup_source
    assert "WA_OUTBOX" not in replay_source


def test_processor_idempotency_authority_is_preserved():
    source = inspect.getsource(
        messaging.process_whatsapp_inbound_message
    )

    assert "_begin_whatsapp_inbound(" in source
    assert "_finish_whatsapp_inbound(" in source
