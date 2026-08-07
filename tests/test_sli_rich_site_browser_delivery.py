from pathlib import Path
from unittest.mock import patch

from sophyane.code_memory.sli_rich_site_compose import (
    _open_generated_site,
)


def _site(
    tmp_path: Path,
) -> Path:
    target = tmp_path / "index.html"

    target.write_text(
        (
            "<!doctype html>"
            "<html>"
            "<body>"
            "<h1>Verified site</h1>"
            "</body>"
            "</html>"
        ),
        encoding="utf-8",
    )

    return target


def test_rich_site_uses_verified_http_browser_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = _site(tmp_path)

    monkeypatch.delenv(
        "SOPHYANE_NO_BROWSER",
        raising=False,
    )

    with patch(
        "sophyane.browser_runtime_v2."
        "open_verified_browser",
        return_value=(
            True,
            (
                "Browser URL: "
                "http://127.0.0.1:43210/index.html\n"
                "HTTP verification: SHA-256 matched abc123"
            ),
        ),
    ) as verified:
        opened, evidence = (
            _open_generated_site(
                target,
                lambda _message: None,
            )
        )

    assert opened is True
    assert (
        "http://127.0.0.1:"
        in evidence
    )
    assert (
        "HTTP verification:"
        in evidence
    )

    verified.assert_called_once()

    args = verified.call_args.args

    assert args[0] == tmp_path.resolve()


def test_rich_site_no_browser_flag_prevents_delivery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = _site(tmp_path)

    monkeypatch.setenv(
        "SOPHYANE_NO_BROWSER",
        "1",
    )

    with patch(
        "sophyane.browser_runtime_v2."
        "open_verified_browser",
    ) as verified:
        opened, evidence = (
            _open_generated_site(
                target,
                lambda _message: None,
            )
        )

    assert opened is False

    assert (
        "SOPHYANE_NO_BROWSER"
        in evidence
    )

    verified.assert_not_called()


def test_rich_site_missing_file_does_not_start_browser(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = (
        tmp_path
        / "index.html"
    )

    monkeypatch.delenv(
        "SOPHYANE_NO_BROWSER",
        raising=False,
    )

    with patch(
        "sophyane.browser_runtime_v2."
        "open_verified_browser",
    ) as verified:
        opened, evidence = (
            _open_generated_site(
                target,
                lambda _message: None,
            )
        )

    assert opened is False

    assert "missing" in evidence.lower()

    verified.assert_not_called()


def test_verified_browser_failure_is_reported_safely(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = _site(tmp_path)

    monkeypatch.delenv(
        "SOPHYANE_NO_BROWSER",
        raising=False,
    )

    with patch(
        "sophyane.browser_runtime_v2."
        "open_verified_browser",
        side_effect=RuntimeError(
            "preview failure"
        ),
    ):
        opened, evidence = (
            _open_generated_site(
                target,
                lambda _message: None,
            )
        )

    assert opened is False

    assert (
        "Verified browser launch failed"
        in evidence
    )

    assert (
        "preview failure"
        in evidence
    )
