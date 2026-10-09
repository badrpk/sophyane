from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import sophyane.cloud.messaging as messaging


def _message(
    message_id: str = "wamid.durable",
) -> dict[str, str]:
    return {
        "message_id": message_id,
        "sender": "923001234567",
        "text": "durable inbound proof",
    }


def test_dedicated_inbound_spool_exists():
    assert hasattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
    )

    spool = messaging.WHATSAPP_INBOUND_SPOOL

    assert isinstance(spool, Path)

    assert "whatsapp_inbound" in str(spool)
    assert spool != messaging.WA_OUTBOX
    assert spool.name != "queue.jsonl"


def test_durable_persist_seam_exists():
    persist = getattr(
        messaging,
        "_persist_whatsapp_inbound_message",
        None,
    )

    assert callable(persist)


def test_persisted_job_contains_exact_message(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path,
    )

    message = _message(
        "wamid.persist-exact"
    )

    path = (
        messaging
        ._persist_whatsapp_inbound_message(
            message
        )
    )

    assert isinstance(path, Path)
    assert path.exists()
    assert path.parent == tmp_path

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    assert payload["message"] == message
    assert (
        payload["message"]["message_id"]
        == "wamid.persist-exact"
    )


def test_persist_uses_atomic_replace():
    source = inspect.getsource(
        messaging
        ._persist_whatsapp_inbound_message
    )

    assert "os.replace(" in source


def test_enqueue_persists_before_executor_submit(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path,
    )

    events: list[str] = []

    original_persist = (
        messaging
        ._persist_whatsapp_inbound_message
    )

    def observed_persist(message):
        events.append("persist")
        return original_persist(message)

    monkeypatch.setattr(
        messaging,
        "_persist_whatsapp_inbound_message",
        observed_persist,
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
            events.append("submit")
            return Future()

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        Executor(),
    )

    messaging._reset_whatsapp_inbound_admission_for_tests()

    result = (
        messaging
        .enqueue_whatsapp_inbound_message(
            _message("wamid.order")
        )
    )

    assert result["ok"] is True
    assert result["queued"] is True

    assert events[:2] == [
        "persist",
        "submit",
    ]


def test_persistence_failure_prevents_submission(
    monkeypatch,
):
    calls = 0

    def fail_persist(message):
        raise OSError(
            "durable spool unavailable"
        )

    monkeypatch.setattr(
        messaging,
        "_persist_whatsapp_inbound_message",
        fail_persist,
    )

    class Executor:
        def submit(
            self,
            function,
            *args,
            **kwargs,
        ):
            nonlocal calls
            calls += 1
            raise AssertionError(
                "must not submit after "
                "persistence failure"
            )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        Executor(),
    )

    messaging._reset_whatsapp_inbound_admission_for_tests()

    result = (
        messaging
        .enqueue_whatsapp_inbound_message(
            _message(
                "wamid.persist-failure"
            )
        )
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["stage"] == "handoff"
    assert calls == 0


def test_restart_recovery_seam_exists():
    recover = getattr(
        messaging,
        "_recover_whatsapp_inbound_spool",
        None,
    )

    assert callable(recover)


def test_persisted_job_survives_memory_reset(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path,
    )

    message = _message(
        "wamid.restart-proof"
    )

    path = (
        messaging
        ._persist_whatsapp_inbound_message(
            message
        )
    )

    assert path.exists()

    messaging._reset_whatsapp_inbound_admission_for_tests()

    recovered = (
        messaging
        ._recover_whatsapp_inbound_spool()
    )

    assert any(
        item["message_id"]
        == "wamid.restart-proof"
        for item in recovered
    )


def test_recovery_restores_duplicate_admission(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path,
    )

    message = _message(
        "wamid.restart-duplicate"
    )

    messaging._persist_whatsapp_inbound_message(
        message
    )

    messaging._reset_whatsapp_inbound_admission_for_tests()

    messaging._recover_whatsapp_inbound_spool()

    class Executor:
        def submit(
            self,
            function,
            *args,
            **kwargs,
        ):
            raise AssertionError(
                "recovered wamid must not "
                "be submitted twice"
            )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        Executor(),
    )

    result = (
        messaging
        .enqueue_whatsapp_inbound_message(
            message
        )
    )

    assert result["ok"] is True
    assert result["queued"] is False
    assert result["duplicate"] is True


def test_inbound_spool_is_not_outbound_outbox():
    enqueue_source = inspect.getsource(
        messaging
        .enqueue_whatsapp_inbound_message
    )

    persist = getattr(
        messaging,
        "_persist_whatsapp_inbound_message",
        None,
    )

    assert callable(persist)

    persist_source = inspect.getsource(
        persist
    )

    assert "WA_OUTBOX" not in enqueue_source
    assert "WA_OUTBOX" not in persist_source
