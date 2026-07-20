"""Kernel-owned incremental edits for constrained local browser models.

The local model remains available as a proposal generator, but common safe page
improvements are applied as deterministic, reversible transformations so a weak
model is not forced to rewrite an entire working document.
"""
from __future__ import annotations

import html as html_lib
import re
from pathlib import Path
from typing import Any, Callable


_STYLE_MARKER = "/* sophyane-incremental */"
_NAV_MARKER = "data-sophyane-nav"
_SERVICES_MARKER = "data-sophyane-services"


def _insert_before(text: str, closing_pattern: str, addition: str) -> str:
    match = re.search(closing_pattern, text, re.I)
    if not match:
        return text
    return text[: match.start()] + addition + "\n" + text[match.start() :]


def _request_features(request: str) -> set[str]:
    text = request.lower()
    features: set[str] = set()
    if any(word in text for word in ("navigation", "navbar", "nav bar", "menu")):
        features.add("nav")
    if any(word in text for word in ("call-to-action", "call to action", "cta", "get started")):
        features.add("cta")
    if "service" in text and any(word in text for word in ("card", "cards", "three", "3")):
        features.add("services")
    if any(word in text for word in ("modern color", "modern colours", "modern colors", "better spacing", "spacing")):
        features.add("theme")
    if any(word in text for word in ("animation", "animations", "animate", "subtle")):
        features.add("animation")
    if any(word in text for word in ("dark mode", "dark theme")):
        features.add("dark")
    return features


def _enhancement_css(features: set[str]) -> str:
    dark = "dark" in features
    bg = "#0f172a" if dark else "#f4f7fb"
    surface = "#172033" if dark else "#ffffff"
    text = "#eef2ff" if dark else "#172033"
    muted = "#bdc7db" if dark else "#5d6677"
    return f"""
<style>{_STYLE_MARKER}
:root{{--bg:{bg};--surface:{surface};--text:{text};--muted:{muted};--brand:#4f46e5;--brand2:#7c3aed}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{background:var(--bg)!important;color:var(--text)!important;font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.55}}
body>header,body>main,body>section,body>footer{{max-width:1100px;margin-inline:auto}}
.sophyane-nav{{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.9rem 1.1rem;background:color-mix(in srgb,var(--surface) 92%,transparent);backdrop-filter:blur(12px);box-shadow:0 8px 30px #0001}}
.sophyane-brand{{font-weight:800;letter-spacing:.02em}}.sophyane-links{{display:flex;gap:.9rem;flex-wrap:wrap}}.sophyane-links a{{color:var(--text);text-decoration:none;font-weight:650}}
.sophyane-cta{{display:inline-block;margin-top:1rem;padding:.8rem 1.2rem;border-radius:999px;background:linear-gradient(135deg,var(--brand),var(--brand2));color:white!important;text-decoration:none;font-weight:800;box-shadow:0 12px 25px #4f46e544}}
.sophyane-services{{padding:2.5rem 1rem}}.sophyane-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}}.sophyane-card{{padding:1.25rem;border-radius:18px;background:var(--surface);color:var(--text);box-shadow:0 14px 40px #00000012;border:1px solid #7c3aed22}}.sophyane-card p{{color:var(--muted)}}
body>*{{transition:transform .25s ease,box-shadow .25s ease,background .25s ease}}.sophyane-card:hover{{transform:translateY(-5px);box-shadow:0 20px 50px #0002}}
@keyframes sophyaneIn{{from{{opacity:0;transform:translateY(12px)}}to{{opacity:1;transform:none}}}}.sophyane-nav,.sophyane-services,.sophyane-cta{{animation:sophyaneIn .55s ease both}}
@media(max-width:700px){{.sophyane-grid{{grid-template-columns:1fr}}.sophyane-nav{{align-items:flex-start}}.sophyane-links{{justify-content:flex-end}}}}
</style>
"""


def apply_incremental_edit(existing: str, request: str) -> tuple[str, list[str]]:
    """Apply safe idempotent feature transforms and return evidence labels."""
    features = _request_features(request)
    if not features:
        return existing, []
    updated = existing
    evidence: list[str] = []

    if _STYLE_MARKER not in updated:
        updated = _insert_before(updated, r"</head\s*>", _enhancement_css(features))
        evidence.append("responsive theme and spacing")

    if "nav" in features and _NAV_MARKER not in updated:
        nav = (
            '<nav class="sophyane-nav" data-sophyane-nav>'
            '<span class="sophyane-brand">Our Company</span>'
            '<span class="sophyane-links"><a href="#home">Home</a><a href="#services">Services</a><a href="#contact">Contact</a></span>'
            '</nav>'
        )
        body = re.search(r"<body\b[^>]*>", updated, re.I)
        if body:
            updated = updated[: body.end()] + "\n" + nav + updated[body.end() :]
            evidence.append("navigation bar")

    if "cta" in features and "data-sophyane-cta" not in updated:
        cta = '<a class="sophyane-cta" data-sophyane-cta href="#services">Explore Our Services</a>'
        heading = re.search(r"</h1\s*>", updated, re.I)
        if heading:
            updated = updated[: heading.end()] + "\n" + cta + updated[heading.end() :]
        else:
            updated = _insert_before(updated, r"</body\s*>", cta)
        evidence.append("call-to-action button")

    if "services" in features and _SERVICES_MARKER not in updated:
        services = (
            '<section id="services" class="sophyane-services" data-sophyane-services>'
            '<h2>Our Services</h2><div class="sophyane-grid">'
            '<article class="sophyane-card"><h3>Strategy</h3><p>Clear plans shaped around practical business goals.</p></article>'
            '<article class="sophyane-card"><h3>Design</h3><p>Accessible, responsive experiences for every device.</p></article>'
            '<article class="sophyane-card"><h3>Delivery</h3><p>Reliable implementation with measurable results.</p></article>'
            '</div></section>'
        )
        footer = re.search(r"<footer\b", updated, re.I)
        if footer:
            updated = updated[: footer.start()] + services + "\n" + updated[footer.start() :]
        else:
            updated = _insert_before(updated, r"</body\s*>", services)
        evidence.append("three service cards")

    return updated, evidence


def install_incremental_browser_edit() -> None:
    """Wrap adaptive browser generation with deterministic editing of existing pages."""
    from sophyane import adaptive_execution as adaptive

    original = adaptive._one_shot_browser_artifact
    if getattr(original, "_sophyane_incremental", False):
        return

    def wrapped(*, ask: Callable[[str], Any], original_request: str,
                workspace: Path, progress: Callable[[str], None]) -> str | None:
        target = workspace / "index.html"
        if target.is_file():
            try:
                existing = target.read_text(encoding="utf-8")
                edited, evidence = apply_incremental_edit(existing, original_request)
                if evidence and edited != existing:
                    problem = adaptive._validate_html(edited, original_request)
                    if not problem:
                        temporary = target.with_suffix(".html.tmp")
                        temporary.write_text(edited, encoding="utf-8")
                        temporary.replace(target)
                        progress("Applied kernel-owned incremental browser edit: " + ", ".join(evidence))
                        from sophyane import execution_runtime as runtime
                        progress("Incremental artifact passed structural verification; opening demo")
                        ok, result = runtime.execute_action({"type": "open_browser"}, workspace, progress)
                        if ok:
                            return (
                                "Updated and opened the incrementally enhanced browser project.\n\n"
                                f"Workspace: {workspace}\nFile: index.html\n\nExecution evidence:\n"
                                f"- Preserved existing page ({len(existing.encode('utf-8'))} bytes)\n"
                                f"- Added: {', '.join(evidence)}\n"
                                "- HTML body/script structure verified\n"
                                "- JavaScript bracket structure verified\n"
                                f"- {result}"
                            )
                    else:
                        progress(f"Incremental kernel edit rejected before write: {problem}")
            except Exception as error:
                progress(f"Incremental browser edit unavailable: {type(error).__name__}: {error}")
        return original(ask=ask, original_request=original_request, workspace=workspace, progress=progress)

    wrapped._sophyane_incremental = True  # type: ignore[attr-defined]
    adaptive._one_shot_browser_artifact = wrapped
