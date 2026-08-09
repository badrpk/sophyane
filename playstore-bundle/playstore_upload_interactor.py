"""Playwright Google Play Console Uploader & CDP Inspector.

Attempts:
  1) Connect over CDP to local Android Chrome (http://127.0.0.1:9222) if active.
  2) Fallback to Playwright persistent browser context.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BUNDLE_DIR = Path("/root/sophyane/playstore-bundle")
AAB_XERUS = BUNDLE_DIR / "release_output" / "xerus-update-v21.2.0-release.aab"
AAB_SOPHYANE = BUNDLE_DIR / "release_output" / "sophyane-v21.2.0-release.aab"
PROFILE_DIR = Path.home() / ".config" / "sophyane" / "browser_profile"


def attempt_upload() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed")
        return

    with sync_playwright() as p:
        browser = None
        # Option A: Try connecting to Chrome Remote Debugging port 9222
        try:
            print("1. Probing Chrome CDP on port 9222...")
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=5000)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            print("Connected to active phone browser via CDP! Page Title:", page.title())
        except Exception as cdp_err:
            print(f"   CDP connection note: {cdp_err}")
            print("2. Falling back to Playwright Persistent Session Context...")
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
            )
            page = context.pages[0] if context.pages else context.new_page()

        print("Navigating / Inspecting Google Play Console...")
        try:
            page.goto("https://play.google.com/console", timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            print("Console Page Title:", page.title())

            # Look for any file input elements
            inputs = page.query_selector_all("input[type='file']")
            print(f"File Upload Inputs Found: {len(inputs)}")

            target_aab = AAB_XERUS if AAB_XERUS.exists() else AAB_SOPHYANE

            if inputs:
                print(f"Setting input files to {target_aab.name}...")
                inputs[0].set_input_files(str(target_aab))
                print("App Bundle attached successfully!")

            # Look for buttons like 'Create app' or 'Create release'
            buttons = page.query_selector_all("button, a[role='button']")
            btn_texts = [b.inner_text().strip() for b in buttons[:10] if b.inner_text().strip()]
            print("Detected Action Elements:", btn_texts)

        except Exception as err:
            print(f"Inspection Result: {err}")

        try:
            context.close()
        except Exception:
            pass


if __name__ == "__main__":
    attempt_upload()
