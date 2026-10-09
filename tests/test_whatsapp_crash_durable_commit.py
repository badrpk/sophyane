from __future__ import annotations

import inspect
from pathlib import Path

import sophyane.cloud.messaging as messaging


def _source(name: str) -> str:
    return inspect.getsource(
        getattr(messaging, name)
    )


def test_initial_persist_flushes_file_before_replace():
    source = _source(
        "_persist_whatsapp_inbound_message"
    )

    flush = source.index("stream.flush()")
    fsync = source.index("os.fsync(")
    replace = source.index("os.replace(")

    assert flush < fsync < replace


def test_retry_accounting_flushes_file_before_replace():
    source = _source(
        "_record_whatsapp_inbound_failed_attempt"
    )

    flush = source.index("stream.flush()")
    fsync = source.index("os.fsync(")
    replace = source.index("os.replace(")

    assert flush < fsync < replace


def test_crash_durable_directory_commit_authority_exists():
    helper = getattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        None,
    )

    assert callable(helper)


def test_initial_persist_syncs_directory_after_replace():
    source = _source(
        "_persist_whatsapp_inbound_message"
    )

    replace = source.index("os.replace(")

    directory_sync = source.index(
        "_fsync_whatsapp_inbound_directory(",
        replace,
    )

    assert replace < directory_sync


def test_retry_accounting_syncs_directory_after_replace():
    source = _source(
        "_record_whatsapp_inbound_failed_attempt"
    )

    replace = source.index("os.replace(")

    directory_sync = source.index(
        "_fsync_whatsapp_inbound_directory(",
        replace,
    )

    assert replace < directory_sync


def test_directory_commit_authority_syncs_directory_fd():
    helper = getattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        None,
    )

    assert callable(helper)

    source = inspect.getsource(helper)

    assert "os.open(" in source
    assert "os.fsync(" in source
    assert "os.close(" in source


def test_directory_commit_authority_is_spool_scoped():
    helper = getattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        None,
    )

    assert callable(helper)

    source = inspect.getsource(helper)

    assert "WHATSAPP_INBOUND_SPOOL" in source


def test_crash_durability_contract_does_not_use_outbound_outbox():
    source = "\n".join(
        (
            _source(
                "_persist_whatsapp_inbound_message"
            ),
            _source(
                "_record_whatsapp_inbound_failed_attempt"
            ),
        )
    )

    helper = getattr(
        messaging,
        "_fsync_whatsapp_inbound_directory",
        None,
    )

    if callable(helper):
        source += "\n" + inspect.getsource(helper)

    assert "WA_OUTBOX" not in source
