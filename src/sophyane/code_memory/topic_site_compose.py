"""Rich internet-grounded informational website composition for SLI Option 1.

The route remains deterministic and LLM-free. It combines MediaWiki facts with
verified local photography, adaptive visual themes, responsive components,
motion, filtering, reading progress, source provenance and strict validation.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import mimetypes
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
MEMORY = Path.home() / ".local/share/sophyane/code_memory"
EVENTS = MEMORY / "topic_site_events.jsonl"
MAX_IMAGE_BYTES = 4_000_000
MAX_IMAGES = 4


@dataclass
class TopicSource:
    requested_topic: str
    resolved_title: str
    extract: str
    page_url: str
    image_url: str | None = None
    image_data_uri: str | None = None
    images: list[tuple[str, str, str]] = field(default_factory=list)


def _p(progress: Progress | None) -> Progress:
    return progress or (lambda _message: None)


def _normalise(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalise_multiline(value: str) -> str:
    return "\n".join(line for raw in str(value or "").splitlines() if (line := _normalise(raw)))


def extract_topic(request: str) -> str:
    value = _normalise(request)
    for pattern in (
        r"\bwebsite\s+(?:on|about|for)\s+(.+)$",
        r"\bwebpage\s+(?:on|about|for)\s+(.+)$",
        r"\bsite\s+(?:on|about|for)\s+(.+)$",
        r"\binformational\s+(?:website|webpage|site)\s+(?:on|about)\s+(.+)$",
    ):
        match = re.search(pattern, value, flags=re.I)
        if match:
            topic = re.sub(
                r"\b(?:in\s+one\s+self[- ]contained\s+index\.html)\b.*$",
                "",
                match.group(1),
                flags=re.I,
            )
            return _normalise(topic).strip(" .,:;-")
    cleaned = re.sub(
        r"^(?:please\s+)?(?:make|create|build|design|generate|develop)\s+",
        "",
        value,
        flags=re.I,
    )
    cleaned = re.sub(r"\b(?:a|an|the)\s+", "", cleaned, count=1, flags=re.I)
    cleaned = re.sub(r"\b(?:website|webpage|site)\b", "", cleaned, count=1, flags=re.I)
    cleaned = re.sub(r"^(?:on|about|for)\s+", "", cleaned, flags=re.I)
    return _normalise(cleaned).strip(" .,:;-")


def is_topic_site_request(request: str) -> bool:
    value = _normalise(request).lower()
    has_build = any(term in value for term in ("make", "create", "build", "design", "generate", "develop"))
    has_site = any(term in value for term in ("website", "webpage", "informational site", "information site"))
    interactive = ("game", "calculator", "dashboard", "editor", "quiz", "simulation", "visualizer", "todo", "kanban")
    return has_build and has_site and not any(x in value for x in interactive) and bool(extract_topic(request))


def _api_json(base: str, parameters: dict[str, str], timeout: int = 25) -> dict:
    query = urllib.parse.urlencode({**parameters, "format": "json", "formatversion": "2", "origin": "*"})
    request = urllib.request.Request(
        base + "?" + query,
        headers={"User-Agent": "Sophyane-SLI-Rich-Topic-Site/2.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _search_title(topic: str) -> str:
    payload = _api_json(WIKIPEDIA_API, {
        "action": "query", "list": "search", "srsearch": topic, "srnamespace": "0", "srlimit": "5",
    })
    results = payload.get("query", {}).get("search", [])
    if not results:
        raise RuntimeError(f"No encyclopedic source was found for: {topic}")
    wanted = set(re.findall(r"[a-z0-9]+", topic.lower()))
    return str(max(results, key=lambda item: (
        str(item.get("title", "")).lower() == topic.lower(),
        len(wanted & set(re.findall(r"[a-z0-9]+", str(item.get("title", "")).lower()))),
    ))["title"])


def _download_data_uri(url: str | None) -> str | None:
    if not url or not url.startswith("https://"):
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Sophyane-SLI-Rich-Topic-Site/2.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            declared = int(response.headers.get("Content-Length", "0") or 0)
            if declared > MAX_IMAGE_BYTES:
                return None
            body = response.read(MAX_IMAGE_BYTES + 1)
            if len(body) < 8_000 or len(body) > MAX_IMAGE_BYTES:
                return None
            kind = response.headers.get_content_type() or mimetypes.guess_type(url)[0] or "image/jpeg"
            if not kind.startswith("image/"):
                return None
        return f"data:{kind};base64,{base64.b64encode(body).decode('ascii')}"
    except Exception:
        return None


def _commons_images(topic: str, limit: int = 10) -> list[tuple[str, str]]:
    payload = _api_json(COMMONS_API, {
        "action": "query", "generator": "search", "gsrsearch": f"{topic} filetype:bitmap",
        "gsrnamespace": "6", "gsrlimit": str(limit), "prop": "imageinfo",
        "iiprop": "url|mime", "iiurlwidth": "1600",
    })
    found: list[tuple[str, str]] = []
    for page in payload.get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [{}])[0]
        mime = str(info.get("mime") or "")
        url = str(info.get("thumburl") or info.get("url") or "")
        if url.startswith("https://") and mime in {"image/jpeg", "image/png", "image/webp"}:
            found.append((str(page.get("title") or topic).removeprefix("File:"), url))
    return found


def retrieve_topic(topic: str, *, progress: Progress | None = None) -> TopicSource:
    progress = _p(progress)
    progress(f"SLI topic search: {topic}")
    title = _search_title(topic)
    progress(f"SLI topic resolved: {title}")
    payload = _api_json(WIKIPEDIA_API, {
        "action": "query", "prop": "extracts|pageimages|info", "titles": title,
        "explaintext": "1", "exsectionformat": "plain", "exlimit": "1",
        "piprop": "original|thumbnail", "pithumbsize": "1600", "inprop": "url",
    })
    pages = payload.get("query", {}).get("pages", [])
    if not pages:
        raise RuntimeError(f"No source page was returned for: {title}")
    page = pages[0]
    extract = _normalise_multiline(str(page.get("extract") or ""))
    if len(extract) < 300:
        raise RuntimeError("The retrieved source did not contain enough factual text.")
    # Both URLs come directly from the resolved Wikipedia page and
    # therefore carry the same primary-subject identity provenance.
    #
    # Prefer Wikipedia's requested display thumbnail: the original can
    # be several megabytes and intentionally exceeds Sophyane's bounded
    # embedded-image budget.  Fall back to the original only when no
    # thumbnail is supplied.
    primary_url = str(
        (page.get("thumbnail") or {}).get("source")
        or (page.get("original") or {}).get("source")
        or ""
    )
    resolved_title = str(
        page.get("title")
        or title
    )

    # The Wikipedia page image is identity-bound to the resolved
    # primary entity.  It is the only photograph permitted to become
    # the subject hero.  Commons search results are supplementary
    # gallery material and must never silently replace it.
    primary_data = (
        _download_data_uri(
            primary_url
        )
        if primary_url
        else None
    )

    images: list[
        tuple[str, str, str]
    ] = []

    seen: set[str] = set()

    if (
        primary_url
        and primary_data
    ):
        images.append(
            (
                resolved_title,
                primary_url,
                primary_data,
            )
        )

        seen.add(
            primary_url
        )

        progress(
            "SLI verified primary photograph: "
            f"{resolved_title[:60]}"
        )

    try:
        commons_candidates = (
            _commons_images(
                topic
            )
        )
    except Exception as error:
        commons_candidates = []

        progress(
            "SLI premium photography unavailable: "
            f"{type(error).__name__}"
        )

    for label, url in commons_candidates:
        if (
            len(images) >= MAX_IMAGES
            or url in seen
        ):
            continue

        seen.add(
            url
        )

        data = _download_data_uri(
            url
        )

        if data:
            images.append(
                (
                    label,
                    url,
                    data,
                )
            )

            progress(
                "SLI supplementary photograph "
                f"{len(images)}/{MAX_IMAGES}: "
                f"{label[:60]}"
            )

    return TopicSource(
        requested_topic=topic,
        resolved_title=resolved_title,
        extract=extract,
        page_url=str(
            page.get("fullurl")
            or ""
        ),
        image_url=(
            primary_url
            or None
        ),
        image_data_uri=(
            primary_data
        ),
        images=images,
    )


def _paragraphs(extract: str) -> list[str]:
    blocks = [_normalise(x) for x in re.split(r"\n+", extract)]
    output = [re.sub(r"^=+\s*(.*?)\s*=+$", r"\1", x) for x in blocks if len(x) >= 80]
    if len(output) < 3:
        sentences = re.split(r"(?<=[.!?])\s+", _normalise(extract))
        output, current = [], []
        for sentence in sentences:
            current.append(sentence)
            if len(" ".join(current)) >= 280:
                output.append(" ".join(current)); current = []
        if current:
            output.append(" ".join(current))
    return output[:18]


def _theme(topic: str) -> tuple[str, str, str, str]:
    themes = (
        ("#f4b942", "#ef8354", "#09111f", "#121f33"),
        ("#66e3c4", "#4aa8ff", "#071a22", "#102d38"),
        ("#d8a7ff", "#ff7eb6", "#160c24", "#29163f"),
        ("#a8e063", "#56ab2f", "#101b11", "#203421"),
        ("#ffd166", "#06d6a0", "#101820", "#1d2d3a"),
    )
    return themes[int(hashlib.sha256(topic.encode()).hexdigest()[:8], 16) % len(themes)]


def compose_document(source: TopicSource) -> str:
    paragraphs = _paragraphs(source.extract)
    if not paragraphs:
        raise RuntimeError("No usable paragraphs were retrieved.")
    title = html.escape(source.resolved_title)
    topic = html.escape(source.requested_topic)
    accent, accent2, bg, panel = _theme(source.requested_topic)
    headings = ("Overview", "Origins & context", "Key dimensions", "People & culture", "Impact & significance", "Explore further")
    remaining = paragraphs[1:] or paragraphs
    cards: list[str] = []
    for index, body in enumerate(remaining[:6]):
        cards.append(
            f'<article class="story-card reveal" data-search="{html.escape((headings[index % len(headings)] + " " + body).lower(), quote=True)}">'
            f'<span class="eyebrow">0{index + 1}</span><h2>{headings[index % len(headings)]}</h2><p>{html.escape(body)}</p></article>'
        )
    gallery = "".join(
        f'<figure class="gallery-item reveal"><img loading="lazy" src="{data}" alt="{html.escape(label, quote=True)}">'
        f'<figcaption>{html.escape(label)}</figcaption></figure>'
        for label, _url, data in source.images
    )
    hero_image = source.images[0][2] if source.images else ""
    hero_media = (
        f'<div class="hero-media"><img src="{hero_image}" alt="{title}"><div class="image-shade"></div></div>'
        if hero_image else '<div class="hero-media abstract" aria-hidden="true"><i></i><i></i><i></i></div>'
    )
    source_url = html.escape(source.page_url or "#", quote=True)
    intro = html.escape(paragraphs[0])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="A verified, internet-grounded visual guide to {topic}."><title>{title} — Sophyane SLI</title>
<style>
:root{{--accent:{accent};--accent2:{accent2};--bg:{bg};--panel:{panel};--ink:#f7f8fb;--muted:#b7c2d0;--max:1180px}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:radial-gradient(circle at 80% 10%,color-mix(in srgb,var(--accent) 15%,transparent),transparent 35%),var(--bg);color:var(--ink);font:16px/1.7 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;overflow-x:hidden}}a{{color:inherit}}button,input{{font:inherit}}.progress{{position:fixed;inset:0 auto auto 0;height:3px;width:0;background:linear-gradient(90deg,var(--accent),var(--accent2));z-index:100}}
.nav{{position:sticky;top:0;z-index:50;display:flex;justify-content:space-between;align-items:center;width:min(var(--max),calc(100% - 32px));margin:auto;padding:16px 0;background:color-mix(in srgb,var(--bg) 75%,transparent);backdrop-filter:blur(18px)}}.brand{{font-weight:900;letter-spacing:.08em;text-transform:uppercase;text-decoration:none}}.brand b{{color:var(--accent)}}.nav-links{{display:flex;gap:22px;font-size:.9rem}}.nav-links a{{text-decoration:none;color:var(--muted)}}
.hero{{position:relative;min-height:82vh;display:grid;align-items:end;width:min(var(--max),calc(100% - 32px));margin:auto;padding:70px 0 56px}}.hero-media{{position:absolute;inset:20px 0 20px 34%;overflow:hidden;border-radius:36px;box-shadow:0 30px 90px #0008}}.hero-media img{{width:100%;height:100%;object-fit:cover;animation:slowZoom 18s ease-in-out infinite alternate}}.image-shade{{position:absolute;inset:0;background:linear-gradient(90deg,var(--bg) 0%,transparent 50%),linear-gradient(0deg,var(--bg),transparent 55%)}}.hero-copy{{position:relative;z-index:2;max-width:720px}}.kicker,.eyebrow{{color:var(--accent);text-transform:uppercase;letter-spacing:.18em;font-weight:800;font-size:.75rem}}h1{{font-size:clamp(3.3rem,9vw,8rem);line-height:.86;letter-spacing:-.07em;margin:.18em 0}}.lead{{max-width:680px;color:#e4e9ef;font-size:clamp(1rem,2vw,1.25rem)}}.actions{{display:flex;flex-wrap:wrap;gap:12px;margin-top:28px}}.button{{display:inline-flex;align-items:center;gap:8px;padding:13px 18px;border:1px solid #ffffff2b;border-radius:999px;text-decoration:none;background:#ffffff10;backdrop-filter:blur(10px)}}.button.primary{{background:var(--accent);color:#101318;border-color:transparent;font-weight:800}}
main{{width:min(var(--max),calc(100% - 32px));margin:auto}}.toolbar{{display:flex;gap:12px;align-items:center;margin:28px 0 22px;padding:12px 14px;border:1px solid #ffffff18;border-radius:18px;background:#ffffff08}}.toolbar input{{width:100%;border:0;outline:0;background:transparent;color:white}}.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:18px}}.story-card{{grid-column:span 6;min-height:330px;padding:34px;border:1px solid #ffffff18;border-radius:28px;background:linear-gradient(145deg,#ffffff0d,#ffffff05);box-shadow:inset 0 1px #ffffff16;transition:.35s transform,.35s border-color}}.story-card:hover{{transform:translateY(-7px);border-color:color-mix(in srgb,var(--accent) 55%,transparent)}}.story-card:nth-child(3n){{grid-column:span 12;min-height:250px}}.story-card h2{{font-size:clamp(1.5rem,3vw,2.4rem);line-height:1.05;margin:.55em 0}}.story-card p{{color:var(--muted)}}
.section-head{{display:flex;justify-content:space-between;align-items:end;gap:24px;margin:110px 0 24px}}.section-head h2{{font-size:clamp(2.3rem,5vw,5rem);line-height:.95;margin:0}}.gallery{{display:grid;grid-template-columns:repeat(12,1fr);grid-auto-rows:220px;gap:16px}}.gallery-item{{position:relative;grid-column:span 6;margin:0;overflow:hidden;border-radius:26px}}.gallery-item:first-child{{grid-column:span 7;grid-row:span 2}}.gallery-item:nth-child(2){{grid-column:span 5}}.gallery-item img{{width:100%;height:100%;object-fit:cover;transition:.6s transform}}.gallery-item:hover img{{transform:scale(1.05)}}.gallery-item figcaption{{position:absolute;inset:auto 14px 14px;padding:8px 12px;border-radius:12px;background:#07111dcc;backdrop-filter:blur(12px);font-size:.8rem}}
.source-panel{{margin:90px 0;padding:32px;border-radius:28px;background:linear-gradient(120deg,color-mix(in srgb,var(--accent) 18%,var(--panel)),var(--panel));border:1px solid #ffffff1b}}footer{{width:min(var(--max),calc(100% - 32px));margin:70px auto 0;padding:30px 0 50px;border-top:1px solid #ffffff1a;color:var(--muted);display:flex;justify-content:space-between;gap:20px}}.reveal{{opacity:0;transform:translateY(22px);transition:.7s opacity,.7s transform}}.reveal.visible{{opacity:1;transform:none}}.abstract{{background:linear-gradient(135deg,var(--panel),var(--accent2))}}.abstract i{{position:absolute;border-radius:50%;filter:blur(2px);background:var(--accent);animation:float 7s ease-in-out infinite}}.abstract i:nth-child(1){{width:42%;aspect-ratio:1;left:10%;top:12%}}.abstract i:nth-child(2){{width:30%;aspect-ratio:1;right:10%;bottom:8%;animation-delay:-2s}}.abstract i:nth-child(3){{width:15%;aspect-ratio:1;right:22%;top:14%;animation-delay:-4s}}@keyframes slowZoom{{to{{transform:scale(1.08)}}}}@keyframes float{{50%{{transform:translateY(-18px) rotate(8deg)}}}}
@media(max-width:760px){{.nav-links{{display:none}}.hero{{min-height:78vh;padding-top:40px}}.hero-media{{inset:20px 0 100px 12%;opacity:.72}}h1{{font-size:clamp(3.2rem,18vw,5.8rem)}}.story-card,.story-card:nth-child(3n){{grid-column:span 12;min-height:auto}}.gallery{{grid-auto-rows:190px}}.gallery-item,.gallery-item:first-child,.gallery-item:nth-child(2){{grid-column:span 12;grid-row:span 1}}.section-head,footer{{align-items:flex-start;flex-direction:column}}}}
@media(prefers-reduced-motion:reduce){{*,*::before,*::after{{animation:none!important;transition:none!important;scroll-behavior:auto!important}}.reveal{{opacity:1;transform:none}}}}
</style></head><body><div class="progress" id="progress"></div>
<nav class="nav"><a class="brand" href="#top">Sophyane <b>SLI</b></a><div class="nav-links"><a href="#stories">Stories</a><a href="#gallery">Gallery</a><a href="#source">Source</a></div></nav>
<header class="hero" id="top">{hero_media}<div class="hero-copy"><div class="kicker">Grounded visual intelligence</div><h1>{title}</h1><p class="lead">{intro}</p><div class="actions"><a class="button primary" href="#stories">Explore the story ↓</a><a class="button" href="{source_url}" target="_blank" rel="noopener">Verify source ↗</a></div></div></header>
<main><section id="stories"><div class="section-head reveal"><div><span class="kicker">Curated knowledge</span><h2>A richer way to explore.</h2></div><p>Search the grounded sections below.</p></div><label class="toolbar"><span>⌕</span><input id="search" type="search" placeholder="Search this guide…" aria-label="Search this guide"></label><div class="grid" id="cards">{''.join(cards)}</div></section>
<section id="gallery"><div class="section-head reveal"><div><span class="kicker">Verified photography</span><h2>Visual perspective.</h2></div><p>{len(source.images)} locally embedded image(s), with no fragile hotlinks.</p></div><div class="gallery">{gallery or '<div class="source-panel reveal">Photography was unavailable, so Sophyane preserved a complete abstract visual experience.</div>'}</div></section>
<section class="source-panel reveal" id="source"><span class="kicker">Provenance</span><h2>Grounded, not invented.</h2><p>This Option 1 website was assembled without a local or cloud LLM. Facts came from the resolved encyclopedia source and images were downloaded, verified, and embedded into this single HTML artifact.</p><a class="button" href="{source_url}" target="_blank" rel="noopener">Open {title} source ↗</a></section></main>
<footer><strong>{title}</strong><span>Generated by Sophyane SLI Graph · deterministic rich-site pipeline</span></footer>
<script>
const bar=document.getElementById('progress');addEventListener('scroll',()=>{{const h=document.documentElement;bar.style.width=((h.scrollTop/(h.scrollHeight-h.clientHeight))*100)+'%'}});
const observer=new IntersectionObserver(entries=>entries.forEach(e=>{{if(e.isIntersecting)e.target.classList.add('visible')}}),{{threshold:.12}});document.querySelectorAll('.reveal').forEach(x=>observer.observe(x));
const search=document.getElementById('search');search.addEventListener('input',()=>{{const q=search.value.toLowerCase().trim();document.querySelectorAll('.story-card').forEach(card=>card.hidden=q&&!card.dataset.search.includes(q))}});
</script></body></html>'''


def _validate_document(document: str, source: TopicSource) -> None:
    lower = document.lower()
    problems: list[str] = []
    if len(document) < 5_000:
        problems.append("HTML is too small for the rich-site contract")
    for marker in ("<!doctype html", "</html>", "<style>", "<script>", "prefers-reduced-motion", "id=\"stories\""):
        if marker not in lower:
            problems.append(f"missing {marker}")
    if source.resolved_title.lower() not in lower:
        problems.append("resolved topic is absent")
    if source.images and sum(data[:40].lower() in lower for _label, _url, data in source.images) < min(3, len(source.images)):
        problems.append("verified photography manifest was not used")
    if problems:
        raise RuntimeError("; ".join(problems))


def _record_event(request: str, source: TopicSource, workspace: Path, document: str) -> None:
    try:
        MEMORY.mkdir(parents=True, exist_ok=True)
        event = {
            "time": time.time(), "request": request, "topic": source.requested_topic,
            "resolved_title": source.resolved_title, "source_url": source.page_url,
            "image_urls": [url for _label, url, _data in source.images],
            "artifact": str(workspace / "index.html"), "bytes": len(document.encode("utf-8")),
            "pipeline": "sli-rich-topic-v2", "llm_used": False,
        }
        with EVENTS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def compose_topic_site(request: str, workspace: Path | str, *, progress: Progress | None = None) -> str:
    progress = _p(progress)
    target = Path(workspace)
    target.mkdir(parents=True, exist_ok=True)
    topic = extract_topic(request)
    if not topic:
        return "Success: False\nNo topic could be extracted.\nNo LLM was used.\n"
    try:
        source = retrieve_topic(topic, progress=progress)
        progress("SLI rich-site composition: cinematic responsive layout")
        document = compose_document(source)
        _validate_document(document, source)
        artifact = target / "index.html"
        artifact.write_text(document, encoding="utf-8")
        _record_event(request, source, target, document)
        progress(f"SLI rich-site artifact written: {artifact}")
        return (
            "Success: True\n"
            f"Artifact: {artifact}\n"
            f"Topic: {source.resolved_title}\n"
            f"Verified images: {len(source.images)}\n"
            "Design: adaptive cinematic theme, responsive cards, gallery, search, motion and provenance\n"
            "LLM used: False\n"
        )
    except Exception as error:
        progress(f"SLI rich-site failure: {error}")
        return f"Success: False\nTopic site generation failed: {error}\nNo LLM was used.\n"


handle_topic_site = compose_topic_site
