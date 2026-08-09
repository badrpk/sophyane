"""Persistent Session Automated Google Play Console Uploader for Sophyane.

Uses Playwright launch_persistent_context to preserve session tokens and cookies.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROFILE_DIR = Path.home() / ".config" / "sophyane" / "browser_profile"
BUNDLE_DIR = Path("/root/sophyane/playstore-bundle")
AAB_XERUS = BUNDLE_DIR / "release_output" / "xerus-update-v21.2.0-release.aab"
AAB_SOPHYANE = BUNDLE_DIR / "release_output" / "sophyane-v21.2.0-release.aab"


def run_persistent_uploader() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed")
        return

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Starting Playwright with Persistent Profile: {PROFILE_DIR}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path="/usr/bin/chromium",
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        )

        page = context.pages[0] if context.pages else context.new_page()

        print("Navigating to Google Play Console Developer Hub...")
        try:
            page.goto("https://play.google.com/apps/publish", timeout=40000)
            page.wait_for_load_state("networkidle", timeout=15000)
            print("Current Page Title:", page.title())

            # Probe for file inputs or release creation buttons
            file_inputs = page.query_selector_all("input[type='file']")
            print(f"Detected File Upload Elements: {len(file_inputs)}")

            target_aab = AAB_XERUS if AAB_XERUS.exists() else AAB_SOPHYANE
            if file_inputs:
                print(f"Attaching App Bundle ({target_aab.name})...")
                file_inputs[0].set_input_files(str(target_aab))
                print("App Bundle Attached Successfully!")
            else:
                print(f"Play Console Session Ready. Bundle Prepared: {target_aab.name}")

            time.sleep(3)
        except Exception as e:
            print(f"Session Step Status: {e}")

        context.close()


if __name__ == "__main__":
    run_persistent_uploader()
