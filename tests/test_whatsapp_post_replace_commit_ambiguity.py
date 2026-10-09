from __future__ import annotations

import json

import pytest

import sophyane.cloud.messaging as messaging


MESSAGE_ID = "wamid.post-replace-ambiguity"


def _message() -> dict[str, str]:
    return {
        "message_id": MESSAGE_ID,
        "from": "15550000003",
        "text": "post replace ambiguity",
    }


def _fail_directory_sync() -> None:
    raise OSError(
        "synthetic post-replace directory fsync failure"
    )


def test_post_replace_failure_preserves_committed_spool_evidence(
    monkeypatch,
    tmp_path,
):
    """
    os.replace() has already installed the target before directory fsync
    fails. The failure must not erase or roll back that visible durable
    evidence.
    """
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "spool",
    )

    monkeypatch.setattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        _fail_directory_sync,
    )

    target = messaging._whatsapp_inbound_spool_path(
        MESSAGE_ID
    )

    with pytest.raises(OSError):
        messaging._persist_whatsapp_inbound_message(
            _message()
        )

    assert target.exists()

    payload = json.loads(
        target.read_text(encoding="utf-8")
    )

    assert payload["message"]["message_id"] == MESSAGE_ID
    assert payload["attempts"] == 0


def test_enqueue_distinguishes_post_replace_durability_uncertainty(
    monkeypatch,
    tmp_path,
):
    """
    A directory fsync failure after replace is not equivalent to a
    pre-commit persistence failure: the spool target already exists.

    The enqueue boundary must report that distinct state explicitly.
    """
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "spool",
    )

    monkeypatch.setattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        _fail_directory_sync,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message()
    )

    target = messaging._whatsapp_inbound_spool_path(
        MESSAGE_ID
    )

    assert target.exists()

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["message_id"] == MESSAGE_ID

    assert result["stage"] == "durability_uncertain"
    assert result["durable_evidence"] is True


def test_durability_uncertainty_does_not_submit_worker(
    monkeypatch,
    tmp_path,
):
    """
    Until directory metadata durability is confirmed, the newly visible
    job must not also be submitted as successfully committed work.
    """
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "spool",
    )

    monkeypatch.setattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        _fail_directory_sync,
    )

    submitted = []

    class Executor:
        def submit(self, *args, **kwargs):
            submitted.append(
                (args, kwargs)
            )
            raise AssertionError(
                "worker submission must not occur "
                "after uncertain directory commit"
            )

    monkeypatch.setattr(
        messaging,
        "_whatsapp_inbound_executor",
        Executor(),
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message()
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["stage"] == "durability_uncertain"
    assert submitted == []


def test_retry_accounting_post_replace_failure_remains_contained(
    monkeypatch,
    tmp_path,
):
    """
    Retry accounting already has a completion-callback containment
    boundary. Preserve the committed attempt update even if the following
    directory fsync fails.
    """
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "spool",
    )

    messaging._persist_whatsapp_inbound_message(
        _message()
    )

    target = messaging._whatsapp_inbound_spool_path(
        MESSAGE_ID
    )

    monkeypatch.setattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        _fail_directory_sync,
    )

    with pytest.raises(OSError):
        messaging._record_whatsapp_inbound_failed_attempt(
            MESSAGE_ID
        )

    payload = json.loads(
        target.read_text(encoding="utf-8")
    )

    assert payload["attempts"] == 1
    assert "next_attempt_at" in payload


def test_uncertain_commit_contract_does_not_use_outbound_outbox():
    import inspect

    source = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )

    assert "WA_OUTBOX" not in source
