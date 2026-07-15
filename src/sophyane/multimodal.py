"""Multimodal hooks: image describe + voice status (provider/binary optional)."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Any

from sophyane.version import __version__


def voice_status() -> dict[str, Any]:
    return {
        "ok": True,
        "stt": {
            "available": bool(shutil.which("whisper") or shutil.which("whisper.cpp") or shutil.which("vosk")),
            "bins": [b for b in ("whisper", "whisper.cpp", "vosk", "ffmpeg") if shutil.which(b)],
        },
        "tts": {
            "available": bool(shutil.which("espeak") or shutil.which("espeak-ng") or shutil.which("say")),
            "bins": [b for b in ("espeak", "espeak-ng", "say", "ffmpeg") if shutil.which(b)],
        },
        "realtime_duplex": "partial",
        "note": "Install whisper/espeak (or cloud STT/TTS) for full voice; hooks are ready.",
        "version": __version__,
    }


def describe_image(path: str, *, prompt: str = "Describe this image for an agent.") -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"ok": False, "error": f"missing image: {path}"}
    if p.stat().st_size > 8_000_000:
        return {"ok": False, "error": "image too large (8MB max)"}
    raw = p.read_bytes()
    b64 = base64.b64encode(raw[:50_000]).decode("ascii")  # header sample for non-vision fallback
    # Try vision-capable provider generate if configured
    try:
        from sophyane.config import load_config
        from sophyane.main import create_provider

        provider = create_provider(load_config())
        text = provider.generate(
            f"{prompt}\nImage path: {p}\nSize bytes: {p.stat().st_size}\n"
            f"Base64 prefix (not full pixels for non-vision models): {b64[:200]}...\n"
            "If you cannot see pixels, describe likely contents from filename and context.",
            "You assist with multimodal understanding for Sophyane agents.",
        )
        return {"ok": True, "path": str(p), "description": text, "mode": "provider_text"}
    except Exception as error:  # noqa: BLE001
        return {
            "ok": True,
            "path": str(p),
            "description": f"Image at {p.name} ({p.stat().st_size} bytes). Vision model unavailable: {error}",
            "mode": "metadata_fallback",
        }


def speak(text: str) -> dict[str, Any]:
    text = (text or "").strip()[:500]
    if not text:
        return {"ok": False, "error": "empty text"}
    for bin_name in ("espeak-ng", "espeak", "say"):
        if shutil.which(bin_name):
            import subprocess

            try:
                subprocess.run([bin_name, text], check=False, timeout=30, capture_output=True)
                return {"ok": True, "engine": bin_name, "chars": len(text)}
            except Exception as error:  # noqa: BLE001
                return {"ok": False, "error": str(error)}
    return {"ok": False, "error": "no TTS binary (espeak/say); text logged only", "text": text}
