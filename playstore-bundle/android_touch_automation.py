"""Full Automated Touch & File Picker Selection Engine for Sophyane.

Automates:
  1) Bringing Chrome Google Play Console to front.
  2) Tapping Upload button.
  3) Auto-selecting xerus-update-v21.2.0-release.aab in Android File Picker.
  4) Confirming Save & Rollout.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


def run_cmd(cmd: str) -> str:
    res = subprocess.run(["su", "-c", cmd], text=True, capture_output=True)
    return res.stdout.strip()


def tap(x: int, y: int, delay: float = 1.5) -> None:
    print(f"Simulating Touch Tap at ({x}, {y})...")
    run_cmd(f"/system/bin/input tap {x} {y}")
    time.sleep(delay)


def keyevent(code: int, delay: float = 1.0) -> None:
    print(f"Simulating Key Event: {code}...")
    run_cmd(f"/system/bin/input keyevent {code}")
    time.sleep(delay)


def text(txt: str, delay: float = 1.0) -> None:
    print(f"Simulating Input Text: {txt}...")
    run_cmd(f"/system/bin/input text '{txt}'")
    time.sleep(delay)


def full_automated_release_sequence() -> None:
    print("1. Bringing Chrome Play Console to Foreground...")
    run_cmd("/data/data/com.termux/files/usr/bin/am start -a android.intent.action.VIEW -d 'https://play.google.com/console'")
    time.sleep(3.0)

    print("2. Tapping Upload Button...")
    tap(540, 1200)
    tap(540, 1600)

    print("3. Handling Android File Picker Dialog...")
    time.sleep(2.0)
    # Search for xerus bundle
    text("xerus")
    keyevent(20)  # Down Arrow
    keyevent(66)  # Enter / Confirm selection

    print("4. Confirming Release Save & Rollout...")
    time.sleep(3.0)
    tap(540, 1800)
    keyevent(66)  # Confirm

    print("Full Automated Play Console Touch & Selection Sequence Completed!")


if __name__ == "__main__":
    full_automated_release_sequence()
