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
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sophyane.code_memory.sli_site_intelligence import (
    apply_design_proposal,
    build_site_plan,
    infer_site_intent,
)

from sophyane.code_memory.sli_site_generative import (
    build_creative_brief,
    propose_design,
)

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


def _render(
    source: TopicSource,
    entities: list[Entity],
    *,
    progress: Progress | None = None,
) -> str:
    """Render a grounded architecture with bounded local creative direction."""
    progress = progress or (lambda _message: None)

    intent = infer_site_intent(
        source,
        entities,
    )

    deterministic_plan = build_site_plan(
        source,
        entities,
    )

    brief = build_creative_brief(
        source,
        entities,
        intent,
    )

    proposal = propose_design(
        brief,
        progress,
    )

    plan = apply_design_proposal(
        deterministic_plan,
        proposal,
    )

    progress(
        "SLI site plan: "
        f"family={plan.family}; "
        f"visual={plan.visual_family}; "
        f"layout={plan.layout_strategy or 'deterministic'}; "
        f"concept={plan.design_concept or plan.hero_kicker}; "
        f"generated={plan.design_generated}"
    )

    topic = html.escape(
        source.requested_topic
    )

    title = html.escape(
        source.resolved_title
    )

    intro = html.escape(
        _sentences(
            source.extract,
            4,
        )
    )

    # Strict subject-image provenance:
    # never substitute a related person's photograph for the hero.
    hero_image = (
        source.image_data_uri
        or _fallback_art(
            source.resolved_title
        )
    )

    categories = sorted(
        {
            entity.category
            for entity in entities
        }
    )

    chips = [
        (
            '<button class="filter-chip active" '
            'data-filter="all">'
            'All stories'
            '</button>'
        )
    ]

    chips.extend(
        (
            '<button class="filter-chip" '
            f'data-filter="{html.escape(category.lower(), quote=True)}">'
            f'{html.escape(category)}'
            '</button>'
        )
        for category in categories
    )

    data = json.dumps(
        [
            {
                "title":
                    entity.title,

                "extract":
                    entity.extract,

                "url":
                    entity.url,

                "image":
                    (
                        entity.image
                        or _fallback_art(
                            entity.title
                        )
                    ),

                "category":
                    entity.category,
            }
            for entity in entities
        ]
    ).replace(
        "</",
        "<\\/",
    )

    source_url = html.escape(
        source.page_url
        or "#",
        quote=True,
    )

    sentences = [
        sentence.strip()
        for sentence in re.split(
            r"(?<=[.!?])\s+",
            source.extract,
        )
        if len(
            sentence.strip()
        ) >= 35
    ]

    chapters: list[str] = []

    cursor = 0

    for _index in range(4):
        chosen = sentences[
            cursor:
            cursor + 2
        ]

        if not chosen:
            break

        chapters.append(
            " ".join(
                chosen
            )
        )

        cursor += 2

    if not chapters:
        chapters = [
            source.extract
        ]

    while len(chapters) < 4:
        chapters.append(
            chapters[-1]
        )

    def phase_cards(
        class_name: str,
    ) -> str:
        return (
            f'<div class="{class_name}">'
            + "".join(
                (
                    '<article class="phase-card reveal">'
                    f'<span class="phase-index">0{index + 1}</span>'
                    f'<h3>{html.escape(label)}</h3>'
                    f'<p>{html.escape(chapters[index])}</p>'
                    '</article>'
                )
                for index, label in enumerate(
                    plan.section_labels
                )
            )
            + "</div>"
        )

    if plan.family == "research-profile":
        adaptive_feature = (
            '<section '
            'class="adaptive-feature research-feature" '
            'id="research-arc">'
            '<div class="feature-heading reveal">'
            f'<span class="pill">{html.escape(plan.feature_eyebrow)}</span>'
            f'<h2>{html.escape(plan.feature_title)}</h2>'
            f'<p>{html.escape(plan.feature_intro)}</p>'
            '</div>'
            + phase_cards(
                "research-grid"
            )
            + "</section>"
        )

        directory_heading = (
            "People, institutions<br>"
            "and connected ideas."
        )

        directory_copy = (
            "Related entities form a research network around "
            "the primary subject rather than replacing the main narrative."
        )

    elif plan.family == "public-life":
        era_links = "".join(
            (
                f'<a href="#phase-{index + 1}">'
                f'{html.escape(label)}'
                '</a>'
            )
            for index, label in enumerate(
                plan.section_labels
            )
        )

        life_phases = "".join(
            (
                '<article '
                'class="life-phase reveal" '
                f'id="phase-{index + 1}">'
                f'<span>0{index + 1}</span>'
                '<div>'
                f'<h3>{html.escape(label)}</h3>'
                f'<p>{html.escape(chapters[index])}</p>'
                '</div>'
                '</article>'
            )
            for index, label in enumerate(
                plan.section_labels
            )
        )

        adaptive_feature = (
            '<section '
            'class="adaptive-feature public-feature" '
            'id="life-chapters">'
            '<div class="feature-heading reveal">'
            f'<span class="pill">{html.escape(plan.feature_eyebrow)}</span>'
            f'<h2>{html.escape(plan.feature_title)}</h2>'
            f'<p>{html.escape(plan.feature_intro)}</p>'
            '</div>'
            '<nav class="era-nav reveal" '
            'aria-label="Life chapters">'
            f'{era_links}'
            '</nav>'
            '<div class="phase-stack">'
            f'{life_phases}'
            '</div>'
            '</section>'
        )

        directory_heading = (
            "People, organisations<br>"
            "and public connections."
        )

        directory_copy = (
            "Related people and institutions support the life-phase "
            "narrative instead of defining the page structure."
        )

    elif plan.family == "sports-career":
        adaptive_feature = (
            '<section '
            'class="adaptive-feature sports-feature" '
            'id="career-arc">'
            '<div class="feature-heading reveal">'
            f'<span class="pill">{html.escape(plan.feature_eyebrow)}</span>'
            f'<h2>{html.escape(plan.feature_title)}</h2>'
            f'<p>{html.escape(plan.feature_intro)}</p>'
            '</div>'
            + phase_cards(
                "career-track"
            )
            + "</section>"
        )

        directory_heading = (
            "Teams, rivals<br>"
            "and career context."
        )

        directory_copy = (
            "Career progression leads the experience; the profile "
            "directory supplies supporting competitive context."
        )

    elif plan.family == "place-guide":
        adaptive_feature = (
            '<section '
            'class="adaptive-feature place-feature" '
            'id="orientation">'
            '<div class="feature-heading reveal">'
            f'<span class="pill">{html.escape(plan.feature_eyebrow)}</span>'
            f'<h2>{html.escape(plan.feature_title)}</h2>'
            f'<p>{html.escape(plan.feature_intro)}</p>'
            '</div>'
            + phase_cards(
                "atlas-grid"
            )
            + "</section>"
        )

        directory_heading = (
            "Places, people<br>"
            "and local context."
        )

        directory_copy = (
            "The page behaves as an exploration guide rather "
            "than a biography-style profile."
        )

    elif plan.family == "organisation-profile":
        adaptive_feature = (
            '<section '
            'class="adaptive-feature organisation-feature" '
            'id="organisation-map">'
            '<div class="feature-heading reveal">'
            f'<span class="pill">{html.escape(plan.feature_eyebrow)}</span>'
            f'<h2>{html.escape(plan.feature_title)}</h2>'
            f'<p>{html.escape(plan.feature_intro)}</p>'
            '</div>'
            + phase_cards(
                "system-grid"
            )
            + "</section>"
        )

        directory_heading = (
            "Capabilities, people<br>"
            "and institutional links."
        )

        directory_copy = (
            "The organisation is represented as a system of purpose, "
            "capability, evolution and relationships."
        )

    elif plan.family == "culture-profile":
        adaptive_feature = (
            '<section '
            'class="adaptive-feature culture-feature" '
            'id="creative-arc">'
            '<div class="feature-heading reveal">'
            f'<span class="pill">{html.escape(plan.feature_eyebrow)}</span>'
            f'<h2>{html.escape(plan.feature_title)}</h2>'
            f'<p>{html.escape(plan.feature_intro)}</p>'
            '</div>'
            + phase_cards(
                "portfolio-strip"
            )
            + "</section>"
        )

        directory_heading = (
            "Work, collaborators<br>"
            "and cultural context."
        )

        directory_copy = (
            "Creative development leads the composition, with related "
            "profiles acting as contextual material."
        )

    else:
        adaptive_feature = (
            '<section '
            'class="adaptive-feature editorial-feature" '
            'id="subject-map">'
            '<div class="feature-heading reveal">'
            f'<span class="pill">{html.escape(plan.feature_eyebrow)}</span>'
            f'<h2>{html.escape(plan.feature_title)}</h2>'
            f'<p>{html.escape(plan.feature_intro)}</p>'
            '</div>'
            + phase_cards(
                "phase-grid"
            )
            + "</section>"
        )

        directory_heading = (
            "People, places<br>"
            "and perspectives."
        )

        directory_copy = (
            "Grounded source fragments provide context before the "
            "searchable related-entity directory."
        )

    return f"""<!doctype html>
<html
  lang="en"
  data-layout-family="{html.escape(plan.family, quote=True)}"
  data-visual-family="{html.escape(plan.visual_family, quote=True)}"
  data-primary-interaction="{html.escape(plan.primary_interaction, quote=True)}"
>
<head>
<meta charset="utf-8">
<meta
  name="viewport"
  content="width=device-width,initial-scale=1"
>
<meta
  name="description"
  content="A rich internet-grounded experience about {topic}"
>
<title>{title} — Sophyane Storyworld</title>

<style>
:root {{
    --bg:#090b12;
    --surface:#111521;
    --surface2:#171c2b;
    --text:#f6f2eb;
    --muted:#a7adbb;
    --accent:{plan.accent};
    --accent2:{plan.accent2};
    --line:rgba(255,255,255,.1);
    --max:1240px;
    --radius:26px;
}}

* {{
    box-sizing:border-box;
}}

html {{
    scroll-behavior:smooth;
}}

body {{
    margin:0;
    color:var(--text);
    background:
        radial-gradient(
            circle at 85% 8%,
            color-mix(
                in srgb,
                var(--accent2) 19%,
                transparent
            ),
            transparent 31%
        ),
        var(--bg);
    font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        "Segoe UI",
        sans-serif;
    overflow-x:hidden;
}}

body.light {{
    --bg:#f3eee8;
    --surface:#fffaf4;
    --surface2:#f0e5da;
    --text:#17131b;
    --muted:#6d6570;
    --line:rgba(25,18,28,.12);
}}

a {{
    color:inherit;
}}

button,
input {{
    font:inherit;
}}

.progress {{
    position:fixed;
    inset:0 auto auto 0;
    z-index:100;
    height:3px;
    width:0;
    background:
        linear-gradient(
            90deg,
            var(--accent),
            var(--accent2)
        );
}}

.nav {{
    position:fixed;
    z-index:50;
    top:16px;
    left:50%;
    transform:translateX(-50%);
    width:min(
        var(--max),
        calc(100% - 28px)
    );
    display:flex;
    align-items:center;
    justify-content:space-between;
    padding:12px 16px;
    border:1px solid var(--line);
    border-radius:18px;
    background:rgba(9,11,18,.72);
    backdrop-filter:blur(18px);
}}

body.light .nav {{
    background:rgba(255,250,244,.82);
}}

.brand {{
    font-weight:900;
    letter-spacing:.12em;
    text-transform:uppercase;
    font-size:.82rem;
}}

.brand b {{
    color:var(--accent);
}}

.nav-actions {{
    display:flex;
    gap:8px;
}}

.icon-btn {{
    border:1px solid var(--line);
    background:transparent;
    color:inherit;
    border-radius:12px;
    padding:9px 12px;
    cursor:pointer;
}}

.hero {{
    min-height:100svh;
    display:grid;
    align-items:end;
    position:relative;
    isolation:isolate;
    padding:
        120px
        max(
            24px,
            calc((100vw - var(--max))/2)
        )
        70px;
}}

.hero:before {{
    content:"";
    position:absolute;
    inset:0;
    z-index:-1;
    background:
        linear-gradient(
            90deg,
            rgba(6,7,13,.96) 0%,
            rgba(6,7,13,.62) 48%,
            rgba(6,7,13,.10)
        ),
        linear-gradient(
            0deg,
            var(--bg),
            transparent 42%
        );
}}

.hero img {{
    position:absolute;
    inset:0;
    z-index:-2;
    width:100%;
    height:100%;
    object-fit:cover;
    filter:saturate(.84);
}}

.hero-content {{
    max-width:800px;
}}

.eyebrow {{
    display:flex;
    align-items:center;
    gap:12px;
    color:var(--accent);
    font-weight:800;
    text-transform:uppercase;
    letter-spacing:.16em;
    font-size:.78rem;
}}

.eyebrow:before {{
    content:"";
    width:44px;
    height:1px;
    background:currentColor;
}}

h1 {{
    max-width:950px;
    margin:22px 0;
    font-family:Georgia,serif;
    font-size:clamp(
        3.3rem,
        9vw,
        8.5rem
    );
    line-height:.87;
    letter-spacing:-.07em;
}}

.hero p {{
    max-width:690px;
    color:#d8d5d6;
    font-size:clamp(
        1rem,
        2vw,
        1.25rem
    );
    line-height:1.75;
}}

.hero-meta {{
    display:flex;
    gap:24px;
    flex-wrap:wrap;
    margin-top:34px;
}}

.metric strong {{
    display:block;
    font-size:1.5rem;
}}

.metric span {{
    color:#c5c1c4;
    font-size:.78rem;
    text-transform:uppercase;
    letter-spacing:.1em;
}}

main {{
    width:min(
        var(--max),
        calc(100% - 32px)
    );
    margin:auto;
}}

.adaptive-feature {{
    padding:105px 0;
}}

.feature-heading {{
    display:grid;
    grid-template-columns:
        minmax(0,1.15fr)
        minmax(260px,.7fr);
    gap:50px;
    align-items:end;
    margin-bottom:42px;
}}

.feature-heading .pill {{
    grid-column:1/-1;
}}

.feature-heading h2 {{
    margin:0;
    font:
        clamp(
            2.7rem,
            6vw,
            6.2rem
        )/.92
        Georgia,
        serif;
    letter-spacing:-.055em;
}}

.feature-heading p {{
    margin:0;
    color:var(--muted);
    line-height:1.8;
}}

.phase-grid,
.research-grid,
.atlas-grid,
.system-grid {{
    display:grid;
    grid-template-columns:
        repeat(
            4,
            minmax(0,1fr)
        );
    gap:16px;
}}

.phase-card {{
    min-height:300px;
    display:flex;
    flex-direction:column;
    justify-content:space-between;
    padding:26px;
    background:
        linear-gradient(
            145deg,
            var(--surface),
            var(--surface2)
        );
    border:1px solid var(--line);
    border-radius:24px;
}}

.phase-index {{
    color:var(--accent);
    font-weight:900;
    letter-spacing:.12em;
}}

.phase-card h3 {{
    margin:auto 0 16px;
    font:
        1.8rem/1.05
        Georgia,
        serif;
}}

.phase-card p {{
    margin:0;
    color:var(--muted);
    line-height:1.65;
}}

.research-grid .phase-card:nth-child(1),
.research-grid .phase-card:nth-child(4) {{
    transform:translateY(28px);
}}

.era-nav {{
    position:sticky;
    top:92px;
    z-index:15;
    display:flex;
    gap:8px;
    overflow:auto;
    padding:10px;
    margin-bottom:28px;
    border:1px solid var(--line);
    border-radius:16px;
    background:
        color-mix(
            in srgb,
            var(--bg) 84%,
            transparent
        );
    backdrop-filter:blur(16px);
}}

.era-nav a {{
    white-space:nowrap;
    text-decoration:none;
    padding:9px 14px;
    border:1px solid var(--line);
    border-radius:999px;
    color:var(--muted);
}}

.phase-stack {{
    display:grid;
    gap:1px;
    overflow:hidden;
    border:1px solid var(--line);
    border-radius:30px;
}}

.life-phase {{
    display:grid;
    grid-template-columns:
        100px
        minmax(0,1fr);
    gap:26px;
    padding:
        clamp(
            28px,
            5vw,
            58px
        );
    background:var(--surface);
}}

.life-phase + .life-phase {{
    border-top:1px solid var(--line);
}}

.life-phase>span {{
    color:var(--accent);
    font:
        2rem
        Georgia,
        serif;
}}

.life-phase h3 {{
    margin:0 0 18px;
    font:
        clamp(
            2rem,
            4vw,
            4rem
        )/1
        Georgia,
        serif;
}}

.life-phase p {{
    max-width:760px;
    margin:0;
    color:var(--muted);
    line-height:1.8;
}}

.career-track,
.portfolio-strip {{
    display:grid;
    grid-auto-flow:column;
    grid-auto-columns:
        minmax(
            280px,
            38%
        );
    gap:18px;
    overflow-x:auto;
    overscroll-behavior-inline:contain;
    padding-bottom:14px;
}}

.place-feature .phase-card:nth-child(1),
.place-feature .phase-card:nth-child(4) {{
    grid-column:span 2;
}}

.organisation-feature .phase-card:nth-child(2) {{
    grid-column:span 2;
}}

.directory {{
    padding:85px 0 20px;
}}

.section-head {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:28px;
    align-items:end;
    margin-bottom:30px;
}}

.section-head h2 {{
    margin:0;
    font-family:Georgia,serif;
    font-size:clamp(
        2.3rem,
        5vw,
        5rem
    );
    line-height:1;
    letter-spacing:-.045em;
}}

.section-head p {{
    margin:0;
    color:var(--muted);
    line-height:1.8;
}}

.controls {{
    display:flex;
    gap:12px;
    flex-wrap:wrap;
    margin:28px 0 34px;
}}

.search {{
    flex:1;
    min-width:230px;
    padding:14px 18px;
    color:inherit;
    background:var(--surface);
    border:1px solid var(--line);
    border-radius:16px;
    outline:none;
}}

.filter-chip {{
    padding:11px 16px;
    color:var(--muted);
    background:transparent;
    border:1px solid var(--line);
    border-radius:999px;
    cursor:pointer;
}}

.filter-chip.active {{
    color:var(--bg);
    background:var(--text);
    border-color:var(--text);
}}

.story-grid {{
    display:grid;
    grid-template-columns:
        repeat(
            12,
            1fr
        );
    gap:22px;
}}

.story-card {{
    grid-column:span 4;
    overflow:hidden;
    background:var(--surface);
    border:1px solid var(--line);
    border-radius:var(--radius);
    transition:
        transform .35s ease,
        border-color .35s ease;
}}

.story-card:nth-child(5n+1),
.story-card:nth-child(5n+2) {{
    grid-column:span 6;
}}

.story-card:hover {{
    transform:translateY(-8px);
    border-color:
        color-mix(
            in srgb,
            var(--accent) 65%,
            transparent
        );
}}

.story-media {{
    height:300px;
    position:relative;
    overflow:hidden;
}}

.story-card:nth-child(5n+1) .story-media,
.story-card:nth-child(5n+2) .story-media {{
    height:390px;
}}

.story-media img {{
    width:100%;
    height:100%;
    object-fit:cover;
    transition:transform .7s ease;
}}

.story-card:hover img {{
    transform:scale(1.05);
}}

.story-index {{
    position:absolute;
    top:14px;
    right:16px;
    font-family:Georgia,serif;
    font-size:2rem;
    text-shadow:0 3px 20px #000;
}}

.story-copy {{
    padding:24px;
}}

.pill {{
    color:var(--accent);
    font-size:.72rem;
    font-weight:800;
    letter-spacing:.12em;
    text-transform:uppercase;
}}

.story-copy h3 {{
    margin:10px 0;
    font-family:Georgia,serif;
    font-size:1.8rem;
}}

.story-copy p {{
    color:var(--muted);
    line-height:1.65;
    display:-webkit-box;
    -webkit-line-clamp:4;
    -webkit-box-orient:vertical;
    overflow:hidden;
}}

.open-story {{
    padding:10px 0;
    color:var(--text);
    background:transparent;
    border:0;
    font-weight:800;
    cursor:pointer;
}}

.open-story span {{
    color:var(--accent);
}}

.manifesto {{
    display:grid;
    grid-template-columns:
        1.2fr
        .8fr;
    gap:22px;
    margin:110px 0;
}}

.manifesto>div {{
    padding:
        clamp(
            28px,
            5vw,
            64px
        );
    background:
        linear-gradient(
            145deg,
            var(--surface),
            var(--surface2)
        );
    border:1px solid var(--line);
    border-radius:32px;
}}

.manifesto blockquote {{
    margin:0;
    font-family:Georgia,serif;
    font-size:clamp(
        2rem,
        4vw,
        4rem
    );
    line-height:1.12;
}}

.manifesto p {{
    color:var(--muted);
    line-height:1.8;
}}

footer {{
    display:flex;
    justify-content:space-between;
    gap:20px;
    flex-wrap:wrap;
    padding:36px 0 60px;
    color:var(--muted);
    border-top:1px solid var(--line);
}}

.modal {{
    position:fixed;
    inset:0;
    z-index:80;
    display:none;
    place-items:center;
    padding:18px;
    background:rgba(3,4,8,.8);
    backdrop-filter:blur(12px);
}}

.modal.open {{
    display:grid;
}}

.modal-card {{
    position:relative;
    display:grid;
    grid-template-columns:
        .9fr
        1.1fr;
    width:min(
        920px,
        100%
    );
    max-height:90vh;
    overflow:auto;
    background:var(--surface);
    border:1px solid var(--line);
    border-radius:30px;
}}

.modal-card img {{
    width:100%;
    height:100%;
    min-height:520px;
    object-fit:cover;
}}

.modal-copy {{
    padding:
        clamp(
            28px,
            5vw,
            56px
        );
}}

.modal-copy h3 {{
    margin:14px 0 22px;
    font:
        clamp(
            2.2rem,
            5vw,
            4.5rem
        )/.95
        Georgia,
        serif;
}}

.modal-copy p {{
    color:var(--muted);
    line-height:1.8;
}}

.close {{
    position:absolute;
    top:14px;
    right:14px;
    width:42px;
    height:42px;
    color:inherit;
    background:var(--surface);
    border:1px solid var(--line);
    border-radius:50%;
    cursor:pointer;
}}

.reveal {{
    opacity:0;
    transform:translateY(24px);
}}

.reveal.visible {{
    opacity:1;
    transform:none;
    transition:
        opacity .7s ease,
        transform .7s ease;
}}

.empty {{
    display:none;
    padding:40px;
    color:var(--muted);
    border:1px dashed var(--line);
    border-radius:24px;
    text-align:center;
}}


/* Genuine family-level structural differences. */

html[data-layout-family="research-profile"]
.adaptive-feature {{
    border-block:1px solid var(--line);
}}

html[data-layout-family="research-profile"]
.hero-content {{
    max-width:900px;
}}

html[data-layout-family="public-life"]
.hero {{
    min-height:92svh;
}}

html[data-layout-family="public-life"]
.story-grid {{
    margin-top:54px;
}}

html[data-layout-family="sports-career"]
.hero:before {{
    background:
        linear-gradient(
            0deg,
            var(--bg),
            transparent 55%
        ),
        linear-gradient(
            90deg,
            rgba(4,10,8,.94),
            rgba(4,10,8,.22)
        );
}}

html[data-layout-family="place-guide"]
.hero-content {{
    max-width:680px;
}}

html[data-layout-family="organisation-profile"]
.hero {{
    min-height:78svh;
}}

html[data-layout-family="culture-profile"]
.story-card:nth-child(odd) {{
    transform:translateY(18px);
}}


@media(max-width:850px) {{
    .feature-heading,
    .section-head,
    .manifesto {{
        grid-template-columns:1fr;
    }}

    .phase-grid,
    .research-grid,
    .atlas-grid,
    .system-grid {{
        grid-template-columns:
            repeat(
                2,
                minmax(0,1fr)
            );
    }}

    .story-card,
    .story-card:nth-child(5n+1),
    .story-card:nth-child(5n+2) {{
        grid-column:span 6;
    }}

    .modal-card {{
        grid-template-columns:1fr;
    }}

    .modal-card img {{
        min-height:300px;
        height:300px;
    }}
}}


@media(max-width:560px) {{
    .hero {{
        padding-inline:22px;
    }}

    .adaptive-feature {{
        padding:72px 0;
    }}

    .phase-grid,
    .research-grid,
    .atlas-grid,
    .system-grid {{
        grid-template-columns:1fr;
    }}

    .research-grid .phase-card:nth-child(1),
    .research-grid .phase-card:nth-child(4) {{
        transform:none;
    }}

    .place-feature .phase-card:nth-child(1),
    .place-feature .phase-card:nth-child(4),
    .organisation-feature .phase-card:nth-child(2) {{
        grid-column:auto;
    }}

    .life-phase {{
        grid-template-columns:52px 1fr;
        gap:14px;
        padding:28px 20px;
    }}

    .career-track,
    .portfolio-strip {{
        grid-auto-columns:84%;
    }}

    .story-card,
    .story-card:nth-child(5n+1),
    .story-card:nth-child(5n+2) {{
        grid-column:1/-1;
    }}

    .story-media,
    .story-card:nth-child(5n+1) .story-media,
    .story-card:nth-child(5n+2) .story-media {{
        height:320px;
    }}

    .nav .hide-mobile {{
        display:none;
    }}
}}


@media(prefers-reduced-motion:reduce) {{
    * {{
        scroll-behavior:auto!important;
        animation:none!important;
        transition:none!important;
    }}

    .reveal {{
        opacity:1;
        transform:none;
    }}
}}
</style>
</head>

<body
  data-site-family="{html.escape(plan.family, quote=True)}"
  data-density="{html.escape(plan.density, quote=True)}"
  data-design-generated="{str(plan.design_generated).lower()}"
  data-layout-strategy="{html.escape(plan.layout_strategy, quote=True)}"
>

<div class="progress"></div>

<nav class="nav">
  <div class="brand">
    Sophyane <b>Storyworld</b>
  </div>

  <div class="nav-actions">
    <a
      class="icon-btn hide-mobile"
      href="#stories"
    >
      Explore
    </a>

    <button
      class="icon-btn"
      id="theme"
      aria-label="Toggle theme"
    >
      ◐
    </button>
  </div>
</nav>

<header class="hero">
  <img
    src="{hero_image}"
    alt="{title}"
  >

  <div class="hero-content reveal">
    <div class="eyebrow">
      {html.escape(plan.hero_kicker)}
    </div>

    <h1>{title}</h1>

    <p>{intro}</p>

    <div class="hero-meta">
      <div class="metric">
        <strong>{len(entities)}</strong>
        <span>curated profiles</span>
      </div>

      <div class="metric">
        <strong>{len(categories)}</strong>
        <span>story categories</span>
      </div>

      <div class="metric">
        <strong>{len(plan.section_labels)}</strong>
        <span>semantic chapters</span>
      </div>
    </div>
  </div>
</header>

<main>

{adaptive_feature}

<section
  class="directory"
  id="stories"
>
  <div class="section-head reveal">
    <h2>
      {directory_heading}
    </h2>

    <p>
      {html.escape(directory_copy)}
    </p>
  </div>

  <div class="controls reveal">
    <input
      id="search"
      class="search"
      placeholder="Search this experience…"
      aria-label="Search profiles"
    >

    {''.join(chips)}
  </div>

  <div class="story-grid">
    {_entity_cards(entities)}
  </div>

  <div
    class="empty"
    id="empty"
  >
    No matching stories found.
  </div>
</section>

<section class="manifesto reveal">
  <div>
    <span class="pill">
      The subject
    </span>

    <blockquote>
      “{intro}”
    </blockquote>
  </div>

  <div>
    <span class="pill">
      Adaptive SLI composition
    </span>

    <p>
      Sophyane classified the grounded evidence as
      <strong>{html.escape(plan.family)}</strong>
      and selected the
      <strong>{html.escape(plan.visual_family)}</strong>
      presentation family.
    </p>

    <p>
      Primary interaction:
      <strong>
        {html.escape(plan.primary_interaction)}
      </strong>
    </p>

    <p>
      The semantic family, grounded evidence, subject identity,
      provenance and validation remain deterministic. A local model
      may contribute a bounded creative direction. Invalid or
      unavailable proposals automatically fall back to the
      deterministic SitePlan.
    </p>

    <p>
      <a
        href="{source_url}"
        target="_blank"
        rel="noopener"
      >
        Open primary source ↗
      </a>
    </p>
  </div>
</section>

<footer>
  <span>
    Sophyane SLI Graph · adaptive deterministic composition
  </span>

  <span>
    {title} · {html.escape(plan.family)}
    · {html.escape(plan.design_concept or plan.visual_family)}
  </span>
</footer>

</main>

<div
  class="modal"
  id="modal"
  role="dialog"
  aria-modal="true"
  aria-labelledby="modalTitle"
>
  <article class="modal-card">

    <button
      class="close"
      id="close"
      aria-label="Close"
    >
      ×
    </button>

    <img
      id="modalImage"
      alt=""
    >

    <div class="modal-copy">

      <span
        class="pill"
        id="modalCategory"
      ></span>

      <h3 id="modalTitle"></h3>

      <p id="modalText"></p>

      <a
        id="modalLink"
        target="_blank"
        rel="noopener"
      >
        Read verified source ↗
      </a>

    </div>
  </article>
</div>

<script>
const entities={data};

const cards=[
    ...document.querySelectorAll(
        '.story-card'
    )
];

const search=
    document.querySelector(
        '#search'
    );

const chips=[
    ...document.querySelectorAll(
        '.filter-chip'
    )
];

const empty=
    document.querySelector(
        '#empty'
    );

let filter='all';


function apply() {{
    const q=
        search.value
            .trim()
            .toLowerCase();

    let shown=0;

    cards.forEach(
        card=>{{
            const ok=
                (
                    filter==='all' ||
                    card.dataset.category===filter
                )
                &&
                (
                    !q ||
                    card.dataset.title.includes(q) ||
                    card.innerText
                        .toLowerCase()
                        .includes(q)
                );

            card.style.display=
                ok
                    ? ''
                    : 'none';

            if(ok) {{
                shown++;
            }}
        }}
    );

    empty.style.display=
        shown
            ? 'none'
            : 'block';
}}


search.addEventListener(
    'input',
    apply
);


chips.forEach(
    chip=>
        chip.addEventListener(
            'click',
            ()=>{{
                chips.forEach(
                    item=>
                        item.classList.remove(
                            'active'
                        )
                );

                chip.classList.add(
                    'active'
                );

                filter=
                    chip.dataset.filter;

                apply();
            }}
        )
);


const modal=
    document.querySelector(
        '#modal'
    );


function openModal(index) {{
    const entity=
        entities[index];

    document.querySelector(
        '#modalImage'
    ).src=
        entity.image;

    document.querySelector(
        '#modalImage'
    ).alt=
        entity.title;

    document.querySelector(
        '#modalCategory'
    ).textContent=
        entity.category;

    document.querySelector(
        '#modalTitle'
    ).textContent=
        entity.title;

    document.querySelector(
        '#modalText'
    ).textContent=
        entity.extract;

    document.querySelector(
        '#modalLink'
    ).href=
        entity.url || '#';

    modal.classList.add(
        'open'
    );

    document.body.style.overflow=
        'hidden';
}}


document.querySelectorAll(
    '.open-story'
).forEach(
    button=>
        button.addEventListener(
            'click',
            ()=>openModal(
                +button.dataset.index
            )
        )
);


cards.forEach(
    (card,index)=>
        card.addEventListener(
            'keydown',
            event=>{{
                if(
                    event.key==='Enter'
                ) {{
                    openModal(
                        index
                    );
                }}
            }}
        )
);


function closeModal() {{
    modal.classList.remove(
        'open'
    );

    document.body.style.overflow=
        '';
}}


document.querySelector(
    '#close'
).onclick=
    closeModal;


modal.addEventListener(
    'click',
    event=>{{
        if(
            event.target===modal
        ) {{
            closeModal();
        }}
    }}
);


addEventListener(
    'keydown',
    event=>{{
        if(
            event.key==='Escape'
        ) {{
            closeModal();
        }}
    }}
);


document.querySelector(
    '#theme'
).onclick=
    ()=>document.body.classList.toggle(
        'light'
    );


const observer=
    new IntersectionObserver(
        rows=>
            rows.forEach(
                row=>{{
                    if(
                        row.isIntersecting
                    ) {{
                        row.target.classList.add(
                            'visible'
                        );
                    }}
                }}
            ),
        {{
            threshold:.12
        }}
    );


document.querySelectorAll(
    '.reveal'
).forEach(
    element=>
        observer.observe(
            element
        )
);


addEventListener(
    'scroll',
    ()=>{{
        const root=
            document.documentElement;

        document.querySelector(
            '.progress'
        ).style.width=
            (
                (
                    root.scrollTop
                    /
                    (
                        root.scrollHeight
                        -
                        root.clientHeight
                    )
                )
                *
                100
                ||
                0
            )
            +
            '%';
    }}
);
</script>

</body>
</html>"""



def _open_generated_site(
    target: Path,
    progress: Progress,
) -> tuple[bool, str]:
    """Serve, verify, and open the generated site over localhost HTTP."""
    target = target.expanduser().resolve()

    if not target.is_file():
        return (
            False,
            "Browser launch skipped: "
            f"file is missing: {target}",
        )

    if str(
        os.environ.get(
            "SOPHYANE_NO_BROWSER",
            "",
        )
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return (
            False,
            "Browser launch disabled by "
            "SOPHYANE_NO_BROWSER",
        )

    try:
        from sophyane.browser_runtime_v2 import (
            open_verified_browser,
        )

        return open_verified_browser(
            target.parent,
            progress,
        )

    except Exception as error:
        return (
            False,
            "Verified browser launch failed: "
            f"{type(error).__name__}: {error}",
        )



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
    document = _render(
        source,
        entities,
        progress=progress,
    )

    # Report model participation only when an accepted local design
    # proposal survived deterministic reconciliation into final HTML.
    design_generated = (
        'data-design-generated="true"'
        in document
    )

    design_llm = (
        "local-design"
        if design_generated
        else "False"
    )

    layout_match = re.search(
        r'data-layout-strategy="([^"]*)"',
        document,
    )

    design_layout = (
        layout_match.group(1)
        if layout_match
        else ""
    )

    family_match = re.search(
        r'data-layout-family="([^"]*)"',
        document,
    )

    design_family = (
        family_match.group(1)
        if family_match
        else ""
    )

    visual_match = re.search(
        r'data-visual-family="([^"]*)"',
        document,
    )

    design_visual = (
        visual_match.group(1)
        if visual_match
        else ""
    )
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
        f"Design generated: {design_generated}",
        f"Design family: {design_family}",
        f"Design visual: {design_visual}",
        f"Design layout: {design_layout}",
        "Validation: passed",
        f"LLM used: {design_llm}",
        "Success: True",
    ])
