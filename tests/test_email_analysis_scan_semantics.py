from sophyane.connectors.email_imap.analysis import (
    _metadata_only_query,
    _requested_result_limit,
    _requested_scan_limit,
)


def test_top_five_contacts_scans_full_window(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_EMAIL_ANALYSIS_MAX_SCAN",
        "5000",
    )

    query = (
        "Determine the five people I communicate with most frequently "
        "by email over the last 90 days. Show received count, sent "
        "count and total messages."
    )

    assert _requested_scan_limit(query) == 5000
    assert _requested_result_limit(query) == 5
    assert _metadata_only_query(query) is True


def test_last_200_received_emails_preserves_200_window(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_EMAIL_ANALYSIS_MAX_SCAN",
        "5000",
    )

    query = (
        "Analyze my last 200 received emails and classify them."
    )

    assert _requested_scan_limit(query) == 200


def test_five_attachment_results_do_not_scan_only_five(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_EMAIL_ANALYSIS_MAX_SCAN",
        "5000",
    )

    query = (
        "Find my five most recent emails containing attachments."
    )

    assert _requested_result_limit(query) == 5
    assert _requested_scan_limit(query) == 5000


def test_configured_scan_ceiling_is_bounded(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_EMAIL_ANALYSIS_MAX_SCAN",
        "999999",
    )

    assert _requested_scan_limit(
        "Top five email contacts over the last 90 days."
    ) == 20000
