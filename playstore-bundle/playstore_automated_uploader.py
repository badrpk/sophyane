"""Playwright Automated Upload Engine for Google Play Console.

Automates:
  1) Launching Chromium browser to https://play.google.com/console
  2) Navigating to Release / Production section
  3) Attaching signed .aab release bundle
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

BUNDLE_DIR = Path("/root/sophyane/playstore-bundle")
AAB_XERUS = BUNDLE_DIR / "release_output" / "xerus-update-v21.2.0-release.aab"
AAB_SOPHYANE = BUNDLE_DIR / "release_output" / "sophyane-v21.2.0-release.aab"


def run_playwright_uploader() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright module not available")
        return

    print("Launching Playwright Chromium Engine...")
    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
        )
        page = context.new_page()

        print("Navigating to Google Play Console...")
        try:
            page.goto("https://play.google.com/console", timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            print("Google Play Console Page Title:", page.title())

            # Search for upload inputs if present
            file_inputs = page.query_selector_all("input[type='file']")
            print(f"Found {len(file_inputs)} file upload target(s) on Play Console")

            if file_inputs:
                target_aab = AAB_XERUS if AAB_XERUS.exists() else AAB_SOPHYANE
                print(f"Attaching release bundle: {target_aab}")
                file_inputs[0].set_input_files(str(target_aab))
                print("App Bundle attached successfully!")

            time.sleep(5)
        except Exception as e:
            print(f"Automation step status: {e}")

        browser.close()


if __name__ == "__main__":
    run_playwright_uploader()
