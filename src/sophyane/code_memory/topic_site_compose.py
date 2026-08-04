"""Internet-grounded informational website composition for SLI.

This module handles generic requests such as:
    make a website about renewable energy
    create a webpage on Lahore
    build an informational site about photosynthesis

It retrieves source material through the public MediaWiki API, constructs a
responsive self-contained HTML document, validates request relevance and
records acquisition provenance.

No local or cloud LLM is used.
"""
from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
import time
import urllib.parse
import urllib.request

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Progress = Callable[[str], None]

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

MEMORY = (
    Path.home()
    / ".local/share/sophyane/code_memory"
)

EVENTS = (
    MEMORY
    / "topic_site_events.jsonl"
)

MAX_IMAGE_BYTES = 4_000_000


@dataclass
class TopicSource:
    requested_topic: str
    resolved_title: str
    extract: str
    page_url: str
    image_url: str | None
    image_data_uri: str | None


def _progress(
    progress: Progress | None,
) -> Progress:
    return progress or (lambda _message: None)


def _normalise(value: str) -> str:
    return " ".join(
        str(value or "").strip().split()
    )


def extract_topic(request: str) -> str:
    """Extract the subject without embedding subject-specific knowledge."""

    value = _normalise(request)

    patterns = (
        r"\bwebsite\s+(?:on|about|for)\s+(.+)$",
        r"\bwebpage\s+(?:on|about|for)\s+(.+)$",
        r"\bsite\s+(?:on|about|for)\s+(.+)$",
        r"\binformational\s+(?:website|webpage|site)\s+(?:on|about)\s+(.+)$",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            value,
            flags=re.I,
        )

        if match:
            topic = match.group(1)

            topic = re.sub(
                r"\b(?:in\s+one\s+self[- ]contained\s+index\.html)\b.*$",
                "",
                topic,
                flags=re.I,
            )

            return _normalise(topic).strip(" .,:;-")

    cleaned = re.sub(
        r"^(?:please\s+)?"
        r"(?:make|create|build|design|generate|develop)\s+",
        "",
        value,
        flags=re.I,
    )

    cleaned = re.sub(
        r"\b(?:a|an|the)\s+",
        "",
        cleaned,
        count=1,
        flags=re.I,
    )

    cleaned = re.sub(
        r"\b(?:website|webpage|site)\b",
        "",
        cleaned,
        count=1,
        flags=re.I,
    )

    cleaned = re.sub(
        r"^(?:on|about|for)\s+",
        "",
        cleaned,
        flags=re.I,
    )

    return _normalise(cleaned).strip(" .,:;-")


def is_topic_site_request(request: str) -> bool:
    value = _normalise(request).lower()

    has_build = any(
        term in value
        for term in (
            "make",
            "create",
            "build",
            "design",
            "generate",
            "develop",
        )
    )

    has_site = any(
        term in value
        for term in (
            "website",
            "webpage",
            "informational site",
            "information site",
        )
    )

    interactive_families = (
        "game",
        "calculator",
        "dashboard",
        "editor",
        "quiz",
        "simulation",
        "visualizer",
        "todo",
        "kanban",
    )

    return (
        has_build
        and has_site
        and not any(
            family in value
            for family in interactive_families
        )
        and bool(extract_topic(request))
    )


def _api_json(
    parameters: dict[str, str],
    *,
    timeout: int = 25,
) -> dict:
    query = urllib.parse.urlencode(
        {
            **parameters,
            "format": "json",
            "formatversion": "2",
            "origin": "*",
        }
    )

    request = urllib.request.Request(
        WIKIPEDIA_API + "?" + query,
        headers={
            "User-Agent":
                "Sophyane-SLI-Topic-Site/1.0",
            "Accept":
                "application/json",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8",
                errors="replace",
            )
        )


def _search_title(
    topic: str,
) -> str:
    payload = _api_json(
        {
            "action": "query",
            "list": "search",
            "srsearch": topic,
            "srnamespace": "0",
            "srlimit": "5",
        }
    )

    results = (
        payload.get("query", {})
        .get("search", [])
    )

    if not results:
        raise RuntimeError(
            f"No encyclopedic source was found for: {topic}"
        )

    topic_tokens = {
        token
        for token in re.findall(
            r"[a-z0-9]+",
            topic.lower(),
        )
        if len(token) > 1
    }

    def score(item: dict) -> tuple[int, int]:
        title = str(
            item.get("title") or ""
        )

        title_tokens = {
            token
            for token in re.findall(
                r"[a-z0-9]+",
                title.lower(),
            )
            if len(token) > 1
        }

        overlap = len(
            topic_tokens & title_tokens
        )

        exact = int(
            title.lower() == topic.lower()
        )

        return exact, overlap

    best = max(
        results,
        key=score,
    )

    return str(best["title"])


def _download_image_data_uri(
    image_url: str | None,
) -> str | None:
    if not image_url:
        return None

    request = urllib.request.Request(
        image_url,
        headers={
            "User-Agent":
                "Sophyane-SLI-Topic-Site/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=25,
        ) as response:
            content_length = int(
                response.headers.get(
                    "Content-Length",
                    "0",
                )
                or 0
            )

            if content_length > MAX_IMAGE_BYTES:
                return None

            content = response.read(
                MAX_IMAGE_BYTES + 1
            )

            if len(content) > MAX_IMAGE_BYTES:
                return None

            content_type = (
                response.headers.get_content_type()
                or mimetypes.guess_type(image_url)[0]
                or "image/jpeg"
            )

    except Exception:
        return None

    encoded = base64.b64encode(
        content
    ).decode("ascii")

    return (
        f"data:{content_type};base64,{encoded}"
    )


def retrieve_topic(
    topic: str,
    *,
    progress: Progress | None = None,
) -> TopicSource:
    progress = _progress(progress)

    progress(
        f"SLI topic search: {topic}"
    )

    title = _search_title(topic)

    progress(
        f"SLI topic resolved: {title}"
    )

    payload = _api_json(
        {
            "action": "query",
            "prop":
                "extracts|pageimages|info",

            "titles":
                title,

            "explaintext":
                "1",

            "exsectionformat":
                "plain",

            "exlimit":
                "1",

            "piprop":
                "original|thumbnail",

            "pithumbsize":
                "1400",

            "inprop":
                "url",
        }
    )

    pages = (
        payload.get("query", {})
        .get("pages", [])
    )

    if not pages:
        raise RuntimeError(
            f"No source page was returned for: {title}"
        )

    page = pages[0]

    extract = _normalise_multiline(
        str(page.get("extract") or "")
    )

    if len(extract) < 300:
        raise RuntimeError(
            "The retrieved source did not contain "
            "enough factual text."
        )

    original = page.get("original") or {}
    thumbnail = page.get("thumbnail") or {}

    image_url = (
        original.get("source")
        or thumbnail.get("source")
    )

    image_data_uri = (
        _download_image_data_uri(
            str(image_url)
            if image_url
            else None
        )
    )

    return TopicSource(
        requested_topic=topic,
        resolved_title=str(
            page.get("title") or title
        ),
        extract=extract,
        page_url=str(
            page.get("fullurl") or ""
        ),
        image_url=(
            str(image_url)
            if image_url
            else None
        ),
        image_data_uri=image_data_uri,
    )


def _normalise_multiline(
    value: str,
) -> str:
    lines = []

    for raw_line in str(
        value or ""
    ).splitlines():
        line = _normalise(raw_line)

        if line:
            lines.append(line)

    return "\n".join(lines)


def _paragraphs(
    extract: str,
) -> list[str]:
    output = []

    for block in re.split(
        r"\n+",
        extract,
    ):
        block = _normalise(block)

        if len(block) < 80:
            continue

        # Remove MediaWiki heading syntax if present.
        block = re.sub(
            r"^=+\s*(.*?)\s*=+$",
            r"\1",
            block,
        )

        output.append(block)

    if not output:
        # Some API responses arrive as one continuous line.
        sentences = re.split(
            r"(?<=[.!?])\s+",
            _normalise(extract),
        )

        current = []

        for sentence in sentences:
            current.append(sentence)

            if len(" ".join(current)) >= 350:
                output.append(
                    " ".join(current)
                )
                current = []

        if current:
            output.append(
                " ".join(current)
            )

    return output[:18]


def _split_sections(
    paragraphs: list[str],
) -> list[tuple[str, list[str]]]:
    if not paragraphs:
        return []

    headings = (
        "Overview",
        "Background",
        "Geography and environment",
        "People and society",
        "Culture and heritage",
        "Economy and development",
        "Modern significance",
    )

    remaining = paragraphs[1:]
    section_count = min(
        max(2, len(remaining) // 2),
        len(headings),
    )

    if not remaining:
        return []

    groups = [
        []
        for _ in range(section_count)
    ]

    for index, paragraph in enumerate(
        remaining
    ):
        groups[
            min(
                index * section_count
                // max(1, len(remaining)),
                section_count - 1,
            )
        ].append(paragraph)

    return [
        (
            headings[index],
            group,
        )
        for index, group in enumerate(groups)
        if group
    ]


def compose_document(
    source: TopicSource,
) -> str:
    paragraphs = _paragraphs(
        source.extract
    )

    if not paragraphs:
        raise RuntimeError(
            "No usable paragraphs were retrieved."
        )

    introduction = paragraphs[0]
    sections = _split_sections(
        paragraphs
    )

    title = html.escape(
        source.resolved_title
    )

    topic = html.escape(
        source.requested_topic
    )

    introduction_html = html.escape(
        introduction
    )

    image_html = ""

    if source.image_data_uri:
        image_html = (
            '<figure class="hero-image">'
            f'<img src="{source.image_data_uri}" '
            f'alt="{title}">'
            f'<figcaption>{title}</figcaption>'
            "</figure>"
        )

    section_html = []

    for heading, bodies in sections:
        body = "\n".join(
            f"<p>{html.escape(paragraph)}</p>"
            for paragraph in bodies
        )

        section_html.append(
            '<section class="content-section">'
            f"<h2>{html.escape(heading)}</h2>"
            f"{body}"
            "</section>"
        )

    source_link = (
        html.escape(
            source.page_url,
            quote=True,
        )
        if source.page_url
        else "#"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="An internet-grounded informational website about {topic}.">
<title>{title} — Informational Guide</title>
<style>
:root {{
  color-scheme: light;
  --ink: #172033;
  --muted: #586477;
  --surface: #ffffff;
  --soft: #eef3f7;
  --accent: #176b4d;
  --accent-dark: #0d4935;
  --line: #d9e1e8;
  --max: 1120px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  color: var(--ink);
  background: var(--soft);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.7;
}}
a {{ color: inherit; }}
.site-header {{
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(255,255,255,.94);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}}
.nav {{
  width: min(var(--max), calc(100% - 32px));
  min-height: 68px;
  margin: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}}
.brand {{
  color: var(--accent-dark);
  font-weight: 800;
  letter-spacing: .02em;
  text-decoration: none;
}}
.nav-links {{
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
}}
.nav-links a {{
  color: var(--muted);
  font-size: .94rem;
  text-decoration: none;
}}
.hero {{
  background:
    radial-gradient(circle at 85% 20%, rgba(255,255,255,.18), transparent 28%),
    linear-gradient(135deg, #0d4935, #198754);
  color: #fff;
}}
.hero-inner {{
  width: min(var(--max), calc(100% - 32px));
  margin: auto;
  padding: clamp(64px, 10vw, 120px) 0;
  display: grid;
  grid-template-columns: minmax(0,1.15fr) minmax(280px,.85fr);
  gap: 48px;
  align-items: center;
}}
.eyebrow {{
  margin: 0 0 12px;
  font-size: .84rem;
  font-weight: 800;
  letter-spacing: .14em;
  text-transform: uppercase;
  opacity: .82;
}}
h1 {{
  margin: 0;
  max-width: 12ch;
  font-size: clamp(3rem, 8vw, 6.7rem);
  line-height: .96;
  letter-spacing: -.055em;
}}
.hero-copy {{
  margin: 24px 0 0;
  max-width: 68ch;
  font-size: clamp(1.02rem, 2vw, 1.25rem);
  opacity: .93;
}}
.hero-image {{
  margin: 0;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,.28);
  border-radius: 22px;
  background: rgba(255,255,255,.1);
  box-shadow: 0 24px 70px rgba(0,0,0,.25);
}}
.hero-image img {{
  display: block;
  width: 100%;
  max-height: 520px;
  object-fit: cover;
}}
.hero-image figcaption {{
  padding: 10px 14px;
  font-size: .78rem;
  opacity: .8;
}}
main {{
  width: min(var(--max), calc(100% - 32px));
  margin: 0 auto;
  padding: 64px 0 96px;
}}
.introduction {{
  margin-bottom: 28px;
  padding: clamp(28px, 5vw, 52px);
  border-radius: 22px;
  background: var(--surface);
  box-shadow: 0 15px 45px rgba(23,32,51,.08);
}}
.introduction h2,
.content-section h2 {{
  margin: 0 0 18px;
  color: var(--accent-dark);
  font-size: clamp(1.55rem, 3vw, 2.35rem);
  line-height: 1.15;
}}
.introduction p {{
  margin: 0;
  font-size: clamp(1.04rem, 2vw, 1.22rem);
}}
.section-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0,1fr));
  gap: 24px;
}}
.content-section {{
  padding: clamp(24px, 4vw, 40px);
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--surface);
}}
.content-section p {{
  margin: 0 0 16px;
  color: #354156;
}}
.content-section p:last-child {{ margin-bottom: 0; }}
.source-card {{
  margin-top: 28px;
  padding: 24px;
  border-radius: 18px;
  background: #dfeee8;
}}
.source-card h2 {{
  margin: 0 0 8px;
  color: var(--accent-dark);
}}
.source-card p {{ margin: 0; }}
.source-card a {{ font-weight: 750; }}
footer {{
  padding: 24px 16px;
  color: var(--muted);
  text-align: center;
  border-top: 1px solid var(--line);
  background: #fff;
}}
@media (max-width: 820px) {{
  .hero-inner,
  .section-grid {{
    grid-template-columns: 1fr;
  }}
  .hero-image {{ max-width: 620px; }}
}}
@media (max-width: 560px) {{
  .nav {{
    align-items: flex-start;
    flex-direction: column;
    padding: 15px 0;
  }}
  .nav-links {{ gap: 12px; }}
}}
</style>
</head>
<body>
<header class="site-header">
  <nav class="nav" aria-label="Primary">
    <a class="brand" href="#top">{title}</a>
    <div class="nav-links">
      <a href="#overview">Overview</a>
      <a href="#explore">Explore</a>
      <a href="#sources">Sources</a>
    </div>
  </nav>
</header>

<section class="hero" id="top">
  <div class="hero-inner">
    <div>
      <p class="eyebrow">Internet-grounded informational guide</p>
      <h1>{title}</h1>
      <p class="hero-copy">{introduction_html}</p>
    </div>
    {image_html}
  </div>
</section>

<main>
  <section class="introduction" id="overview">
    <h2>Overview</h2>
    <p>{introduction_html}</p>
  </section>

  <div class="section-grid" id="explore">
    {''.join(section_html)}
  </div>

  <section class="source-card" id="sources">
    <h2>Source and attribution</h2>
    <p>
      This website was composed from the Wikipedia article
      <a href="{source_link}" target="_blank" rel="noopener noreferrer">{title}</a>.
      Wikipedia text is available under its applicable Creative Commons licence.
    </p>
  </section>
</main>

<footer>
  Generated through Sophyane SLI internet-grounded topic composition.
</footer>

<script>
document.querySelectorAll('a[href^="#"]').forEach(function(link) {{
  link.addEventListener("click", function(event) {{
    var target = document.querySelector(link.getAttribute("href"));
    if (target) {{
      event.preventDefault();
      target.scrollIntoView({{behavior: "smooth", block: "start"}});
    }}
  }});
}});
</script>
</body>
</html>
"""


def validate_document(
    document: str,
    topic: str,
) -> tuple[bool, list[str]]:
    low = str(document or "").lower()

    issues = []

    if len(document) < 2_000:
        issues.append(
            "document is too small"
        )

    if not (
        "<html" in low
        and "<body" in low
        and "</html>" in low
    ):
        issues.append(
            "incomplete HTML document"
        )

    identity_terms = [
        token
        for token in re.findall(
            r"[a-z0-9]+",
            topic.lower(),
        )
        if len(token) > 1
    ]

    matched = [
        token
        for token in identity_terms
        if token in low
    ]

    required = (
        1
        if len(identity_terms) <= 2
        else 2
    )

    if len(matched) < required:
        issues.append(
            "insufficient topic identity"
        )

    if "<script" not in low:
        issues.append(
            "missing navigation behavior"
        )

    return not issues, issues


def compose_topic_site(
    request: str,
    workspace: Path,
    *,
    progress: Progress | None = None,
) -> str:
    progress = _progress(progress)

    topic = extract_topic(request)

    if not topic:
        return (
            "SLI topic-site composition failed: "
            "no topic could be derived from the request.\n"
            "No LLM fallback was used."
        )

    workspace = Path(workspace)
    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = workspace / "index.html"
    output.unlink(
        missing_ok=True,
    )

    try:
        source = retrieve_topic(
            topic,
            progress=progress,
        )

        document = compose_document(
            source
        )

        accepted, issues = validate_document(
            document,
            topic,
        )

        if not accepted:
            return (
                "SLI topic-site composition failed validation.\n"
                "Issues: "
                + "; ".join(issues)
                + "\nNo LLM fallback was used."
            )

        output.write_text(
            document,
            encoding="utf-8",
        )

        event = {
            "request": request,
            "topic": topic,
            "resolved_title":
                source.resolved_title,
            "source_url":
                source.page_url,
            "image_embedded":
                bool(source.image_data_uri),
            "bytes":
                output.stat().st_size,
            "timestamp":
                time.time(),
        }

        MEMORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        with EVENTS.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                )
                + "\n"
            )

        return "\n".join(
            [
                "Sophyane internet-grounded topic-site composer",
                f"Request: {request}",
                f"Topic: {topic}",
                (
                    "Resolved source: "
                    f"{source.resolved_title}"
                ),
                (
                    "Lead image embedded: "
                    f"{bool(source.image_data_uri)}"
                ),
                f"Bytes: {output.stat().st_size}",
                "Files: index.html",
                "Validation: passed",
                "Success: True",
                (
                    "Inference: public source retrieval + "
                    "deterministic SLI composition; "
                    "no local/cloud LLM"
                ),
            ]
        )

    except Exception as error:
        output.unlink(
            missing_ok=True,
        )

        return (
            "SLI topic-site acquisition failed.\n"
            f"Error: {type(error).__name__}: {error}\n"
            "No LLM fallback was used."
        )


__all__ = [
    "compose_topic_site",
    "extract_topic",
    "is_topic_site_request",
    "retrieve_topic",
    "validate_document",
]
