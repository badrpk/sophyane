from pathlib import Path
from unittest.mock import patch

from sophyane.rendered_evidence import (
    RenderedEvidence,
    _headless_command,
    _result_from_payload,
    capture_rendered_evidence,
)


def test_headless_command_locks_absolute_subprocess_path(
    tmp_path: Path,
) -> None:
    headless = (
        tmp_path
        / "headless_shell"
    )

    profile = (
        tmp_path
        / "profile"
    )

    command = _headless_command(
        headless,
        port=9233,
        profile=profile,
    )

    expected = (
        "--browser-subprocess-path="
        + str(
            headless.resolve()
        )
    )

    assert command[0] == str(
        headless.resolve()
    )

    assert expected in command

    assert (
        "--remote-debugging-port=9233"
        in command
    )

    assert not any(
        item.startswith(
            "TERMUX_EXEC"
        )
        for item in command
    )


def test_render_payload_becomes_structured_evidence() -> None:
    url = (
        "http://127.0.0.1:"
        "8788/index.html"
    )

    result = _result_from_payload(
        url,
        {
            "href":
                url,

            "title":
                "Demis Hassabis — "
                "Sophyane Storyworld",

            "readyState":
                "complete",

            "htmlLength":
                1_840_143,

            "bodyTextLength":
                5_834,

            "viewport": {
                "width":
                    390,

                "height":
                    844,
            },

            "document": {
                "width":
                    390,

                "height":
                    8_812,
            },

            "horizontalOverflow":
                False,

            "counts": {
                "elements":
                    168,

                "images":
                    11,

                "brokenImages":
                    1,

                "buttons":
                    14,

                "anchors":
                    3,

                "inputs":
                    1,

                "interactive":
                    18,
            },

            "consoleErrors":
                0,

            "logErrors":
                0,

            "screenshotBytes":
                349_943,
        },
    )

    assert result.ok is True
    assert result.available is True

    assert (
        result.viewport_width
        == 390
    )

    assert (
        result.document_width
        == 390
    )

    assert (
        result.horizontal_overflow
        is False
    )

    assert result.elements == 168
    assert result.images == 11
    assert result.broken_images == 1

    assert (
        result.screenshot_bytes
        == 349_943
    )

    summary = result.summary()

    assert (
        "Rendered evidence: PASS"
        in summary
    )

    assert (
        "viewport=390x844"
        in summary
    )

    assert (
        "horizontal_overflow=False"
        in summary
    )


def test_missing_headless_shell_is_nonfatal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prefix = (
        tmp_path
        / "termux"
    )

    monkeypatch.setenv(
        "PREFIX",
        str(prefix),
    )

    result = (
        capture_rendered_evidence(
            (
                "http://127.0.0.1:"
                "9999/index.html"
            ),
            tmp_path,
            lambda _message: None,
        )
    )

    assert result.available is False
    assert result.ok is False

    assert (
        "headless_shell"
        in result.error
    )


def test_rendered_evidence_summary_is_safe_on_failure() -> None:
    result = RenderedEvidence(
        available=True,
        ok=False,
        backend=(
            "termux-headless-shell-cdp"
        ),
        url=(
            "http://127.0.0.1/"
        ),
        error=(
            "probe failed"
        ),
    )

    assert (
        result.summary()
        ==
        (
            "Rendered evidence: FAIL; "
            "backend="
            "termux-headless-shell-cdp"
            ": probe failed"
        )
    )


def test_verified_browser_result_includes_rendered_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sophyane import (
        browser_runtime_v2,
    )

    target = (
        tmp_path
        / "index.html"
    )

    target.write_text(
        (
            "<!doctype html>"
            "<html>"
            "<head>"
            "<meta charset=\"utf-8\">"
            "<title>Rendered test site</title>"
            "</head>"
            "<body>"
            "<main>"
            "<h1>Rendered</h1>"
            "<p>"
            "This fixture is intentionally substantial enough "
            "to satisfy the verified browser runtime minimum "
            "artifact-size contract."
            "</p>"
            "</main>"
            "</body>"
            "</html>"
        ),
        encoding="utf-8",
    )

    rendered = RenderedEvidence(
        available=True,
        ok=True,
        backend=(
            "termux-headless-shell-cdp"
        ),
        url="unused",
        title="Rendered",
        viewport_width=390,
        viewport_height=844,
        document_width=390,
        document_height=844,
        elements=5,
        screenshot_bytes=4096,
    )

    original_which = (
        browser_runtime_v2
        .shutil
        .which
    )

    def fake_which(
        executable: str,
    ) -> str | None:
        if (
            executable
            == "termux-open-url"
        ):
            return (
                "/data/data/"
                "com.termux/files/usr/"
                "bin/termux-open-url"
            )

        return original_which(
            executable
        )

    monkeypatch.setattr(
        browser_runtime_v2.shutil,
        "which",
        fake_which,
    )

    with patch(
        "sophyane.rendered_evidence."
        "capture_rendered_evidence",
        return_value=rendered,
    ) as capture:
        with patch(
            "sophyane.browser_runtime_v2."
            "subprocess.run",
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ""
            run.return_value.stderr = ""

            opened, evidence = (
                browser_runtime_v2
                .open_verified_browser(
                    tmp_path,
                    lambda _message: None,
                )
            )

    assert opened is True

    assert (
        "HTTP verification:"
        in evidence
    )

    assert (
        "Rendered evidence: PASS"
        in evidence
    )

    assert (
        "termux-headless-shell-cdp"
        in evidence
    )

    capture.assert_called_once()

    assert (
        capture.call_args.args[0]
        .startswith(
            "http://127.0.0.1:"
        )
    )


def test_preview_server_is_detached_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sophyane import browser_runtime_v2

    target = (
        tmp_path
        / "index.html"
    )

    target.write_text(
        (
            "<!doctype html>"
            "<html>"
            "<head>"
            "<title>Persistent preview</title>"
            "</head>"
            "<body>"
            "<h1>Persistent preview</h1>"
            "</body>"
            "</html>"
        ),
        encoding="utf-8",
    )

    class FakeProcess:
        returncode = None
        pid = 12345

        def poll(self):
            return None

        def terminate(self):
            return None

    fake_process = FakeProcess()

    monkeypatch.setattr(
        browser_runtime_v2,
        "_free_preview_port",
        lambda: 45123,
    )

    monkeypatch.setattr(
        browser_runtime_v2,
        "_wait_for_server",
        lambda base, process: None,
    )

    browser_runtime_v2._SERVERS.clear()

    with patch(
        "sophyane.browser_runtime_v2."
        "subprocess.Popen",
        return_value=fake_process,
    ) as popen:
        base = (
            browser_runtime_v2
            ._server_for(
                tmp_path
            )
        )

    assert (
        base
        ==
        "http://127.0.0.1:45123"
    )

    popen.assert_called_once()

    kwargs = (
        popen.call_args.kwargs
    )

    assert (
        kwargs[
            "start_new_session"
        ]
        is True
    )

    command = (
        popen.call_args.args[0]
    )

    assert (
        command[1:3]
        ==
        [
            "-m",
            "http.server",
        ]
    )

    assert (
        "--directory"
        in command
    )

    assert (
        str(
            tmp_path.resolve()
        )
        in command
    )


def test_preview_server_reuses_live_detached_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sophyane import browser_runtime_v2

    class FakeProcess:
        returncode = None

        def poll(self):
            return None

    process = FakeProcess()

    root = (
        tmp_path.resolve()
    )

    base = (
        "http://127.0.0.1:"
        "45124"
    )

    browser_runtime_v2._SERVERS.clear()

    browser_runtime_v2._SERVERS[
        root
    ] = (
        process,
        base,
    )

    monkeypatch.setattr(
        browser_runtime_v2,
        "_server_ready",
        lambda candidate: (
            candidate == base
        ),
    )

    with patch(
        "sophyane.browser_runtime_v2."
        "subprocess.Popen",
    ) as popen:
        result = (
            browser_runtime_v2
            ._server_for(
                tmp_path
            )
        )

    assert result == base

    popen.assert_not_called()
