"""Compact live-web grounding for Sophyane local chat.

This layer intentionally reuses :mod:`sophyane.web_intel` rather than adding a
second browser/search stack. It handles two high-value local-chat cases:

* explicit public URLs in the user's request; and
* follow-ups that refer to the most recently fetched/scraped page.

Generic search remains a secondary fallback because some restricted/offline
hosts may not return search results even when direct URL fetch works.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sophyane.web_intel import SCRAPE_DIR, fetch_url, format_search_context, needs_web_research, web_search

_URL_RE = re.compile(r"https?://[^\s<>\]\[(){}\"']+", re.IGNORECASE)
_BARE_DOMAIN_RE = re.compile(
    r"(?<![@\w])(?:www\.)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z]{2,})+(?:/[^\s<>]*)?",
    re.IGNORECASE,
)
_RECENT_FETCH_PHRASES = (
    "page i just fetched",
    "page i fetched",
    "just fetched",
    "last fetched page",
    "recently fetched page",
    "previously fetched page",
    "the fetched page",
    "that page i fetched",
)


def extract_public_url(message: str) -> str:
    """Return one explicit HTTP(S) URL or bare public domain from a message."""
    text = str(message or "")
    match = _URL_RE.search(text)
    if match:
        return match.group(0).rstrip(".,;:!?\")'")
    match = _BARE_DOMAIN_RE.search(text)
    if not match:
        return ""
    value = match.group(0).rstrip(".,;:!?\")'")
    return value if value.lower().startswith(("http://", "https://")) else f"https://{value}"


def refers_to_recent_fetch(message: str) -> bool:
    text = str(message or "").strip().lower()
    return any(phrase in text for phrase in _RECENT_FETCH_PHRASES)


def latest_scrape(*, scrape_dir: Path = SCRAPE_DIR) -> dict[str, Any] | None:
    """Load the newest persisted successful scrape, if available."""
    if not scrape_dir.exists():
        return None
    paths = sorted(scrape_dir.glob("*.json"), reverse=True)
    for path in paths[:50]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not data.get("ok"):
            continue
        text = str(data.get("text") or "").strip()
        if not text:
            continue
        return data
    return None


def _format_page(data: dict[str, Any], *, max_chars: int) -> str:
    title = str(data.get("title") or "Fetched page").strip()
    url = str(data.get("url") or "").strip()
    text = str(data.get("text") or "").strip()
    header = (
        "LIVE WEB PAGE EVIDENCE (treat as current fetched evidence; do not claim "
        "you cannot access it):\n"
        f"Title: {title}\n"
        f"URL: {url}\n\n"
    )
    budget = max(0, max_chars - len(header))
    return header + text[:budget]


def build_web_grounding(message: str, *, max_chars: int = 3500) -> str:
    """Return bounded web evidence for a chat request, or an empty string.

    Direct URL fetch and recent-scrape retrieval are preferred because they are
    deterministic and preserve provenance. Generic search is attempted only for
    messages that explicitly need live research and lack a direct URL.
    """
    query = str(message or "").strip()
    if not query:
        return ""

    url = extract_public_url(query)
    if url:
        result = fetch_url(url)
        if result.ok and result.text:
            return _format_page(result.to_dict(), max_chars=max_chars)
        return ""

    if refers_to_recent_fetch(query):
        data = latest_scrape()
        if data:
            return _format_page(data, max_chars=max_chars)

    if needs_web_research(query):
        search = web_search(query, limit=5)
        return format_search_context(search, max_chars=max_chars)

    return ""
