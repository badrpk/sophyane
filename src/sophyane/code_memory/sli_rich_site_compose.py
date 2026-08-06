"""Rich deterministic website orchestration for Sophyane Option 1.

This module deliberately uses no LLM. It capitalises on Sophyane's existing
internet-grounded topic retrieval, local artifact workflow and promotion path,
while adding multi-entity acquisition and application-grade UI composition.
"""
from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sophyane.code_memory.topic_site_compose import (
    TopicSource,
    extract_topic,
    is_topic_site_request,
    retrieve_topic,
)

Progress = Callable[[str], None]
API = "https://en.wikipedia.org/w/api.php"
MAX_IMAGE_BYTES = 2_500_000


@dataclass
class Entity:
    title: str
    extract: str
    url: str
    image: str | None
    category: str


def _api(params: dict[str, str], timeout: int = 20) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2", "origin": "*"})
    request = urllib.request.Request(
        API + "?" + query,
        headers={"User-Agent": "Sophyane-SLI-Rich-Site/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _data_uri(url: str | None) -> str | None:
    if not url:
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Sophyane-SLI-Rich-Site/1.0"})
        with urllib.request.urlopen(request, timeout=18) as response:
            body = response.read(MAX_IMAGE_BYTES + 1)
            if not body or len(body) > MAX_IMAGE_BYTES:
                return None
            content_type = response.headers.get_content_type() or mimetypes.guess_type(url)[0] or "image/jpeg"
        return f"data:{content_type};base64,{base64.b64encode(body).decode('ascii')}"
    except Exception:
        return None


def _sentences(text: str, limit: int = 3) -> str:
    clean = " ".join(str(text or "").split())
    parts = re.split(r"(?<=[.!?])\s+", clean)
    return " ".join(parts[:limit]).strip()


def _category(title: str, extract: str) -> str:
    text = f"{title} {extract}".lower()
    groups = (
        ("Television", ("television", "drama", "serial", "tv actor", "tv actress")),
        ("Film", ("film", "cinema", "movie", "filmmaker")),
        ("Music", ("singer", "musician", "composer", "music")),
        ("Culture", ("culture", "heritage", "writer", "artist")),
    )
    for label, keys in groups:
        if any(key in text for key in keys):
            return label
    return "Featured"


def _related_entities(topic: str, resolved_title: str, progress: Progress, limit: int = 9) -> list[Entity]:
    progress(f"SLI rich-site: discovering related entities for {topic}")
    payload = _api({
        "action": "query", "list": "search", "srsearch": topic,
        "srnamespace": "0", "srlimit": str(max(limit + 5, 14)),
    })
    titles = []
    for row in payload.get("query", {}).get("search", []):
        title = str(row.get("title") or "").strip()
        if title and title.lower() != resolved_title.lower() and title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    if not titles:
        return []

    detail = _api({
        "action": "query",
        "prop": "extracts|pageimages|info",
        "titles": "|".join(titles),
        "exintro": "1", "explaintext": "1", "exsentences": "4",
        "piprop": "thumbnail|original", "pithumbsize": "900", "inprop": "url",
    })
    entities: list[Entity] = []
    for page in detail.get("query", {}).get("pages", []):
        title = str(page.get("title") or "").strip()
        extract = _sentences(str(page.get("extract") or ""), 3)
        if not title or len(extract) < 80:
            continue
        image_info = page.get("thumbnail") or page.get("original") or {}
        image_url = str(image_info.get("source") or "") or None
        entities.append(Entity(
            title=title,
            extract=extract,
            url=str(page.get("fullurl") or ""),
            image=_data_uri(image_url),
            category=_category(title, extract),
        ))
    progress(f"SLI rich-site: acquired {len(entities)} related entities")
    return entities


def _fallback_art(title: str) -> str:
    safe = html.escape(title[:36])
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 600'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        "<stop stop-color='#171b2f'/><stop offset='.5' stop-color='#6b2d5c'/><stop offset='1' stop-color='#d9814f'/></linearGradient>"
        "<filter id='b'><feGaussianBlur stdDeviation='28'/></filter></defs>"
        "<rect width='900' height='600' fill='url(#g)'/><circle cx='690' cy='130' r='150' fill='#fff' opacity='.16' filter='url(#b)'/>"
        "<circle cx='160' cy='500' r='210' fill='#ffce76' opacity='.15' filter='url(#b)'/>"
        f"<text x='450' y='320' text-anchor='middle' font-family='Georgia,serif' font-size='52' fill='white'>{safe}</text></svg>"
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


def _entity_cards(entities: list[Entity]) -> str:
    cards = []
    for index, entity in enumerate(entities):
        image = entity.image or _fallback_art(entity.title)
        cards.append(
            f'''<article class="story-card reveal" data-title="{html.escape(entity.title.lower(), quote=True)}" data-category="{html.escape(entity.category.lower(), quote=True)}" tabindex="0">
              <div class="story-media"><img src="{image}" alt="{html.escape(entity.title, quote=True)}"><span class="story-index">{index + 1:02d}</span></div>
              <div class="story-copy"><span class="pill">{html.escape(entity.category)}</span><h3>{html.escape(entity.title)}</h3>
              <p>{html.escape(entity.extract)}</p><button class="open-story" data-index="{index}">Explore profile <span>↗</span></button></div>
            </article>'''
        )
    return "\n".join(cards)


def _render(source: TopicSource, entities: list[Entity]) -> str:
    topic = html.escape(source.requested_topic)
    title = html.escape(source.resolved_title)
    intro = html.escape(_sentences(source.extract, 4))
    hero_image = source.image_data_uri or (entities[0].image if entities and entities[0].image else _fallback_art(source.resolved_title))
    categories = sorted({entity.category for entity in entities})
    chips = ['<button class="filter-chip active" data-filter="all">All stories</button>'] + [
        f'<button class="filter-chip" data-filter="{html.escape(cat.lower(), quote=True)}">{html.escape(cat)}</button>' for cat in categories
    ]
    data = json.dumps([
        {"title": e.title, "extract": e.extract, "url": e.url, "image": e.image or _fallback_art(e.title), "category": e.category}
        for e in entities
    ]).replace("</", "<\\/")
    source_url = html.escape(source.page_url or "#", quote=True)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="A rich internet-grounded experience about {topic}"><title>{title} — Sophyane Storyworld</title>
<style>
:root{{--bg:#090b12;--surface:#111521;--surface2:#171c2b;--text:#f6f2eb;--muted:#a7adbb;--accent:#ffb45f;--accent2:#e66395;--line:rgba(255,255,255,.1);--max:1240px;--radius:26px}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:radial-gradient(circle at 80% 5%,rgba(230,99,149,.14),transparent 30%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;overflow-x:hidden}}body.light{{--bg:#f3eee8;--surface:#fffaf4;--surface2:#f0e5da;--text:#17131b;--muted:#6d6570;--line:rgba(25,18,28,.12)}}
a{{color:inherit}}button,input{{font:inherit}}.progress{{position:fixed;inset:0 auto auto 0;height:3px;width:0;background:linear-gradient(90deg,var(--accent),var(--accent2));z-index:100}}
.nav{{position:fixed;z-index:50;top:16px;left:50%;transform:translateX(-50%);width:min(var(--max),calc(100% - 28px));display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border:1px solid var(--line);border-radius:18px;background:rgba(9,11,18,.68);backdrop-filter:blur(18px)}}body.light .nav{{background:rgba(255,250,244,.78)}}.brand{{font-weight:900;letter-spacing:.12em;text-transform:uppercase;font-size:.82rem}}.brand b{{color:var(--accent)}}.nav-actions{{display:flex;gap:8px}}.icon-btn{{border:1px solid var(--line);background:transparent;color:inherit;border-radius:12px;padding:9px 12px;cursor:pointer}}
.hero{{min-height:100svh;display:grid;align-items:end;position:relative;isolation:isolate;padding:120px max(24px,calc((100vw - var(--max))/2)) 70px}}.hero:before{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(6,7,13,.95) 0%,rgba(6,7,13,.64) 48%,rgba(6,7,13,.12)),linear-gradient(0deg,var(--bg),transparent 40%);z-index:-1}}.hero img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:-2;filter:saturate(.82)}}.hero-content{{max-width:780px}}.eyebrow{{display:flex;align-items:center;gap:12px;color:var(--accent);font-weight:800;text-transform:uppercase;letter-spacing:.16em;font-size:.78rem}}.eyebrow:before{{content:"";width:44px;height:1px;background:currentColor}}h1{{font-family:Georgia,serif;font-size:clamp(3.3rem,9vw,8.5rem);line-height:.87;margin:22px 0;letter-spacing:-.07em;max-width:950px}}.hero p{{font-size:clamp(1rem,2vw,1.25rem);line-height:1.75;color:#d8d5d6;max-width:690px}}.hero-meta{{display:flex;gap:24px;flex-wrap:wrap;margin-top:34px}}.metric strong{{display:block;font-size:1.5rem}}.metric span{{color:#c5c1c4;font-size:.82rem;text-transform:uppercase;letter-spacing:.1em}}
main{{width:min(var(--max),calc(100% - 32px));margin:auto}}.marquee{{overflow:hidden;border-block:1px solid var(--line);padding:18px 0;margin:0 0 90px;white-space:nowrap}}.marquee-track{{display:inline-flex;gap:40px;animation:marquee 24s linear infinite;color:var(--muted);font-family:Georgia,serif;font-size:1.4rem;font-style:italic}}@keyframes marquee{{to{{transform:translateX(-50%)}}}}
.section-head{{display:grid;grid-template-columns:1fr 1fr;gap:28px;align-items:end;margin-bottom:30px}}.section-head h2{{font-family:Georgia,serif;font-size:clamp(2.3rem,5vw,5rem);line-height:1;margin:0;letter-spacing:-.045em}}.section-head p{{color:var(--muted);line-height:1.8;margin:0}}.controls{{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0 34px}}.search{{flex:1;min-width:230px;background:var(--surface);border:1px solid var(--line);border-radius:16px;color:inherit;padding:14px 18px;outline:none}}.filter-chip{{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:999px;padding:11px 16px;cursor:pointer}}.filter-chip.active{{background:var(--text);color:var(--bg);border-color:var(--text)}}
.story-grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:22px}}.story-card{{grid-column:span 4;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;transition:transform .35s ease,border-color .35s ease}}.story-card:nth-child(5n+1),.story-card:nth-child(5n+2){{grid-column:span 6}}.story-card:hover{{transform:translateY(-8px);border-color:rgba(255,180,95,.55)}}.story-media{{height:300px;position:relative;overflow:hidden}}.story-card:nth-child(5n+1) .story-media,.story-card:nth-child(5n+2) .story-media{{height:390px}}.story-media img{{width:100%;height:100%;object-fit:cover;transition:transform .7s ease}}.story-card:hover img{{transform:scale(1.05)}}.story-index{{position:absolute;right:16px;top:14px;font-size:2rem;font-family:Georgia,serif;text-shadow:0 3px 20px #000}}.story-copy{{padding:24px}}.pill{{color:var(--accent);font-size:.72rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}.story-copy h3{{font-family:Georgia,serif;font-size:1.8rem;margin:10px 0}}.story-copy p{{color:var(--muted);line-height:1.65;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}}.open-story{{border:0;background:transparent;color:var(--text);font-weight:800;padding:10px 0;cursor:pointer}}.open-story span{{color:var(--accent)}}
.manifesto{{margin:110px 0;display:grid;grid-template-columns:1.2fr .8fr;gap:22px}}.manifesto>div{{background:linear-gradient(145deg,var(--surface),var(--surface2));border:1px solid var(--line);border-radius:32px;padding:clamp(28px,5vw,64px)}}.manifesto blockquote{{font-family:Georgia,serif;font-size:clamp(2rem,4vw,4rem);line-height:1.12;margin:0}}.manifesto p{{color:var(--muted);line-height:1.8}}footer{{border-top:1px solid var(--line);padding:36px 0 60px;color:var(--muted);display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}}
.modal{{position:fixed;inset:0;z-index:80;display:none;place-items:center;padding:18px;background:rgba(3,4,8,.8);backdrop-filter:blur(12px)}}.modal.open{{display:grid}}.modal-card{{width:min(920px,100%);max-height:90vh;overflow:auto;background:var(--surface);border:1px solid var(--line);border-radius:30px;display:grid;grid-template-columns:.9fr 1.1fr;position:relative}}.modal-card img{{width:100%;height:100%;min-height:520px;object-fit:cover}}.modal-copy{{padding:clamp(28px,5vw,56px)}}.modal-copy h3{{font:clamp(2.2rem,5vw,4.5rem)/.95 Georgia,serif;margin:14px 0 22px}}.modal-copy p{{color:var(--muted);line-height:1.8}}.close{{position:absolute;right:14px;top:14px;border:1px solid var(--line);background:var(--surface);color:inherit;border-radius:50%;width:42px;height:42px;cursor:pointer}}.reveal{{opacity:0;transform:translateY(24px)}}.reveal.visible{{opacity:1;transform:none;transition:opacity .7s ease,transform .7s ease}}.empty{{display:none;padding:40px;border:1px dashed var(--line);border-radius:24px;color:var(--muted);text-align:center}}
@media(max-width:850px){{.section-head,.manifesto{{grid-template-columns:1fr}}.story-card,.story-card:nth-child(5n+1),.story-card:nth-child(5n+2){{grid-column:span 6}}.modal-card{{grid-template-columns:1fr}}.modal-card img{{min-height:300px;height:300px}}}}
@media(max-width:560px){{.hero{{padding-inline:22px}}.story-card,.story-card:nth-child(5n+1),.story-card:nth-child(5n+2){{grid-column:1/-1}}.story-media,.story-card:nth-child(5n+1) .story-media,.story-card:nth-child(5n+2) .story-media{{height:320px}}.nav .hide-mobile{{display:none}}}}
@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important;animation:none!important;transition:none!important}}.reveal{{opacity:1;transform:none}}}}
</style></head><body><div class="progress"></div>
<nav class="nav"><div class="brand">Sophyane <b>Storyworld</b></div><div class="nav-actions"><a class="icon-btn hide-mobile" href="#stories">Explore</a><button class="icon-btn" id="theme" aria-label="Toggle theme">◐</button></div></nav>
<header class="hero"><img src="{hero_image}" alt="{title}"><div class="hero-content reveal"><div class="eyebrow">Internet-grounded editorial experience</div><h1>{title}</h1><p>{intro}</p><div class="hero-meta"><div class="metric"><strong>{len(entities)}</strong><span>curated profiles</span></div><div class="metric"><strong>{len(categories)}</strong><span>story categories</span></div><div class="metric"><strong>0</strong><span>LLMs used</span></div></div></div></header>
<main><div class="marquee"><div class="marquee-track"><span>{title}</span><span>Profiles</span><span>Stories</span><span>Culture</span><span>Verified sources</span><span>{title}</span><span>Profiles</span><span>Stories</span><span>Culture</span><span>Verified sources</span></div></div>
<section id="stories"><div class="section-head reveal"><h2>People, places<br>and perspectives.</h2><p>Instead of presenting one long article, Sophyane discovered related pages and assembled them into an interactive editorial directory. Search, filter and open any story for a focused profile.</p></div>
<div class="controls reveal"><input id="search" class="search" placeholder="Search this storyworld…" aria-label="Search profiles">{''.join(chips)}</div><div class="story-grid">{_entity_cards(entities)}</div><div class="empty" id="empty">No matching stories found.</div></section>
<section class="manifesto reveal"><div><span class="pill">The subject</span><blockquote>“{intro}”</blockquote></div><div><span class="pill">How this was made</span><p>Sophyane Option 1 resolved the topic, retrieved public-source material, discovered related entities, embedded available images, generated this self-contained interface, validated the artifact and made it ready for local preview.</p><p><a href="{source_url}" target="_blank" rel="noopener">Open primary source ↗</a></p></div></section>
<footer><span>Generated by Sophyane SLI Graph · no local or cloud LLM</span><span>{title}</span></footer></main>
<div class="modal" id="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle"><article class="modal-card"><button class="close" id="close" aria-label="Close">×</button><img id="modalImage" alt=""><div class="modal-copy"><span class="pill" id="modalCategory"></span><h3 id="modalTitle"></h3><p id="modalText"></p><a id="modalLink" target="_blank" rel="noopener">Read verified source ↗</a></div></article></div>
<script>const entities={data};const cards=[...document.querySelectorAll('.story-card')];const search=document.querySelector('#search');const chips=[...document.querySelectorAll('.filter-chip')];const empty=document.querySelector('#empty');let filter='all';
function apply(){{const q=search.value.trim().toLowerCase();let shown=0;cards.forEach(c=>{{const ok=(filter==='all'||c.dataset.category===filter)&&(!q||c.dataset.title.includes(q)||c.innerText.toLowerCase().includes(q));c.style.display=ok?'':'none';if(ok)shown++}});empty.style.display=shown?'none':'block'}}search.addEventListener('input',apply);chips.forEach(chip=>chip.addEventListener('click',()=>{{chips.forEach(x=>x.classList.remove('active'));chip.classList.add('active');filter=chip.dataset.filter;apply()}}));
const modal=document.querySelector('#modal');function openModal(i){{const e=entities[i];document.querySelector('#modalImage').src=e.image;document.querySelector('#modalImage').alt=e.title;document.querySelector('#modalCategory').textContent=e.category;document.querySelector('#modalTitle').textContent=e.title;document.querySelector('#modalText').textContent=e.extract;document.querySelector('#modalLink').href=e.url||'#';modal.classList.add('open');document.body.style.overflow='hidden'}}document.querySelectorAll('.open-story').forEach(b=>b.addEventListener('click',()=>openModal(+b.dataset.index)));cards.forEach((c,i)=>c.addEventListener('keydown',e=>{{if(e.key==='Enter')openModal(i)}}));function closeModal(){{modal.classList.remove('open');document.body.style.overflow=''}}document.querySelector('#close').onclick=closeModal;modal.addEventListener('click',e=>{{if(e.target===modal)closeModal()}});addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal()}});
document.querySelector('#theme').onclick=()=>document.body.classList.toggle('light');const observer=new IntersectionObserver(rows=>rows.forEach(r=>{{if(r.isIntersecting)r.target.classList.add('visible')}}),{{threshold:.12}});document.querySelectorAll('.reveal').forEach(x=>observer.observe(x));addEventListener('scroll',()=>{{const d=document.documentElement;document.querySelector('.progress').style.width=((d.scrollTop/(d.scrollHeight-d.clientHeight))*100||0)+'%'}});</script></body></html>'''


def _open_generated_site(
    target: Path,
    progress: Progress,
) -> tuple[bool, str]:
    """Open a generated HTML artifact in the user's desktop browser."""
    target = target.expanduser().resolve()

    if not target.is_file():
        return False, f"Browser launch skipped: file is missing: {target}"

    if str(os.environ.get("SOPHYANE_NO_BROWSER", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False, "Browser launch disabled by SOPHYANE_NO_BROWSER"

    # Under WSL, ask Windows to open the generated file.
    if os.environ.get("WSL_DISTRO_NAME"):
        try:
            converted = subprocess.run(
                ["wslpath", "-w", str(target)],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            windows_path = converted.stdout.strip()

            if windows_path:
                powershell = shutil.which("powershell.exe")
                if powershell:
                    subprocess.run(
                        [
                            powershell,
                            "-NoProfile",
                            "-NonInteractive",
                            "-Command",
                            "Start-Process",
                            "-FilePath",
                            windows_path,
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    progress(f"Opened website in Windows browser: {windows_path}")
                    return True, windows_path

                cmd = shutil.which("cmd.exe")
                if cmd:
                    subprocess.run(
                        [cmd, "/c", "start", "", windows_path],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    progress(f"Opened website in Windows browser: {windows_path}")
                    return True, windows_path
        except Exception as error:
            progress(
                "Windows browser launch failed; trying platform browser: "
                f"{type(error).__name__}: {error}"
            )

    # Native Linux, macOS, Windows Python, or WSL fallback.
    try:
        uri = target.as_uri()
        opened = bool(webbrowser.open(uri, new=2))
        if opened:
            progress(f"Opened website in browser: {uri}")
            return True, uri
        return False, f"Browser launcher declined URI: {uri}"
    except Exception as error:
        return False, f"Browser launch failed: {type(error).__name__}: {error}"


def _validate(document: str, entities: list[Entity]) -> str:
    checks = {
        "complete document": "</html>" in document.lower(),
        "substantial artifact": len(document) >= 12000,
        "multi-entity content": len(entities) >= 3,
        "search interaction": 'id="search"' in document and "function apply" in document,
        "filter interaction": "filter-chip" in document,
        "modal interaction": 'id="modal"' in document and "openModal" in document,
        "responsive design": "@media(max-width:560px)" in document,
        "reduced motion": "prefers-reduced-motion" in document,
        "source provenance": "Read verified source" in document,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return ", ".join(failed)


def compose_rich_topic_site(request: str, workspace: Path, *, progress: Progress | None = None) -> str:
    progress = progress or (lambda _m: None)
    if not is_topic_site_request(request):
        return "Success: False\nNot a supported informational website request.\n"
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    topic = extract_topic(request)
    source = retrieve_topic(topic, progress=progress)
    entities = _related_entities(topic, source.resolved_title, progress)
    if len(entities) < 3:
        progress("SLI rich-site: insufficient entity set; using primary source fragments")
        fragments = [p.strip() for p in re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z])", source.extract) if len(p.strip()) > 100][:6]
        entities = [Entity(f"{source.resolved_title} · {i+1}", _sentences(text, 3), source.page_url, source.image_data_uri, "Overview") for i, text in enumerate(fragments)]
    document = _render(source, entities)
    problem = _validate(document, entities)
    output = workspace / "index.html"
    if problem:
        output.unlink(missing_ok=True)
        return f"SLI rich-site validation failed: {problem}\nSuccess: False\n"
    output.write_text(document, encoding="utf-8")

    browser_opened, browser_target = _open_generated_site(
        output,
        progress,
    )

    return "\n".join([
        "Sophyane rich SLI website orchestrator",
        f"Request: {request}",
        f"Topic: {topic}",
        f"Resolved source: {source.resolved_title}",
        f"Related entities: {len(entities)}",
        "Components: cinematic hero, editorial grid, search, filters, profile modal, theme toggle, scroll motion, provenance",
        f"Bytes: {len(document.encode('utf-8'))}",
        "Files: index.html",
        f"Browser opened: {browser_opened}",
        f"Browser target: {browser_target}",
        "Validation: passed",
        "LLM used: False",
        "Success: True",
    ])
