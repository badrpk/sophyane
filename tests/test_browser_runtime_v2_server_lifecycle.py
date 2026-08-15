from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sophyane import browser_runtime_v2


class FakeProcess:
    def __init__(
        self,
        *,
        running: bool = True,
    ) -> None:
        self.returncode = (
            None
            if running
            else 0
        )
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = 0

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9

    def wait(
        self,
        timeout=None,
    ):
        self.wait_calls += 1
        return self.returncode


@pytest.fixture(autouse=True)
def clean_server_registry():
    browser_runtime_v2._SERVERS.clear()

    yield

    # Tests use fake processes, but ensure registry ownership
    # never escapes one test into another.
    browser_runtime_v2.stop_all_preview_servers()
    browser_runtime_v2._SERVERS.clear()


def _artifact(
    tmp_path: Path,
) -> Path:
    target = (
        tmp_path
        / "index.html"
    )

    target.write_text(
        (
            "<!doctype html>"
            "<html>"
            "<head>"
            "<title>Lifecycle test</title>"
            "</head>"
            "<body>"
            "<main>"
            "<h1>Lifecycle test</h1>"
            "<p>"
            "This preview fixture is intentionally larger "
            "than the verified browser minimum size."
            "</p>"
            "</main>"
            "</body>"
            "</html>"
        ),
        encoding="utf-8",
    )

    return target


@pytest.mark.parametrize(
    (
        "name",
        "value",
    ),
    (
        (
            "SOPHYANE_DISABLE_BROWSER_OPEN",
            "1",
        ),
        (
            "SOPHYANE_NO_AUTO_OPEN",
            "1",
        ),
        (
            "SOPHYANE_NO_BROWSER",
            "1",
        ),
        (
            "SOPHYANE_BROWSER_PREVIEW",
            "0",
        ),
    ),
)
def test_browser_suppression_prevents_server_spawn(
    tmp_path: Path,
    monkeypatch,
    name: str,
    value: str,
) -> None:
    _artifact(
        tmp_path
    )

    for variable in (
        "SOPHYANE_DISABLE_BROWSER_OPEN",
        "SOPHYANE_NO_AUTO_OPEN",
        "SOPHYANE_NO_BROWSER",
        "SOPHYANE_BROWSER_PREVIEW",
    ):
        monkeypatch.delenv(
            variable,
            raising=False,
        )

    monkeypatch.setenv(
        name,
        value,
    )

    with patch(
        "sophyane.browser_runtime_v2."
        "subprocess.Popen",
    ) as popen:
        opened, detail = (
            browser_runtime_v2
            .open_verified_browser(
                tmp_path,
                lambda _message: None,
            )
        )

    assert opened is False

    assert (
        "suppressed"
        in detail.lower()
    )

    popen.assert_not_called()

    assert (
        browser_runtime_v2._SERVERS
        == {}
    )


def test_stop_preview_server_terminates_owned_process(
    tmp_path: Path,
) -> None:
    root = (
        tmp_path.resolve()
    )

    process = FakeProcess()

    browser_runtime_v2._SERVERS[
        root
    ] = (
        process,
        "http://127.0.0.1:45123",
    )

    stopped = (
        browser_runtime_v2
        .stop_preview_server(
            tmp_path
        )
    )

    assert stopped is True

    assert (
        process.terminate_calls
        == 1
    )

    assert (
        process.wait_calls
        == 1
    )

    assert (
        process.kill_calls
        == 0
    )

    assert (
        root
        not in browser_runtime_v2._SERVERS
    )


def test_stop_preview_server_is_exact_workspace_only(
    tmp_path: Path,
) -> None:
    first = (
        tmp_path
        / "first"
    )

    second = (
        tmp_path
        / "second"
    )

    first.mkdir()
    second.mkdir()

    first_process = FakeProcess()
    second_process = FakeProcess()

    browser_runtime_v2._SERVERS[
        first.resolve()
    ] = (
        first_process,
        "http://127.0.0.1:45124",
    )

    browser_runtime_v2._SERVERS[
        second.resolve()
    ] = (
        second_process,
        "http://127.0.0.1:45125",
    )

    assert (
        browser_runtime_v2
        .stop_preview_server(
            first
        )
        is True
    )

    assert (
        first_process.terminate_calls
        == 1
    )

    assert (
        second_process.terminate_calls
        == 0
    )

    assert (
        second.resolve()
        in browser_runtime_v2._SERVERS
    )


def test_stale_preview_is_terminated_before_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = (
        tmp_path.resolve()
    )

    stale = FakeProcess()

    browser_runtime_v2._SERVERS[
        root
    ] = (
        stale,
        "http://127.0.0.1:45126",
    )

    replacement = FakeProcess()

    monkeypatch.setattr(
        browser_runtime_v2,
        "_server_ready",
        lambda _base: False,
    )

    monkeypatch.setattr(
        browser_runtime_v2,
        "_free_preview_port",
        lambda: 45127,
    )

    monkeypatch.setattr(
        browser_runtime_v2,
        "_wait_for_server",
        lambda base, process: None,
    )

    with patch(
        "sophyane.browser_runtime_v2."
        "subprocess.Popen",
        return_value=replacement,
    ) as popen:
        base = (
            browser_runtime_v2
            ._server_for(
                tmp_path
            )
        )

    assert (
        stale.terminate_calls
        == 1
    )

    assert (
        stale.wait_calls
        == 1
    )

    assert (
        base
        == "http://127.0.0.1:45127"
    )

    popen.assert_called_once()

    assert (
        browser_runtime_v2._SERVERS[
            root
        ][0]
        is replacement
    )


def test_failed_preview_start_is_terminated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    process = FakeProcess()

    monkeypatch.setattr(
        browser_runtime_v2,
        "_free_preview_port",
        lambda: 45128,
    )

    def fail_wait(
        base,
        candidate,
    ):
        raise RuntimeError(
            "simulated server startup failure"
        )

    monkeypatch.setattr(
        browser_runtime_v2,
        "_wait_for_server",
        fail_wait,
    )

    with patch(
        "sophyane.browser_runtime_v2."
        "subprocess.Popen",
        return_value=process,
    ):
        with pytest.raises(
            RuntimeError,
            match=(
                "simulated server "
                "startup failure"
            ),
        ):
            browser_runtime_v2._server_for(
                tmp_path
            )

    assert (
        process.terminate_calls
        == 1
    )

    assert (
        process.wait_calls
        == 1
    )

    assert (
        browser_runtime_v2._SERVERS
        == {}
    )


def test_stop_process_escalates_after_timeout(
    monkeypatch,
) -> None:
    class SlowProcess:
        returncode = None

        def __init__(self):
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = 0

        def poll(self):
            return None

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1
            self.returncode = -9

        def wait(
            self,
            timeout=None,
        ):
            self.wait_calls += 1

            if self.kill_calls == 0:
                raise subprocess.TimeoutExpired(
                    cmd="http.server",
                    timeout=timeout,
                )

            return self.returncode

    process = SlowProcess()

    browser_runtime_v2._stop_process(
        process,
        timeout=0.01,
    )

    assert (
        process.terminate_calls
        == 1
    )

    assert (
        process.kill_calls
        == 1
    )

    assert (
        process.wait_calls
        == 2
    )
