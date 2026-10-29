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


def _http_json(url: str, *, timeout: float = 12.0) -> dict[str, Any] | list[Any] | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(2_000_000)
            return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None


def _wikipedia_search(query: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Live Wikipedia OpenSearch + summary (no API key)."""
    hits: list[dict[str, Any]] = []
    q = query.strip()
    if not q:
        return hits
    # Prefer direct summary for person/entity-like queries
    title_guess = q
    for prefix in ("who is ", "who was ", "what is ", "what are ", "tell me about "):
        low = q.lower()
        if low.startswith(prefix):
            title_guess = q[len(prefix) :].strip(" ?.")
            break
    summary_url = (
        "https://en.wikipedia.org/api/rest_v1/page/summary/"
        + urllib.parse.quote(title_guess.replace(" ", "_"), safe="")
    )
    summary = _http_json(summary_url)
    if isinstance(summary, dict) and summary.get("extract") and summary.get("type") != "disambiguation":
        hits.append(
            {
                "title": str(summary.get("title") or title_guess),
                "snippet": str(summary.get("extract") or "")[:900],
                "url": str(
                    (summary.get("content_urls") or {}).get("desktop", {}).get("page")
                    or summary.get("content_urls", {}).get("desktop", {}).get("page")
                    or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title_guess.replace(' ', '_'))}"
                ),
                "source": "wikipedia",
            }
        )
    # OpenSearch for more hits
    search_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": q,
            "limit": str(limit),
            "namespace": "0",
            "format": "json",
        }
    )
    data = _http_json(search_url)
    if isinstance(data, list) and len(data) >= 4:
        titles, descs, urls = data[1], data[2], data[3]
        for i, title in enumerate(titles):
            url = urls[i] if i < len(urls) else ""
            snippet = descs[i] if i < len(descs) else ""
            if any(h.get("url") == url for h in hits):
                continue
            # Enrich first open-search hit with summary if needed
            if not snippet and title:
                s2 = _http_json(
                    "https://en.wikipedia.org/api/rest_v1/page/summary/"
                    + urllib.parse.quote(str(title).replace(" ", "_"), safe="")
                )
                if isinstance(s2, dict):
                    snippet = str(s2.get("extract") or "")[:700]
            hits.append(
                {
                    "title": str(title),
                    "snippet": str(snippet)[:700],
                    "url": str(url),
                    "source": "wikipedia",
                }
            )
            if len(hits) >= limit + 1:
                break
    return hits[: max(limit, 1) + 1]


def _duckduckgo_search(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """DuckDuckGo Instant Answer API (no API key)."""
    hits: list[dict[str, Any]] = []
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    data = _http_json(url)
    if not isinstance(data, dict):
        return hits
    abstract = str(data.get("AbstractText") or "").strip()
    heading = str(data.get("Heading") or query).strip()
    abs_url = str(data.get("AbstractURL") or data.get("AbstractSource") or "").strip()
    if abstract:
        hits.append(
            {
                "title": heading or query,
                "snippet": abstract[:900],
                "url": abs_url or "https://duckduckgo.com/?" + urllib.parse.urlencode({"q": query}),
                "source": "duckduckgo",
            }
        )
    for topic in data.get("RelatedTopics") or []:
        if len(hits) >= limit:
            break
        if not isinstance(topic, dict):
            continue
        # Nested topics
        if "Topics" in topic and isinstance(topic["Topics"], list):
            for sub in topic["Topics"]:
                if not isinstance(sub, dict):
                    continue
                text = str(sub.get("Text") or "").strip()
                first_url = str(sub.get("FirstURL") or "").strip()
                if text and first_url:
                    hits.append(
                        {
                            "title": text.split(" - ")[0][:120],
                            "snippet": text[:500],
                            "url": first_url,
                            "source": "duckduckgo",
                        }
                    )
                if len(hits) >= limit:
                    break
            continue
        text = str(topic.get("Text") or "").strip()
        first_url = str(topic.get("FirstURL") or "").strip()
        if text and first_url:
            hits.append(
                {
                    "title": text.split(" - ")[0][:120],
                    "snippet": text[:500],
                    "url": first_url,
                    "source": "duckduckgo",
                }
            )
    return hits[:limit]


def web_search(query: str, *, limit: int = 6) -> dict[str, Any]:
    """Live internet search for agent/chat grounding (Wikipedia + DuckDuckGo)."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "query": q, "results": [], "error": "empty query"}
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        results.extend(_wikipedia_search(q, limit=3))
    except Exception as error:  # noqa: BLE001
        errors.append(f"wikipedia: {error}")
    try:
        for hit in _duckduckgo_search(q, limit=limit):
            if any(h.get("url") == hit.get("url") for h in results):
                continue
            results.append(hit)
    except Exception as error:  # noqa: BLE001
        errors.append(f"duckduckgo: {error}")
    # Local scrape store as last resort
    if len(results) < 2:
        for hit in search_scrapes(q, limit=3):
            results.append(
                {
                    "title": hit.get("title") or hit.get("url"),
                    "snippet": hit.get("snippet") or "",
                    "url": hit.get("url") or "",
                    "source": "local_scrape",
                }
            )
    results = results[:limit]
    return {
        "ok": bool(results),
        "query": q,
        "results": results,
        "errors": errors,
        "count": len(results),
    }


def needs_web_research(message: str) -> bool:
    """Heuristic: factual / current-events / entity questions benefit from live search.

    Matches phrases anywhere in the text so chat prefixes like
    ``User (email): who is …`` still trigger research.
    """
    text = (message or "").strip().lower()
    if not text or len(text) < 3:
        return False
    # Strip common client prefixes
    for prefix in ("user:", "question:", "user ("):
        if text.startswith(prefix) or "): " in text[:80]:
            # take last segment after a colon when short
            if ":" in text:
                tail = text.rsplit(":", 1)[-1].strip()
                if len(tail) >= 3:
                    text = tail
            break
    phrases = (
        "who is ",
        "who was ",
        "who are ",
        "what is ",
        "what are ",
        "what was ",
        "when did ",
        "when was ",
        "where is ",
        "where was ",
        "tell me about ",
        "search ",
        "look up ",
        "lookup ",
        "find online ",
        "define ",
        "latest ",
        "news about ",
        "google ",
    )
    if any(p in text for p in phrases):
        return True
    if text.startswith("which ") or text.startswith("current "):
        return True
    # Short person/entity style questions
    words = text.replace("?", " ").split()
    if text.endswith("?") and len(words) <= 16:
        if any(k in text for k in ("who", "what", "when", "where", "which", "why", "how many")):
            return True
    # Bare-ish person name style: 2–5 words without code punctuation
    if 2 <= len(words) <= 5 and "?" in (message or "") and not any(c in text for c in "{}[]=/\\"):
        return True
    if "http://" in text or "https://" in text:
        return False
    return False


def format_search_context(search: dict[str, Any], *, max_chars: int = 3500) -> str:
    """Compact source block for LLM system/user prompts."""
    results = search.get("results") if isinstance(search, dict) else None
    if not results:
        return ""
    lines = ["LIVE INTERNET RESEARCH (use these facts; prefer them over stale model memory):"]
    for i, hit in enumerate(results, 1):
        title = str(hit.get("title") or "source")
        snippet = str(hit.get("snippet") or "").strip()
        url = str(hit.get("url") or "")
        lines.append(f"[{i}] {title}\n{snippet}\nURL: {url}")
    text = "\n\n".join(lines)
    return text[:max_chars]


def grounded_answer_from_search(query: str, search: dict[str, Any]) -> str:
    """Fallback answer when the small local LLM is weak or wrong."""
    results = (search or {}).get("results") or []
    if not results:
        return ""
    primary = results[0]
    title = str(primary.get("title") or query).strip()
    snippet = str(primary.get("snippet") or "").strip()
    url = str(primary.get("url") or "").strip()
    lines = [
        f"**{title}**",
        "",
        snippet or "No detailed extract available.",
    ]
    if url:
        lines.extend(["", f"Source: {url}"])
    if len(results) > 1:
        lines.append("")
        lines.append("Also see:")
        for hit in results[1:4]:
            t = str(hit.get("title") or "source")
            u = str(hit.get("url") or "")
            if u:
                lines.append(f"- {t}: {u}")
    return "\n".join(lines)


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
