"""Voice / media helpers: YouTube resolve for hands-free play commands."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from sophyane.version import __version__
from sophyane.web_intel import USER_AGENT, web_search

INVIDIOUS_MIRRORS = (
    "https://yewtu.be",
    "https://invidious.fdn.fr",
    "https://vid.puffyan.us",
    "https://inv.nadeko.net",
)


def _http_json(url: str, *, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_text(url: str, *, timeout: float = 12.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(800_000).decode("utf-8", errors="replace")


def youtube_search(query: str, *, limit: int = 5) -> dict[str, Any]:
    """Find YouTube videos for a voice 'play …' command (no API key)."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "empty query", "results": []}

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    # 1) Invidious public API mirrors
    for base in INVIDIOUS_MIRRORS:
        try:
            url = f"{base}/api/v1/search?" + urllib.parse.urlencode(
                {"q": q, "type": "video"}
            )
            data = _http_json(url, timeout=8.0)
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") and item.get("type") != "video":
                        continue
                    vid = str(item.get("videoId") or "").strip()
                    if not vid:
                        continue
                    results.append(
                        {
                            "video_id": vid,
                            "title": str(item.get("title") or q),
                            "author": str(item.get("author") or ""),
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "embed_url": f"https://www.youtube.com/embed/{vid}?autoplay=1",
                            "source": "invidious",
                        }
                    )
                    if len(results) >= limit:
                        break
            if results:
                break
        except Exception as error:  # noqa: BLE001
            errors.append(f"{base}: {error}")

    # 2) DuckDuckGo / web search for youtube links
    if not results:
        try:
            search = web_search(f"{q} site:youtube.com", limit=6)
            for hit in search.get("results") or []:
                url = str(hit.get("url") or "")
                m = re.search(r"(?:v=|/shorts/)([A-Za-z0-9_-]{6,})", url)
                if not m and "youtu.be/" in url:
                    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{6,})", url)
                if not m:
                    continue
                vid = m.group(1)
                results.append(
                    {
                        "video_id": vid,
                        "title": str(hit.get("title") or q),
                        "author": "",
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "embed_url": f"https://www.youtube.com/embed/{vid}?autoplay=1",
                        "source": hit.get("source") or "web",
                    }
                )
                if len(results) >= limit:
                    break
        except Exception as error:  # noqa: BLE001
            errors.append(f"web_search: {error}")

    # 3) Always provide a search page fallback for the client to open
    search_page = "https://www.youtube.com/results?" + urllib.parse.urlencode(
        {"search_query": q}
    )
    top = results[0] if results else None
    return {
        "ok": bool(results) or True,
        "query": q,
        "results": results[:limit],
        "play": top,
        "search_page": search_page,
        "errors": errors,
        "version": __version__,
        "note": (
            "Open play.url or embed_url to start media. "
            "If no video id resolved, open search_page."
        ),
    }


def parse_voice_media_intent(text: str) -> dict[str, Any] | None:
    """Detect play/search media intents from transcribed speech."""
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower().strip()
    # strip polite prefixes
    for p in ("hey sophyane ", "sophyane ", "ok sophyane ", "please "):
        if low.startswith(p):
            low = low[len(p) :].strip()
            raw = raw[len(p) :].strip() if len(raw) > len(p) else raw

    play_patterns = (
        r"^(?:play|put on|listen to|watch)\s+(.+?)(?:\s+on\s+youtube)?$",
        r"^(?:youtube|yt)\s+(?:play\s+)?(.+)$",
        r"^play\s+(?:the\s+)?(?:song|music|video|track)\s+(.+)$",
        r"^put\s+on\s+(?:some\s+)?(.+)$",
    )
    for pat in play_patterns:
        m = re.match(pat, low, flags=re.I)
        if m:
            q = m.group(1).strip(" .?!")
            if q and q not in {"music", "something", "a song"}:
                return {"intent": "youtube_play", "query": q, "raw": raw}

    search_patterns = (
        r"^(?:search(?:\s+for)?|look\s+up|find|google|web\s+search)\s+(.+)$",
        r"^(?:what is|who is|who was|tell me about)\s+(.+)$",
    )
    for pat in search_patterns:
        m = re.match(pat, low, flags=re.I)
        if m:
            return {"intent": "web_search", "query": m.group(1).strip(" .?!"), "raw": raw}

    return None
