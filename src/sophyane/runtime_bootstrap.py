"""Device-aware startup normalization for plug-and-play Sophyane installs."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from sophyane.config import (
    DEFAULT_MODEL,
    get_secret,
    load_config,
    save_config,
    save_secret,
)


def _memory_mb() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size / (1024 * 1024))
    except (AttributeError, OSError, ValueError):
        return None


def detect_device() -> dict[str, Any]:
    prefix = os.getenv("PREFIX", "")
    termux = "com.termux" in prefix or Path("/data/data/com.termux").exists()
    memory_mb = _memory_mb()
    return {
        "termux": termux,
        "android": bool(os.getenv("ANDROID_ROOT")) or termux,
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
        "memory_mb": memory_mb,
        "git": bool(shutil.which("git")),
        "curl": bool(shutil.which("curl")),
        "python": sys.executable,
    }


def bootstrap_runtime() -> dict[str, Any]:
    """Normalize stale configuration and persist environment credentials.

    This function is deliberately dependency-free and safe to run at every CLI
    startup. It never overwrites a valid explicit model except known stale model
    aliases that are not available through the public Gemini API.
    """
    device = detect_device()
    config = load_config()
    changed = False

    provider = str(config.get("provider") or "gemini").strip().lower()
    model = str(config.get("model") or DEFAULT_MODEL).strip()

    if provider == "gemini" and model in {
        "gemini-3.5-flash",
        "gemini-3.5-flash-latest",
    }:
        config["model"] = DEFAULT_MODEL
        changed = True

    memory_mb = device.get("memory_mb")
    if device["termux"]:
        # Conservative defaults prevent Android process kills and long apparent
        # hangs, while preserving explicit smaller user settings.
        if int(config.get("timeout", 60) or 60) > 120:
            config["timeout"] = 120
            changed = True
        recommended_tokens = 2048 if memory_mb and memory_mb < 6144 else 4096
        if int(config.get("max_tokens", 4096) or 4096) > recommended_tokens:
            config["max_tokens"] = recommended_tokens
            changed = True
        config["runtime_profile"] = "termux"
    else:
        config.setdefault("runtime_profile", "desktop")

    # A key exported during setup should keep working in future shells without
    # requiring users to understand Python environments.
    if provider == "gemini" and not get_secret("gemini", "GEMINI_API_KEY"):
        env_key = (
            os.getenv("GEMINI_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        )
        if env_key:
            save_secret("gemini", env_key)

    if changed:
        save_config(config)

    return {"device": device, "config": config}


def provider_readiness(config: dict[str, Any]) -> tuple[bool, str]:
    provider = str(config.get("provider") or "gemini").strip().lower()
    if provider == "gemini":
        if get_secret("gemini", "GEMINI_API_KEY"):
            return True, ""
        return False, (
            "Gemini is selected but no API key is configured. "
            "Run `sophyane --setup` once; Sophyane will store it privately "
            "and reuse it on this device."
        )
    return True, ""
