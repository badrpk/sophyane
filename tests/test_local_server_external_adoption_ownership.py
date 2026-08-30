from __future__ import annotations

from pathlib import Path


def test_discovered_server_is_not_persisted_as_owned():
    text = Path(
        "src/sophyane/local_server.py"
    ).read_text(
        encoding="utf-8",
    )

    marker = (
        "SOPHYANE_DISCOVERY_IS_NOT_OWNERSHIP_V1"
    )

    assert marker in text

    start = text.index(
        marker
    )

    region = text[
        start:
        start + 1400
    ]

    assert (
        "return discovered_pid"
        in region
    )

    assert (
        "_write_pid(discovered_pid)"
        not in region
    )


def test_stalled_recovery_requires_recorded_owned_pid():
    text = Path(
        "src/sophyane/local_server.py"
    ).read_text(
        encoding="utf-8",
    )

    marker = (
        "SOPHYANE_TERMINATE_ONLY_RECORDED_OWNER_V1"
    )

    assert marker in text

    start = text.index(
        marker
    )

    region = text[
        start:
        start + 1800
    ]

    assert (
        "old_pid = _read_pid()"
        in region
    )

    assert (
        "old_pid <= 0"
        in region
    )

    # Process-instance ownership is now the authoritative
    # automatic-termination gate.  It includes the earlier
    # executable/model/port match and additionally proves
    # boot/start-instance provenance.
    assert (
        "_owned_process_matches("
        in region
    )

    terminate = region.index(
        "_terminate_process_group("
    )

    ownership_check = region.index(
        "_owned_process_matches("
    )

    assert ownership_check < terminate


def test_external_discovery_and_termination_are_separate_contracts():
    text = Path(
        "src/sophyane/local_server.py"
    ).read_text(
        encoding="utf-8",
    )

    discovery = text.index(
        "SOPHYANE_DISCOVERY_IS_NOT_OWNERSHIP_V1"
    )

    termination = text.index(
        "SOPHYANE_TERMINATE_ONLY_RECORDED_OWNER_V1"
    )

    assert discovery < termination
