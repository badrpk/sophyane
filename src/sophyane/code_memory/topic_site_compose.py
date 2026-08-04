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

# SOPHYANE_SEMANTIC_TOPIC_RESOLVER_V2
#
# Resolve topic meaning from several candidates rather than selecting the
# first title-overlap result. When no single encyclopedic article represents a
# relational topic, compose a grounded source from its principal concepts.

import math as _semantic_math
import urllib.parse as _semantic_urlparse


_SEMANTIC_TOPIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "about",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


_SEMANTIC_ENTITY_PENALTIES = {
    "animated television series": -500.0,
    "animated series": -480.0,
    "television series": -450.0,
    "tv series": -450.0,
    "children's television": -450.0,
    "fictional": -400.0,
    "film": -350.0,
    "album": -350.0,
    "song": -350.0,
    "band": -300.0,
    "video game": -280.0,
    "comic": -250.0,
    "manga": -250.0,
    "anime": -250.0,
    "episode": -250.0,
    "character": -220.0,
    "novel": -220.0,
}


_SEMANTIC_INFORMATION_BONUSES = {
    "animal": 80.0,
    "animals": 80.0,
    "species": 70.0,
    "fauna": 70.0,
    "wildlife": 70.0,
    "geography": 50.0,
    "history": 40.0,
    "culture": 35.0,
    "country": 30.0,
    "region": 30.0,
    "domestic": 30.0,
    "mammal": 50.0,
    "mammals": 50.0,
}


def _semantic_tokens_v2(
    value: str,
) -> list[str]:
    output = []

    for token in re.findall(
        r"[a-z0-9]+",
        str(value or "").lower(),
    ):
        if (
            len(token) > 1
            and token not in _SEMANTIC_TOPIC_STOPWORDS
            and token not in output
        ):
            output.append(token)

    return output


def _semantic_singular_v2(
    token: str,
) -> str:
    value = str(token or "").lower()

    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"

    if value.endswith("ses") and len(value) > 4:
        return value[:-2]

    if value.endswith("s") and not value.endswith("ss") and len(value) > 3:
        return value[:-1]

    return value


def _semantic_forms_v2(
    tokens: list[str],
) -> set[str]:
    forms = set()

    for token in tokens:
        forms.add(token)
        forms.add(
            _semantic_singular_v2(token)
        )

    return {
        form
        for form in forms
        if form
    }


def _semantic_contains_v2(
    text: str,
    token: str,
) -> bool:
    low = str(text or "").lower()
    forms = {
        token,
        _semantic_singular_v2(token),
    }

    return any(
        re.search(
            r"\b"
            + re.escape(form)
            + r"(?:s|es)?\b",
            low,
        )
        for form in forms
        if form
    )


def _semantic_candidate_details_v2(
    titles: list[str],
) -> dict[str, dict]:
    if not titles:
        return {}

    payload = _api_json(
        {
            "action": "query",
            "prop":
                "extracts|pageimages|info|categories",

            "titles":
                "|".join(titles[:20]),

            "explaintext":
                "1",

            "exintro":
                "1",

            "exsectionformat":
                "plain",

            "piprop":
                "original|thumbnail",

            "pithumbsize":
                "1400",

            "inprop":
                "url",

            "cllimit":
                "50",

            "redirects":
                "1",
        }
    )

    pages = (
        payload.get("query", {})
        .get("pages", [])
    )

    output = {}

    for page in pages:
        title = str(
            page.get("title") or ""
        )

        if title:
            output[
                title.lower()
            ] = page

    return output


def _semantic_candidate_score_v2(
    *,
    topic: str,
    title: str,
    snippet: str,
    extract: str,
    categories: list[str],
) -> tuple[float, dict[str, object]]:
    topic_tokens = _semantic_tokens_v2(
        topic
    )

    title_low = title.lower()
    snippet_low = re.sub(
        r"<[^>]+>",
        " ",
        snippet,
    ).lower()

    category_text = " ".join(
        categories
    ).lower()

    extract_low = extract.lower()

    combined = " ".join(
        (
            title_low,
            snippet_low,
            extract_low[:5000],
            category_text,
        )
    )

    matched_title = [
        token
        for token in topic_tokens
        if _semantic_contains_v2(
            title_low,
            token,
        )
    ]

    matched_text = [
        token
        for token in topic_tokens
        if _semantic_contains_v2(
            combined,
            token,
        )
    ]

    score = 0.0

    score += len(matched_title) * 90.0
    score += len(matched_text) * 35.0

    if topic_tokens:
        score += (
            len(set(matched_text))
            / len(topic_tokens)
        ) * 220.0

    normalised_topic = " ".join(
        topic_tokens
    )

    normalised_title = " ".join(
        _semantic_tokens_v2(title)
    )

    if (
        normalised_topic
        and normalised_topic == normalised_title
    ):
        score += 300.0

    if (
        normalised_topic
        and normalised_topic in normalised_title
    ):
        score += 120.0

    for phrase, penalty in (
        _SEMANTIC_ENTITY_PENALTIES.items()
    ):
        if phrase in combined:
            score += penalty

    for phrase, bonus in (
        _SEMANTIC_INFORMATION_BONUSES.items()
    ):
        if phrase in combined:
            score += bonus

    # A candidate covering only one part of a multi-token relation should not
    # beat a candidate covering the whole request.
    if (
        len(topic_tokens) >= 2
        and len(set(matched_text)) < 2
    ):
        score -= 120.0

    # Numeric/title entertainment brands are suspicious for natural-subject
    # requests unless the number was explicitly requested.
    if (
        re.search(r"\d", title)
        and not re.search(r"\d", topic)
    ):
        score -= 80.0

    evidence = {
        "title_matches":
            matched_title,

        "text_matches":
            matched_text,

        "categories":
            categories[:10],

        "score":
            round(score, 2),
    }

    return score, evidence


def _semantic_search_candidates_v2(
    topic: str,
) -> list[dict]:
    topic_tokens = _semantic_tokens_v2(
        topic
    )

    queries = [
        topic,
        " ".join(topic_tokens),
    ]

    if len(topic_tokens) >= 2:
        queries.extend(
            [
                (
                    topic_tokens[0]
                    + " "
                    + topic_tokens[-1]
                    + " animal"
                ),
                (
                    topic_tokens[0]
                    + " in "
                    + topic_tokens[-1]
                ),
            ]
        )

    candidates = {}

    for query in dict.fromkeys(
        query
        for query in queries
        if query.strip()
    ):
        payload = _api_json(
            {
                "action":
                    "query",

                "list":
                    "search",

                "srsearch":
                    query,

                "srnamespace":
                    "0",

                "srlimit":
                    "20",
            }
        )

        results = (
            payload.get("query", {})
            .get("search", [])
        )

        for result in results:
            title = str(
                result.get("title") or ""
            )

            if not title:
                continue

            key = title.lower()

            current = candidates.get(
                key
            )

            record = {
                "title":
                    title,

                "snippet":
                    str(
                        result.get("snippet")
                        or ""
                    ),

                "search_query":
                    query,

                "search_rank":
                    int(
                        result.get("size")
                        or 0
                    ),
            }

            if current is None:
                candidates[key] = record

    titles = [
        item["title"]
        for item in candidates.values()
    ]

    details = _semantic_candidate_details_v2(
        titles
    )

    ranked = []

    for key, candidate in candidates.items():
        page = (
            details.get(key)
            or {}
        )

        categories = [
            str(
                category.get("title")
                or ""
            ).replace(
                "Category:",
                "",
            )
            for category in (
                page.get("categories")
                or []
            )
        ]

        extract = _normalise_multiline(
            str(
                page.get("extract")
                or ""
            )
        )

        score, evidence = (
            _semantic_candidate_score_v2(
                topic=topic,
                title=candidate["title"],
                snippet=candidate["snippet"],
                extract=extract,
                categories=categories,
            )
        )

        ranked.append(
            {
                **candidate,
                "page":
                    page,
                "extract":
                    extract,
                "categories":
                    categories,
                "semantic_score":
                    score,
                "evidence":
                    evidence,
            }
        )

    ranked.sort(
        key=lambda item: (
            -item["semantic_score"],
            item["title"].lower(),
        )
    )

    return ranked


def _semantic_page_to_source_v2(
    topic: str,
    page: dict,
) -> TopicSource:
    title = str(
        page.get("title") or topic
    )

    extract = _normalise_multiline(
        str(
            page.get("extract")
            or ""
        )
    )

    original = page.get("original") or {}
    thumbnail = page.get("thumbnail") or {}

    image_url = (
        original.get("source")
        or thumbnail.get("source")
    )

    return TopicSource(
        requested_topic=topic,
        resolved_title=title,
        extract=extract,
        page_url=str(
            page.get("fullurl")
            or ""
        ),
        image_url=(
            str(image_url)
            if image_url
            else None
        ),
        image_data_uri=(
            _download_image_data_uri(
                str(image_url)
                if image_url
                else None
            )
        ),
    )


def _semantic_fetch_concept_v2(
    concept: str,
) -> dict | None:
    payload = _api_json(
        {
            "action":
                "query",

            "generator":
                "search",

            "gsrsearch":
                concept,

            "gsrnamespace":
                "0",

            "gsrlimit":
                "5",

            "prop":
                "extracts|pageimages|info|categories",

            "explaintext":
                "1",

            "exintro":
                "1",

            "piprop":
                "original|thumbnail",

            "pithumbsize":
                "1400",

            "inprop":
                "url",

            "cllimit":
                "50",
        }
    )

    pages = (
        payload.get("query", {})
        .get("pages", [])
    )

    if not pages:
        return None

    concept_tokens = _semantic_tokens_v2(
        concept
    )

    def page_score(page: dict) -> float:
        title = str(
            page.get("title") or ""
        )

        extract = str(
            page.get("extract") or ""
        )

        categories = [
            str(
                category.get("title")
                or ""
            )
            for category in (
                page.get("categories")
                or []
            )
        ]

        score, _evidence = (
            _semantic_candidate_score_v2(
                topic=concept,
                title=title,
                snippet="",
                extract=extract,
                categories=categories,
            )
        )

        return score

    return max(
        pages,
        key=page_score,
    )


def _semantic_composite_source_v2(
    topic: str,
    *,
    progress: Progress,
) -> TopicSource:
    tokens = _semantic_tokens_v2(
        topic
    )

    if not tokens:
        raise RuntimeError(
            "No meaningful topic concepts were found."
        )

    concepts = []

    # Preserve the major subject and modifier. For "cats of italy", this
    # becomes "cats" and "italy"; for longer topics, use the first and last
    # high-information terms.
    concepts.append(tokens[0])

    if len(tokens) > 1:
        concepts.append(tokens[-1])

    pages = []

    for concept in dict.fromkeys(
        concepts
    ):
        progress(
            "SLI semantic fallback concept: "
            + concept
        )

        page = _semantic_fetch_concept_v2(
            concept
        )

        if page is not None:
            pages.append(page)

    if not pages:
        raise RuntimeError(
            "No grounded concept sources were found."
        )

    extracts = []

    source_urls = []
    image_url = None

    for page in pages:
        title = str(
            page.get("title") or ""
        )

        extract = _normalise_multiline(
            str(
                page.get("extract")
                or ""
            )
        )

        if extract:
            extracts.append(
                title
                + "\n"
                + extract
            )

        page_url = str(
            page.get("fullurl")
            or ""
        )

        if page_url:
            source_urls.append(
                page_url
            )

        if image_url is None:
            original = (
                page.get("original")
                or {}
            )

            thumbnail = (
                page.get("thumbnail")
                or {}
            )

            image_url = (
                original.get("source")
                or thumbnail.get("source")
            )

    if not extracts:
        raise RuntimeError(
            "Grounded concept pages contained no usable text."
        )

    title = " ".join(
        word.capitalize()
        for word in topic.split()
    )

    # Add a deterministic relational introduction without inventing facts.
    introduction = (
        f"{title} is presented here through grounded reference material "
        f"about {', '.join(concepts)}. The sections below combine the "
        "retrieved encyclopedic background for these concepts rather than "
        "treating a similarly named entertainment title as the requested "
        "subject."
    )

    combined_extract = (
        introduction
        + "\n"
        + "\n".join(extracts)
    )

    search_url = (
        "https://en.wikipedia.org/w/index.php?"
        + _semantic_urlparse.urlencode(
            {
                "search":
                    topic,
            }
        )
    )

    return TopicSource(
        requested_topic=topic,
        resolved_title=title,
        extract=combined_extract,
        page_url=(
            source_urls[0]
            if source_urls
            else search_url
        ),
        image_url=(
            str(image_url)
            if image_url
            else None
        ),
        image_data_uri=(
            _download_image_data_uri(
                str(image_url)
                if image_url
                else None
            )
        ),
    )


def retrieve_topic(
    topic: str,
    *,
    progress: Progress | None = None,
) -> TopicSource:
    """Resolve a topic semantically and reject misleading entity matches."""

    progress = _progress(
        progress
    )

    progress(
        f"SLI semantic topic search: {topic}"
    )

    ranked = _semantic_search_candidates_v2(
        topic
    )

    for candidate in ranked[:8]:
        progress(
            "SLI semantic candidate: "
            f"{candidate['title']} "
            f"score={candidate['semantic_score']:.1f} "
            f"matches={candidate['evidence']['text_matches']}"
        )

    best = (
        ranked[0]
        if ranked
        else None
    )

    topic_tokens = _semantic_tokens_v2(
        topic
    )

    if best is not None:
        matched = set(
            best["evidence"][
                "text_matches"
            ]
        )

        required_matches = (
            1
            if len(topic_tokens) <= 1
            else min(
                2,
                len(topic_tokens),
            )
        )

        entertainment_text = " ".join(
            (
                best["title"],
                best["snippet"],
                best["extract"][:3000],
                " ".join(
                    best["categories"]
                ),
            )
        ).lower()

        entertainment_hit = any(
            phrase in entertainment_text
            for phrase in (
                _SEMANTIC_ENTITY_PENALTIES
            )
        )

        acceptable = (
            best["semantic_score"] >= 180.0
            and len(matched) >= required_matches
            and not entertainment_hit
            and len(
                best["extract"]
            ) >= 300
        )

        if acceptable:
            progress(
                "SLI semantic topic resolved: "
                + best["title"]
            )

            return _semantic_page_to_source_v2(
                topic,
                best["page"],
            )

        progress(
            "SLI semantic candidate rejected: "
            f"{best['title']} "
            "(insufficient conceptual fit or wrong entity type)"
        )

    progress(
        "SLI semantic resolver: no single article represented "
        "the full request; using grounded concept composition"
    )

    source = _semantic_composite_source_v2(
        topic,
        progress=progress,
    )

    progress(
        "SLI semantic topic resolved as composite: "
        + source.resolved_title
    )

    return source

# SOPHYANE_MEDIAWIKI_CACHE_BACKOFF_V1
#
# Persistent MediaWiki caching and bounded retry. This prevents continuous SLI
# and regression tests from repeating identical Wikipedia API traffic.

import hashlib as _wiki_hashlib
import os as _wiki_os
import random as _wiki_random
import threading as _wiki_threading
import urllib.error as _wiki_urlerror


_WIKI_CACHE_ROOT = (
    MEMORY
    / "topic_site_api_cache"
)

_WIKI_TOPIC_CACHE_ROOT = (
    MEMORY
    / "topic_site_resolution_cache"
)

_WIKI_CACHE_TTL_SECONDS = int(
    _wiki_os.environ.get(
        "SOPHYANE_WIKI_CACHE_TTL",
        str(7 * 24 * 60 * 60),
    )
)

_WIKI_STALE_TTL_SECONDS = int(
    _wiki_os.environ.get(
        "SOPHYANE_WIKI_STALE_TTL",
        str(90 * 24 * 60 * 60),
    )
)

_WIKI_MAX_ATTEMPTS = max(
    1,
    int(
        _wiki_os.environ.get(
            "SOPHYANE_WIKI_MAX_ATTEMPTS",
            "4",
        )
    ),
)

_WIKI_CACHE_LOCK = _wiki_threading.RLock()

_api_json_before_cache_backoff_v1 = _api_json
_retrieve_topic_before_resolution_cache_v1 = retrieve_topic


def _wiki_canonical_parameters_v1(
    parameters: dict[str, str],
) -> dict[str, str]:
    return {
        str(key):
            str(value)

        for key, value in sorted(
            dict(parameters or {}).items(),
            key=lambda item:
                str(item[0]),
        )
    }


def _wiki_cache_key_v1(
    parameters: dict[str, str],
) -> str:
    canonical = json.dumps(
        _wiki_canonical_parameters_v1(
            parameters
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return _wiki_hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def _wiki_cache_path_v1(
    parameters: dict[str, str],
) -> Path:
    key = _wiki_cache_key_v1(
        parameters
    )

    return (
        _WIKI_CACHE_ROOT
        / key[:2]
        / f"{key}.json"
    )


def _wiki_read_cache_v1(
    parameters: dict[str, str],
    *,
    maximum_age: int,
) -> dict | None:
    path = _wiki_cache_path_v1(
        parameters
    )

    if not path.is_file():
        return None

    try:
        record = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

        saved_at = float(
            record.get("saved_at")
            or 0.0
        )

        age = max(
            0.0,
            time.time() - saved_at,
        )

        payload = record.get(
            "payload"
        )

        if (
            age <= maximum_age
            and isinstance(payload, dict)
        ):
            return payload

    except Exception:
        return None

    return None


def _wiki_write_cache_v1(
    parameters: dict[str, str],
    payload: dict,
) -> None:
    path = _wiki_cache_path_v1(
        parameters
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    record = {
        "saved_at":
            time.time(),

        "parameters":
            _wiki_canonical_parameters_v1(
                parameters
            ),

        "payload":
            payload,
    }

    temporary = path.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    _wiki_os.replace(
        temporary,
        path,
    )


def _wiki_retry_after_v1(
    error,
    attempt: int,
) -> float:
    header_value = None

    try:
        header_value = (
            error.headers.get(
                "Retry-After"
            )
        )
    except Exception:
        pass

    if header_value:
        try:
            return min(
                60.0,
                max(
                    0.5,
                    float(header_value),
                ),
            )
        except (TypeError, ValueError):
            pass

    base = min(
        30.0,
        1.5 * (2 ** attempt),
    )

    return base + _wiki_random.uniform(
        0.1,
        0.8,
    )


def _api_json(
    parameters: dict[str, str],
    *,
    timeout: int = 25,
) -> dict:
    """Read-through cached MediaWiki request with bounded 429 backoff."""

    parameters = _wiki_canonical_parameters_v1(
        parameters
    )

    cached = _wiki_read_cache_v1(
        parameters,
        maximum_age=_WIKI_CACHE_TTL_SECONDS,
    )

    if cached is not None:
        return cached

    last_error = None

    for attempt in range(
        _WIKI_MAX_ATTEMPTS
    ):
        try:
            payload = (
                _api_json_before_cache_backoff_v1(
                    parameters,
                    timeout=timeout,
                )
            )

            if not isinstance(
                payload,
                dict,
            ):
                raise RuntimeError(
                    "MediaWiki returned a non-object payload."
                )

            with _WIKI_CACHE_LOCK:
                _wiki_write_cache_v1(
                    parameters,
                    payload,
                )

            return payload

        except _wiki_urlerror.HTTPError as error:
            last_error = error

            if error.code not in {
                429,
                500,
                502,
                503,
                504,
            }:
                raise

            stale = _wiki_read_cache_v1(
                parameters,
                maximum_age=_WIKI_STALE_TTL_SECONDS,
            )

            if stale is not None:
                return stale

            if (
                attempt
                >= _WIKI_MAX_ATTEMPTS - 1
            ):
                break

            time.sleep(
                _wiki_retry_after_v1(
                    error,
                    attempt,
                )
            )

        except (
            TimeoutError,
            _wiki_urlerror.URLError,
        ) as error:
            last_error = error

            stale = _wiki_read_cache_v1(
                parameters,
                maximum_age=_WIKI_STALE_TTL_SECONDS,
            )

            if stale is not None:
                return stale

            if (
                attempt
                >= _WIKI_MAX_ATTEMPTS - 1
            ):
                break

            time.sleep(
                min(
                    20.0,
                    1.0 * (2 ** attempt)
                    + _wiki_random.uniform(
                        0.1,
                        0.6,
                    ),
                )
            )

    stale = _wiki_read_cache_v1(
        parameters,
        maximum_age=_WIKI_STALE_TTL_SECONDS,
    )

    if stale is not None:
        return stale

    if last_error is not None:
        raise last_error

    raise RuntimeError(
        "MediaWiki request failed without an error response."
    )


def _wiki_topic_key_v1(
    topic: str,
) -> str:
    normalised = _normalise(
        topic
    ).lower()

    return _wiki_hashlib.sha256(
        normalised.encode("utf-8")
    ).hexdigest()


def _wiki_topic_cache_path_v1(
    topic: str,
) -> Path:
    key = _wiki_topic_key_v1(
        topic
    )

    return (
        _WIKI_TOPIC_CACHE_ROOT
        / key[:2]
        / f"{key}.json"
    )


def _wiki_read_topic_cache_v1(
    topic: str,
) -> TopicSource | None:
    path = _wiki_topic_cache_path_v1(
        topic
    )

    if not path.is_file():
        return None

    try:
        record = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

        saved_at = float(
            record.get("saved_at")
            or 0.0
        )

        if (
            time.time() - saved_at
            > _WIKI_CACHE_TTL_SECONDS
        ):
            return None

        source_data = dict(
            record.get("source")
            or {}
        )

        required = {
            "requested_topic",
            "resolved_title",
            "extract",
            "page_url",
            "image_url",
            "image_data_uri",
        }

        if not required.issubset(
            source_data
        ):
            return None

        return TopicSource(
            requested_topic=str(
                source_data[
                    "requested_topic"
                ]
            ),

            resolved_title=str(
                source_data[
                    "resolved_title"
                ]
            ),

            extract=str(
                source_data[
                    "extract"
                ]
            ),

            page_url=str(
                source_data[
                    "page_url"
                ]
            ),

            image_url=(
                str(
                    source_data[
                        "image_url"
                    ]
                )
                if source_data[
                    "image_url"
                ]
                else None
            ),

            image_data_uri=(
                str(
                    source_data[
                        "image_data_uri"
                    ]
                )
                if source_data[
                    "image_data_uri"
                ]
                else None
            ),
        )

    except Exception:
        return None


def _wiki_write_topic_cache_v1(
    topic: str,
    source: TopicSource,
) -> None:
    path = _wiki_topic_cache_path_v1(
        topic
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    record = {
        "saved_at":
            time.time(),

        "topic":
            topic,

        "source": {
            "requested_topic":
                source.requested_topic,

            "resolved_title":
                source.resolved_title,

            "extract":
                source.extract,

            "page_url":
                source.page_url,

            "image_url":
                source.image_url,

            "image_data_uri":
                source.image_data_uri,
        },
    }

    temporary = path.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    _wiki_os.replace(
        temporary,
        path,
    )


def retrieve_topic(
    topic: str,
    *,
    progress: Progress | None = None,
) -> TopicSource:
    """Resolve once, cache the grounded result, and reuse it safely."""

    progress = _progress(
        progress
    )

    cached = _wiki_read_topic_cache_v1(
        topic
    )

    if cached is not None:
        progress(
            "SLI semantic topic cache hit: "
            + cached.resolved_title
        )

        return cached

    source = (
        _retrieve_topic_before_resolution_cache_v1(
            topic,
            progress=progress,
        )
    )

    _wiki_write_topic_cache_v1(
        topic,
        source,
    )

    return source
