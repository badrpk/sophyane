"""Process-wide browser suppression for SLI candidate assembly."""
from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
import webbrowser
from typing import Any


class _BlockedProcess:
    """Minimal Popen-compatible result for intentionally blocked launches."""

    pid = 0
    returncode = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def communicate(self, input=None, timeout=None):
        return b"", b""

    def terminate(self):
        return None

    def kill(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _command_text(command: Any) -> str:
    if isinstance(command, (list, tuple)):
        return " ".join(str(part) for part in command).lower()

    return str(command or "").lower()


def _is_browser_launch(command: Any) -> bool:
    text = _command_text(command)

    launch_signatures = (
        "xdg-open",
        "sensible-browser",
        "gio open",
        "gnome-open",
        "kde-open",
        "firefox",
        "google-chrome",
        "chromium",
        "microsoft-edge",
        "start-process",
        "cmd.exe /c start",
        "cmd.exe /c  start",
        "powershell.exe",
        "explorer.exe http",
    )

    return any(signature in text for signature in launch_signatures)


@contextlib.contextmanager
def suppress_browser_launch():
    """Prevent browser windows while leaving compilers and HTTP servers usable."""
    previous_flag = os.environ.get("SOPHYANE_SLI_CANDIDATE_MODE")
    previous_disable = os.environ.get("SOPHYANE_DISABLE_BROWSER_OPEN")

    os.environ["SOPHYANE_SLI_CANDIDATE_MODE"] = "1"
    os.environ["SOPHYANE_DISABLE_BROWSER_OPEN"] = "1"

    original_open = webbrowser.open
    original_open_new = webbrowser.open_new
    original_open_new_tab = webbrowser.open_new_tab
    original_popen = subprocess.Popen
    original_run = subprocess.run
    original_call = subprocess.call
    original_check_call = subprocess.check_call
    original_check_output = subprocess.check_output

    def blocked_webbrowser(*_args, **_kwargs):
        return False

    def guarded_popen(command, *args, **kwargs):
        if _is_browser_launch(command):
            return _BlockedProcess()
        return original_popen(command, *args, **kwargs)

    def guarded_run(command, *args, **kwargs):
        if _is_browser_launch(command):
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=b"" if kwargs.get("text") is not True else "",
                stderr=b"" if kwargs.get("text") is not True else "",
            )
        return original_run(command, *args, **kwargs)

    def guarded_call(command, *args, **kwargs):
        if _is_browser_launch(command):
            return 0
        return original_call(command, *args, **kwargs)

    def guarded_check_call(command, *args, **kwargs):
        if _is_browser_launch(command):
            return 0
        return original_check_call(command, *args, **kwargs)

    def guarded_check_output(command, *args, **kwargs):
        if _is_browser_launch(command):
            return "" if kwargs.get("text") else b""
        return original_check_output(command, *args, **kwargs)

    webbrowser.open = blocked_webbrowser
    webbrowser.open_new = blocked_webbrowser
    webbrowser.open_new_tab = blocked_webbrowser
    subprocess.Popen = guarded_popen
    subprocess.run = guarded_run
    subprocess.call = guarded_call
    subprocess.check_call = guarded_check_call
    subprocess.check_output = guarded_check_output

    try:
        yield
    finally:
        webbrowser.open = original_open
        webbrowser.open_new = original_open_new
        webbrowser.open_new_tab = original_open_new_tab
        subprocess.Popen = original_popen
        subprocess.run = original_run
        subprocess.call = original_call
        subprocess.check_call = original_check_call
        subprocess.check_output = original_check_output

        if previous_flag is None:
            os.environ.pop("SOPHYANE_SLI_CANDIDATE_MODE", None)
        else:
            os.environ["SOPHYANE_SLI_CANDIDATE_MODE"] = previous_flag

        if previous_disable is None:
            os.environ.pop("SOPHYANE_DISABLE_BROWSER_OPEN", None)
        else:
            os.environ["SOPHYANE_DISABLE_BROWSER_OPEN"] = previous_disable


__all__ = ["suppress_browser_launch"]
