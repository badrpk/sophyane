from __future__ import annotations

import json

import sophyane.cloud.messaging as messaging


MESSAGE_ID = "wamid.commit-point-signal"


def _message(
    text: str = "new attempt",
) -> dict[str, str]:
    return {
        "message_id": MESSAGE_ID,
        "from": "15550000005",
        "text": text,
    }


def test_preexisting_target_does_not_imply_current_commit_uncertainty(
    monkeypatch,
    tmp_path,
):
    """
    Evidence left by an older attempt cannot prove that the current
    persistence attempt reached os.replace().
    """
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "spool",
    )

    messaging.WHATSAPP_INBOUND_SPOOL.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = messaging._whatsapp_inbound_spool_path(
        MESSAGE_ID
    )

    old_payload = {
        "message": _message("old durable evidence"),
        "attempts": 1,
    }

    target.write_text(
        json.dumps(
            old_payload,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    before = target.read_text(
        encoding="utf-8"
    )

    def fail_before_replace(message):
        raise OSError(
            "synthetic pre-replace persistence failure"
        )

    monkeypatch.setattr(
        messaging,
        "_persist_whatsapp_inbound_message",
        fail_before_replace,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message()
    )

    after = target.read_text(
        encoding="utf-8"
    )

    assert before == after

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["message_id"] == MESSAGE_ID

    # The current attempt never reached replace.
    assert result["stage"] == "handoff"

    # Existing evidence belongs to an older attempt and must not be
    # represented as evidence that this attempt reached commit.
    assert result.get("durable_evidence") is not True


def test_post_replace_directory_sync_failure_remains_uncertain(
    monkeypatch,
    tmp_path,
):
    """
    A real current-attempt replace followed by directory-fsync failure
    must retain the 3K.9-G durability-uncertain classification.
    """
    monkeypatch.setattr(
        messaging,
        "WHATSAPP_INBOUND_SPOOL",
        tmp_path / "spool",
    )

    def fail_directory_sync() -> None:
        raise OSError(
            "synthetic post-replace directory fsync failure"
        )

    monkeypatch.setattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        fail_directory_sync,
    )

    result = messaging.enqueue_whatsapp_inbound_message(
        _message()
    )

    target = messaging._whatsapp_inbound_spool_path(
        MESSAGE_ID
    )

    assert target.exists()

    payload = json.loads(
        target.read_text(encoding="utf-8")
    )

    assert (
        payload["message"]["message_id"]
        == MESSAGE_ID
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["stage"] == "durability_uncertain"
    assert result["durable_evidence"] is True


def test_commit_classification_is_not_derived_from_target_exists():
    """
    The enqueue exception boundary must not infer commit progress from
    target existence. That cannot distinguish old durable state from a
    replace performed by the current attempt.
    """
    import inspect

    source = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )

    persist = source.index(
        "_persist_whatsapp_inbound_message("
    )

    exception = source.index(
        "except Exception as exc:",
        persist,
    )

    failure_block = source[
        exception:
        source.index(
            "if not _claim_whatsapp_inbound_capacity()",
            exception,
        )
    ]

    assert ".exists()" not in failure_block


def test_commit_signal_contract_does_not_use_outbound_outbox():
    import inspect

    source = inspect.getsource(
        messaging.enqueue_whatsapp_inbound_message
    )

    assert "WA_OUTBOX" not in source
