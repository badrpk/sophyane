"""Internet fetch + safe HTML scraping for Sophyane self-improvement and agents."""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
SCRAPE_DIR = STATE_DIR / "web_scrape"
USER_AGENT = f"SophyaneWebIntel/{__version__} (+https://github.com/badrpk/sophyane)"

# Basic safety: block obvious credential/metadata hosts by default.
BLOCKED_HOST_SUFFIXES = (
    "metadata.google.internal",
    "169.254.169.254",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
)


@dataclass
class ScrapeResult:
    ok: bool
    url: str
    title: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)
    status: int = 0
    error: str = ""
    fetched_at: float = field(default_factory=time.time)
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._links: list[str] = []
        self._title_parts: list[str] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._links.append(href)
        if tag in {"p", "br", "li", "h1", "h2", "h3", "tr", "div"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self._title_parts.append(text)
        else:
            self._chunks.append(text + " ")

    def result(self) -> tuple[str, str, list[str]]:
        title = " ".join(self._title_parts).strip()
        body = re.sub(r"[ \t]+", " ", "".join(self._chunks))
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        # de-dupe links preserve order
        links: list[str] = []
        for link in self._links:
            if link not in links:
                links.append(link)
        return title, body, links


def _host_allowed(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    for blocked in BLOCKED_HOST_SUFFIXES:
        if host == blocked or host.endswith("." + blocked):
            return False
    return True


def fetch_url(url: str, *, timeout: float = 20.0, max_bytes: int = 1_500_000) -> ScrapeResult:
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    if not _host_allowed(url):
        return ScrapeResult(False, url, error="URL blocked by Sophyane safety policy")

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", 200) or 200
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raw = raw[:max_bytes]
            charset = response.headers.get_content_charset() or "utf-8"
            content = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as error:
        return ScrapeResult(False, url, status=error.code, error=f"HTTP {error.code}")
    except Exception as error:  # noqa: BLE001
        return ScrapeResult(False, url, error=str(error))

    parser = _TextExtractor()
    try:
        parser.feed(content)
        parser.close()
    except Exception:
        # fall back to tag strip
        title, body, links = "", re.sub(r"<[^>]+>", " ", content), []
    else:
        title, body, links = parser.result()

    # resolve relative links
    resolved = []
    for link in links[:50]:
        resolved.append(urllib.parse.urljoin(url, link))
    body = html.unescape(body)[:50_000]
    digest = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()
    result = ScrapeResult(
        ok=True,
        url=url,
        title=title[:300],
        text=body,
        links=resolved,
        status=status,
        content_hash=digest,
    )
    _persist_scrape(result)
    return result


def _persist_scrape(result: ScrapeResult) -> Path | None:
    try:
        SCRAPE_DIR.mkdir(parents=True, exist_ok=True)
        path = SCRAPE_DIR / f"{int(result.fetched_at)}_{result.content_hash[:12]}.json"
        path.write_text(json.dumps(result.to_dict(), indent=2)[:200_000], encoding="utf-8")
        return path
    except OSError:
        return None


def search_scrapes(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    query_l = query.lower().strip()
    if not SCRAPE_DIR.exists():
        return []
    hits: list[dict[str, Any]] = []
    for path in sorted(SCRAPE_DIR.glob("*.json"), reverse=True)[:200]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        blob = f"{data.get('title','')} {data.get('text','')} {data.get('url','')}".lower()
        if query_l in blob:
            hits.append(
                {
                    "url": data.get("url"),
                    "title": data.get("title"),
                    "snippet": str(data.get("text") or "")[:280],
                    "path": str(path),
                }
            )
        if len(hits) >= limit:
            break
    return hits


def scrape_for_improvement(urls: list[str]) -> dict[str, Any]:
    """Fetch several URLs and return compact improvement-oriented notes."""
    results = []
    for url in urls[:5]:
        item = fetch_url(url)
        results.append(
            {
                "ok": item.ok,
                "url": item.url,
                "title": item.title,
                "summary": item.text[:1200],
                "hash": item.content_hash,
                "error": item.error,
            }
        )
    return {
        "fetched": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "results": results,
        "scraped_at": time.time(),
    }
