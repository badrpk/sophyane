from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.browser.launcher as launcher


def test_nifdu_launcher_uses_dedicated_profile_and_cdp(
    monkeypatch,
    tmp_path: Path,
) -> None:
    profile = (
        tmp_path
        / "nifdu-profile"
    )

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        profile,
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium-browser",
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    # SOPHYANE_TEST_NIFDU_CDP_READINESS_MOCK_V1
    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda process, host, port: (
            True,
            "",
        ),
    )

    monkeypatch.setenv(
        "SOPHYANE_CDP_HOST",
        "127.0.0.1",
    )

    monkeypatch.setenv(
        "SOPHYANE_CDP_PORT",
        "9222",
    )

    captured = {}

    def fake_popen(
        argv,
        **kwargs,
    ):
        captured["argv"] = list(
            argv
        )
        captured["kwargs"] = kwargs

        return SimpleNamespace(
            pid=43210
        )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    result = (
        launcher.launch_nifdu_browser()
    )

    argv = captured["argv"]

    assert result["ok"] is True
    assert result["launched"] is True
    assert result["reused"] is False
    assert result["pid"] == 43210

    assert argv[0] == (
        "/test/chromium-browser"
    )

    assert (
        f"--user-data-dir={profile}"
        in argv
    )

    assert (
        "--remote-debugging-address=127.0.0.1"
        in argv
    )

    assert (
        "--remote-debugging-port=9222"
        in argv
    )

    assert (
        "https://chatgpt.com/"
        in argv
    )

    assert (
        captured["kwargs"][
            "start_new_session"
        ]
        is True
    )


def test_nifdu_launcher_reuses_live_cdp_without_spawn(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: True,
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium-browser",
    )

    def forbidden_popen(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Popen must not run when CDP is already live"
        )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        forbidden_popen,
    )

    result = (
        launcher.launch_nifdu_browser()
    )

    assert result["ok"] is True
    assert result["reused"] is True
    assert result["launched"] is False
    assert result["pid"] is None


def test_nifdu_launcher_missing_chromium_fails_without_spawn(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: None,
    )

    def forbidden_popen(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Popen must not run without Chromium"
        )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        forbidden_popen,
    )

    result = (
        launcher.launch_nifdu_browser()
    )

    assert result["ok"] is False
    assert result["launched"] is False
    assert result["chromium"] is None


def test_nifdu_cdp_port_environment_contract(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_CDP_HOST",
        "127.0.0.1",
    )

    monkeypatch.setenv(
        "SOPHYANE_CDP_PORT",
        "9333",
    )

    assert (
        launcher._nifdu_cdp_endpoint()
        == (
            "127.0.0.1",
            9333,
        )
    )


def test_invalid_nifdu_cdp_port_fails_closed(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_CDP_PORT",
        "invalid",
    )

    try:
        launcher._nifdu_cdp_endpoint()
    except ValueError:
        pass
    else:
        raise AssertionError(
            "invalid CDP port must fail closed"
        )


def test_nifdu_launcher_has_tracked_authority_marker() -> None:
    source = Path(
        "src/sophyane/browser/launcher.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_NIFDU_TRACKED_BROWSER_LAUNCH_AUTHORITY_V1"
        in source
    )

    assert (
        "launch_nifdu_browser"
        in source
    )

    assert (
        "--remote-debugging-port="
        in source
    )

    assert (
        "nifdu-browser-profile"
        in source
    )


def test_wait_for_nifdu_cdp_accepts_ready_endpoint(
    monkeypatch,
) -> None:
    process = SimpleNamespace(
        poll=lambda: None,
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: True,
    )

    ready, error = (
        launcher._wait_for_nifdu_cdp(
            process,
            "127.0.0.1",
            9222,
            timeout=0.1,
            interval=0.01,
        )
    )

    assert ready is True
    assert error == ""


def test_wait_for_nifdu_cdp_fails_if_chromium_exits(
    monkeypatch,
) -> None:
    process = SimpleNamespace(
        poll=lambda: 7,
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    ready, error = (
        launcher._wait_for_nifdu_cdp(
            process,
            "127.0.0.1",
            9222,
            timeout=0.1,
            interval=0.01,
        )
    )

    assert ready is False

    assert (
        "exited before CDP became ready"
        in error
    )

    assert "status 7" in error


def test_wait_for_nifdu_cdp_times_out_fail_closed(
    monkeypatch,
) -> None:
    process = SimpleNamespace(
        poll=lambda: None,
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    ready, error = (
        launcher._wait_for_nifdu_cdp(
            process,
            "127.0.0.1",
            9222,
            timeout=0.03,
            interval=0.01,
        )
    )

    assert ready is False

    assert (
        "did not become ready"
        in error
    )

    assert "127.0.0.1:9222" in error


def test_spawned_browser_failure_is_returned_when_cdp_never_ready(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium",
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    process = SimpleNamespace(
        pid=54321,
        poll=lambda: None,
    )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda process, host, port: (
            False,
            "synthetic CDP timeout",
        ),
    )

    result = (
        launcher.launch_nifdu_browser()
    )

    assert result["ok"] is False
    assert result["launched"] is True
    assert result["pid"] == 54321

    assert (
        result["error"]
        == "synthetic CDP timeout"
    )


def test_wait_for_nifdu_cdp_accepts_ready_endpoint(
    monkeypatch,
) -> None:
    process = SimpleNamespace(
        poll=lambda: None,
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: True,
    )

    ready, error = (
        launcher._wait_for_nifdu_cdp(
            process,
            "127.0.0.1",
            9222,
            timeout=0.1,
            interval=0.01,
        )
    )

    assert ready is True
    assert error == ""


def test_wait_for_nifdu_cdp_fails_if_chromium_exits(
    monkeypatch,
) -> None:
    process = SimpleNamespace(
        poll=lambda: 7,
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    ready, error = (
        launcher._wait_for_nifdu_cdp(
            process,
            "127.0.0.1",
            9222,
            timeout=0.1,
            interval=0.01,
        )
    )

    assert ready is False

    assert (
        "exited before CDP became ready"
        in error
    )

    assert "status 7" in error


def test_wait_for_nifdu_cdp_times_out_fail_closed(
    monkeypatch,
) -> None:
    process = SimpleNamespace(
        poll=lambda: None,
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    ready, error = (
        launcher._wait_for_nifdu_cdp(
            process,
            "127.0.0.1",
            9222,
            timeout=0.03,
            interval=0.01,
        )
    )

    assert ready is False

    assert (
        "did not become ready"
        in error
    )

    assert "127.0.0.1:9222" in error


def test_spawned_browser_failure_is_returned_when_cdp_never_ready(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium",
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    process = SimpleNamespace(
        pid=54321,
        poll=lambda: None,
    )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda process, host, port: (
            False,
            "synthetic CDP timeout",
        ),
    )

    result = (
        launcher.launch_nifdu_browser()
    )

    assert result["ok"] is False
    assert result["launched"] is True
    assert result["pid"] == 54321

    assert (
        result["error"]
        == "synthetic CDP timeout"
    )


def test_nifdu_launcher_auto_headless_without_display(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(
        "DISPLAY",
        raising=False,
    )

    monkeypatch.delenv(
        "WAYLAND_DISPLAY",
        raising=False,
    )

    # Isolate this headless test from a real Termux:X11 socket in
    # the parent process environment.
    monkeypatch.setenv(
        "TMPDIR",
        str(tmp_path),
    )

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium",
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda process, host, port: (
            True,
            "",
        ),
    )

    captured = {}

    def fake_popen(
        argv,
        **kwargs,
    ):
        captured["argv"] = list(
            argv
        )

        return SimpleNamespace(
            pid=11111,
            poll=lambda: None,
        )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    result = (
        launcher.launch_nifdu_browser()
    )

    argv = captured["argv"]

    assert "--headless=new" in argv
    assert "--disable-gpu" in argv
    assert "--new-window" not in argv
    assert result["headless"] is True


def test_nifdu_launcher_preserves_gui_mode_with_display(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "DISPLAY",
        ":1",
    )

    monkeypatch.delenv(
        "WAYLAND_DISPLAY",
        raising=False,
    )

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium",
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda process, host, port: (
            True,
            "",
        ),
    )

    captured = {}

    def fake_popen(
        argv,
        **kwargs,
    ):
        captured["argv"] = list(
            argv
        )

        return SimpleNamespace(
            pid=22222,
            poll=lambda: None,
        )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    result = (
        launcher.launch_nifdu_browser()
    )

    argv = captured["argv"]

    assert "--new-window" in argv
    assert "--headless=new" not in argv
    assert "--disable-gpu" not in argv
    assert result["headless"] is False


def test_nifdu_launcher_allows_only_configured_cdp_origin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(
        "DISPLAY",
        raising=False,
    )

    monkeypatch.delenv(
        "WAYLAND_DISPLAY",
        raising=False,
    )

    monkeypatch.setenv(
        "SOPHYANE_CDP_HOST",
        "127.0.0.1",
    )

    monkeypatch.setenv(
        "SOPHYANE_CDP_PORT",
        "9333",
    )

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium",
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda process, host, port: (
            True,
            "",
        ),
    )

    captured = {}

    def fake_popen(
        argv,
        **kwargs,
    ):
        captured["argv"] = list(
            argv
        )

        return SimpleNamespace(
            pid=33333,
            poll=lambda: None,
        )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    launcher.launch_nifdu_browser()

    argv = captured["argv"]

    assert (
        "--remote-allow-origins=http://127.0.0.1:9333"
        in argv
    )

    assert (
        "--remote-allow-origins=*"
        not in argv
    )


def test_termux_exec_environment_uses_single_process_containment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(
        "DISPLAY",
        raising=False,
    )

    monkeypatch.delenv(
        "WAYLAND_DISPLAY",
        raising=False,
    )

    # Isolate this headless test from a real Termux:X11 socket in
    # the parent process environment.
    monkeypatch.setenv(
        "TMPDIR",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "PREFIX",
        "/data/data/com.termux/files/usr",
    )

    monkeypatch.setenv(
        "LD_PRELOAD",
        (
            "/data/data/com.termux/files/usr/lib/"
            "libtermux-exec.so"
        ),
    )

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium",
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda process, host, port: (
            True,
            "",
        ),
    )

    captured = {}

    def fake_popen(
        argv,
        **kwargs,
    ):
        captured["argv"] = list(argv)

        return SimpleNamespace(
            pid=44444,
            poll=lambda: None,
        )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    launcher.launch_nifdu_browser()

    argv = captured["argv"]

    assert "--headless=new" in argv
    assert "--single-process" not in argv
    assert "--enable-features=NetworkServiceInProcess2" in argv
    assert "--no-zygote" not in argv
    assert "--no-sandbox" in argv


def test_non_termux_environment_does_not_force_single_process(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "PREFIX",
        "/usr",
    )

    monkeypatch.delenv(
        "LD_PRELOAD",
        raising=False,
    )

    monkeypatch.setenv(
        "DISPLAY",
        ":1",
    )

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )

    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/test/chromium",
    )

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda host, port: False,
    )

    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda process, host, port: (
            True,
            "",
        ),
    )

    captured = {}

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda argv, **kwargs: (
            captured.setdefault(
                "argv",
                list(argv),
            )
            or SimpleNamespace(
                pid=55555,
                poll=lambda: None,
            )
        ),
    )

    # Avoid the lambda return-shape ambiguity.
    def fake_popen(
        argv,
        **kwargs,
    ):
        captured["argv"] = list(argv)

        return SimpleNamespace(
            pid=55555,
            poll=lambda: None,
        )

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    launcher.launch_nifdu_browser()

    argv = captured["argv"]

    assert "--single-process" not in argv
    assert "--no-zygote" not in argv

# SOPHYANE_NIFDU_TERMUX_X11_SOCKET_AUTHORITY_TESTS_V1
def test_termux_live_x0_socket_prefers_visible_chromium_when_display_unset(
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv(
        "PREFIX",
        "/data/data/com.termux/files/usr",
    )
    monkeypatch.setenv(
        "LD_PRELOAD",
        (
            "/data/data/com.termux/files/usr/lib/"
            "libtermux-exec.so"
        ),
    )
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    x11_dir = tmp_path / ".X11-unix"
    x11_dir.mkdir()
    (x11_dir / "X0").touch()

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )
    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/usr/bin/chromium",
    )

    captured = {}

    class Process:
        pid = 4242

    def fake_popen(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    result = launcher.launch_nifdu_browser(
        open_chatgpt=False,
    )

    argv = captured["argv"]
    child_env = captured["kwargs"].get("env")

    assert result["ok"] is True
    assert result["launched"] is True
    assert result["reused"] is False
    assert result["headless"] is False

    assert "--headless=new" not in argv
    assert "--disable-gpu" not in argv
    assert "--new-window" in argv

    assert (
        "--enable-features=NetworkServiceInProcess2"
        in argv
    )
    assert "--no-sandbox" in argv

    assert child_env is not None
    assert child_env["DISPLAY"] == ":0"

    # Parent environment must remain untouched.
    assert "DISPLAY" not in launcher.os.environ


def test_termux_x11_executable_without_live_x0_socket_stays_headless(
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv(
        "PREFIX",
        "/data/data/com.termux/files/usr",
    )
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    termux_x11 = bin_dir / "termux-x11"
    termux_x11.write_text("#!/bin/sh\n", encoding="utf-8")
    termux_x11.chmod(0o700)

    monkeypatch.setenv(
        "PATH",
        str(bin_dir)
        + launcher.os.pathsep
        + launcher.os.environ.get("PATH", ""),
    )

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )
    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: "/usr/bin/chromium",
    )

    captured = {}

    class Process:
        pid = 4243

    def fake_popen(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    result = launcher.launch_nifdu_browser(
        open_chatgpt=False,
    )

    argv = captured["argv"]

    assert result["ok"] is True
    assert result["headless"] is True
    assert "--headless=new" in argv
    assert "--disable-gpu" in argv

    # Presence of the executable alone is not display authority.
    assert "--new-window" not in argv
    assert "env" not in captured["kwargs"]

