"""Completion / event notifications (desktop, log, webhook)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

LOG = Path.home() / ".local" / "state" / "sophyane" / "notifications.log"


def notify(title: str, body: str = "", *, level: str = "info") -> dict[str, Any]:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = {"ts": time.time(), "title": title, "body": body[:2000], "level": level}
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    channels: list[str] = ["log"]
    # Desktop notify-send
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", f"Sophyane: {title}", body[:200] or title],
                check=False,
                timeout=5,
                capture_output=True,
            )
            channels.append("notify-send")
        except Exception:  # noqa: BLE001
            pass
    # Optional webhook
    url = os.environ.get("SOPHYANE_NOTIFY_WEBHOOK", "").strip()
    if url:
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(line).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            channels.append("webhook")
        except Exception:  # noqa: BLE001
            channels.append("webhook_failed")
    return {"ok": True, "channels": channels, "event": line}


def recent(limit: int = 20) -> dict[str, Any]:
    if not LOG.exists():
        return {"ok": True, "events": []}
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"ok": True, "events": events}
