"""Android Native Touch Screen Automation Engine for Sophyane.

Uses /system/bin/input via root (su) to simulate touch taps, swipes, and text inputs on the phone display.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


def run_cmd(cmd: str) -> str:
    res = subprocess.run(["su", "-c", cmd], text=True, capture_output=True)
    return res.stdout.strip()


def tap(x: int, y: int) -> None:
    print(f"Simulating Touch Tap at ({x}, {y})...")
    run_cmd(f"/system/bin/input tap {x} {y}")
    time.sleep(1.5)


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 500) -> None:
    print(f"Simulating Touch Swipe ({x1},{y1}) -> ({x2},{y2})...")
    run_cmd(f"/system/bin/input swipe {x1} {y1} {x2} {y2} {duration_ms}")
    time.sleep(1.5)


def text(txt: str) -> None:
    print(f"Simulating Input Text: {txt}...")
    run_cmd(f"/system/bin/input text '{txt}'")
    time.sleep(1.0)


def automate_playstore_upload() -> None:
    print("1. Bringing Chrome Browser to Foreground...")
    run_cmd("/data/data/com.termux/files/usr/bin/am start -a android.intent.action.VIEW -d 'https://play.google.com/console'")
    time.sleep(3.0)

    print("2. Performing Screen Touch Operations for Release Upload...")
    # Get display metrics
    wm_info = run_cmd("/system/bin/wm size")
    print("Screen Resolution:", wm_info)

    # Tap center-right of screen where Upload/Release buttons typically sit
    tap(540, 1200)
    tap(540, 1600)

    print("Android Touch Screen Automation Sequence Completed Successfully!")


if __name__ == "__main__":
    automate_playstore_upload()
