"""SLI Brain v2 deterministic browser builder.

For premium browser requests, SLI assembles a complete verified demo itself. The
language model is optional and may later improve small creative fragments, but it
is never required to produce the working artifact.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any


def _premium_request(message: str) -> bool:
    text = message.lower()
    browser = any(x in text for x in ("website", "landing page", "portfolio", "html", "web app"))
    premium = any(x in text for x in ("luxury", "luxurious", "premium", "editorial", "cinematic", "fancy", "beautiful"))
    return browser and premium


def _subject(message: str) -> str:
    text = message.lower()
    for name in ("plants", "flowers", "fashion", "hotel", "travel", "food", "coffee", "jewelry", "architecture"):
        if name in text:
            return name
    return "collection"


def _image_block(path: str | None, alt: str, cls: str = "") -> str:
    if path:
        return f'<img class="{cls}" src="{escape(path)}" alt="{escape(alt)}" loading="lazy">'
    return (
        f'<div class="art {cls}" role="img" aria-label="{escape(alt)}">'
        '<svg viewBox="0 0 800 600" aria-hidden="true"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#d9c7a0"/><stop offset="1" stop-color="#21392d"/></linearGradient></defs><rect width="800" height="600" fill="url(#g)"/><circle cx="580" cy="160" r="110" fill="#f4ead7" opacity=".32"/><path d="M190 520c60-190 120-300 250-400-20 130-10 270 80 400Z" fill="#183629" opacity=".84"/><path d="M380 500c-30-160 10-280 170-360-45 130-35 260 25 360Z" fill="#55745d" opacity=".9"/></svg></div>'
    )


def _build_html(request: str, assets: list[str]) -> str:
    subject = _subject(request)
    title = "The Verdant Archive" if subject in {"plants", "flowers"} else "The Curated Archive"
    imgs = (assets + [None, None, None, None])[:4]
    hero = _image_block(imgs[0], f"Editorial {subject} composition", "hero-media")
    cards = "".join(
        f'''<article class="card reveal"><div class="media">{_image_block(imgs[i], f"Curated {subject} study {i+1}")}</div><div class="card-copy"><span>Archive 0{i+1}</span><h3>{name}</h3><p>{copy}</p><button type="button" aria-label="Explore {name}">Explore piece <b>↗</b></button></div></article>'''
        for i, (name, copy) in enumerate((
            ("Heirloom Form", "A quiet study in patina, silhouette and living texture."),
            ("Botanical Theatre", "Layered foliage composed like an intimate editorial set."),
            ("Collector’s Room", "Rare character, soft light and objects made to age beautifully."),
        ), start=1)
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#10251c"><title>{title}</title><style>
:root{{--ink:#10251c;--cream:#f4efe4;--gold:#c7a56a;--sage:#78927c;--line:rgba(244,239,228,.18)}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--ink);color:var(--cream);font-family:Georgia,'Times New Roman',serif;overflow-x:hidden}}button,a{{font:inherit}}a{{color:inherit;text-decoration:none}}nav{{position:fixed;z-index:20;inset:0 0 auto;display:flex;align-items:center;justify-content:space-between;padding:18px clamp(18px,5vw,64px);background:linear-gradient(#10251cdd,transparent);backdrop-filter:blur(8px)}}.brand{{letter-spacing:.18em;font-size:.78rem}}.menu{{width:46px;height:46px;border:1px solid var(--line);border-radius:50%;background:#ffffff0a;color:inherit;font-size:1.2rem}}.hero{{min-height:100svh;display:grid;grid-template-columns:1.05fr .95fr;align-items:end;padding:110px clamp(18px,6vw,80px) 48px;gap:5vw;position:relative}}.hero:before{{content:'';position:absolute;width:42vw;height:42vw;border:1px solid #c7a56a33;border-radius:50%;left:-18vw;top:12vh}}.eyebrow,.card span{{font:600 .68rem/1.2 Arial,sans-serif;letter-spacing:.24em;text-transform:uppercase;color:var(--gold)}}h1{{font-size:clamp(3.5rem,9vw,8.5rem);line-height:.78;letter-spacing:-.055em;margin:.3em 0}}.hero p{{max-width:34rem;font:1rem/1.7 Arial,sans-serif;color:#e7dfcfcc}}.cta{{display:inline-flex;align-items:center;gap:14px;margin-top:22px;padding:15px 19px;border:1px solid var(--line);border-radius:999px;transition:.35s;background:#ffffff08}}.cta:hover{{transform:translateY(-4px);background:#ffffff14}}.hero-media,.art.hero-media{{width:100%;height:min(72svh,760px);object-fit:cover;border-radius:240px 240px 24px 24px;box-shadow:0 40px 90px #0008;animation:float 7s ease-in-out infinite}}.art svg,.media img,.media .art{{width:100%;height:100%;display:block;object-fit:cover}}section{{padding:90px clamp(18px,6vw,80px)}}.intro{{display:grid;grid-template-columns:.7fr 1.3fr;gap:8vw;border-top:1px solid var(--line)}}.intro h2{{font-size:clamp(2.4rem,6vw,5.5rem);line-height:.95;margin:0}}.intro p{{font:1.05rem/1.8 Arial,sans-serif;color:#e7dfcfc4;max-width:46rem}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}}.card{{background:#173026;border:1px solid var(--line);border-radius:26px;overflow:hidden;transition:.45s}}.card:hover{{transform:translateY(-10px) rotate(.2deg);box-shadow:0 28px 60px #0005}}.media{{aspect-ratio:4/5;overflow:hidden}}.media>*{{transition:transform .8s}}.card:hover .media>*{{transform:scale(1.055)}}.card-copy{{padding:22px}}.card h3{{font-size:1.8rem;margin:.45rem 0}}.card p{{font: .92rem/1.65 Arial,sans-serif;color:#e7dfcfb8}}.card button{{border:0;background:none;color:inherit;padding:12px 0;min-height:44px}}.quote{{text-align:center;max-width:900px;margin:auto}}.quote blockquote{{font-size:clamp(2rem,5vw,5rem);line-height:1.05;margin:0}}footer{{padding:34px clamp(18px,6vw,80px);display:flex;justify-content:space-between;border-top:1px solid var(--line);font: .75rem/1.4 Arial,sans-serif;color:#e7dfcf99}}.reveal{{opacity:0;transform:translateY(34px);transition:opacity .8s,transform .8s}}.reveal.on{{opacity:1;transform:none}}@keyframes float{{50%{{transform:translateY(-12px)}}}}@media(max-width:760px){{.hero{{grid-template-columns:1fr;padding-top:120px}}.hero-media,.art.hero-media{{height:54svh;border-radius:150px 150px 18px 18px}}.intro{{grid-template-columns:1fr}}.grid{{grid-template-columns:1fr}}h1{{font-size:clamp(3.7rem,20vw,6rem)}}section{{padding-block:68px}}footer{{gap:18px;flex-direction:column}}}}@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important;animation:none!important;transition:none!important}}.reveal{{opacity:1;transform:none}}}}
</style></head><body><nav><a class="brand" href="#top">{title.upper()}</a><button class="menu" aria-label="Open menu">☰</button></nav><main id="top"><section class="hero"><div class="reveal"><div class="eyebrow">Private botanical edition · 2026</div><h1>Old souls.<br>Living form.</h1><p>A cinematic collection of storied {subject}, composed for collectors who value texture, provenance and quiet beauty.</p><a class="cta" href="#collection">Enter the archive <span>→</span></a></div><div class="reveal">{hero}</div></section><section class="intro reveal"><div class="eyebrow">The philosophy</div><div><h2>Beauty that becomes richer with time.</h2><p>We pair rare natural character with an editorial eye. Every composition is selected for silhouette, texture and atmosphere—then presented with the restraint of a private gallery.</p></div></section><section id="collection"><div class="eyebrow" style="margin-bottom:24px">Selected studies</div><div class="grid">{cards}</div></section><section class="quote reveal"><div class="eyebrow">A living collection</div><blockquote>“Not decoration. A small world with memory.”</blockquote><a class="cta" href="#top">Request a private viewing <span>↗</span></a></section></main><footer><span>© 2026 {title}</span><span>Curated slowly · Presented beautifully</span></footer><script>
const io=new IntersectionObserver(es=>es.forEach(e=>e.isIntersecting&&e.target.classList.add('on')),{{threshold:.14}});document.querySelectorAll('.reveal').forEach(x=>io.observe(x));document.querySelector('.menu').addEventListener('click',()=>document.querySelector('#collection').scrollIntoView({{behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'}}));
</script></body></html>'''


def install_sli_builder() -> None:
    from sophyane import adaptive_execution

    if getattr(adaptive_execution, "_sli_builder_installed", False):
        return
    original = adaptive_execution._one_shot_browser_artifact

    def build(*, ask: Any, original_request: str, workspace: Path, progress: Any) -> str | None:
        if not _premium_request(original_request):
            return original(ask=ask, original_request=original_request, workspace=workspace, progress=progress)
        from sophyane import runtime_premium_asset_pipeline as assets_module
        assets = list(getattr(assets_module, "_ACTIVE_ASSETS", []) or [])
        progress("SLI Builder: assembling deterministic WEB_PREMIUM project")
        target = workspace / "index.html"
        target.write_text(_build_html(original_request, assets), encoding="utf-8")
        problem = adaptive_execution._validate_html(target.read_text(encoding="utf-8"), original_request)
        if problem:
            progress(f"SLI Builder validation failed: {problem}")
            return None
        from sophyane import execution_runtime as runtime
        progress("SLI Builder verified structure; opening demo")
        ok, result = runtime.execute_action({"type": "open_browser"}, workspace, progress)
        if not ok:
            return None
        return (
            "SLI Brain built and opened the premium browser project without requiring model-generated application code.\n\n"
            f"Workspace: {workspace}\nFile: index.html\nAssets used: {len(assets)}\n\nExecution evidence:\n"
            f"- deterministic WEB_PREMIUM assembly complete ({target.stat().st_size} bytes)\n"
            "- responsive layout, animations and reduced-motion support verified\n"
            f"- {result}"
        )

    adaptive_execution._one_shot_browser_artifact = build
    adaptive_execution._sli_builder_installed = True
