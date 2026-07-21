"""Keep one-shot browser artifacts self-contained and visually useful."""
from __future__ import annotations

import html
import re
import urllib.parse

_IMAGE_ATTR = re.compile(
    r"(<(?:img|source)\b[^>]*?\b(?:src|srcset)\s*=\s*)([\"'])(.*?)(\2)",
    re.I | re.S,
)
_LOCAL_RESOURCE = re.compile(
    r"<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*[\"'](?!https?://|//|data:|blob:|#)([^\"']+)[\"']",
    re.I,
)
_CSS_LOCAL_URL = re.compile(
    r"url\(\s*([\"']?)(?!https?://|//|data:|blob:|#)([^)'\"]+)\1\s*\)", re.I
)


def _is_embedded_or_remote(value: str) -> bool:
    target = value.strip().lower()
    return not target or target.startswith(("data:", "http://", "https://", "//", "blob:", "#"))


def _svg_placeholder(label: str) -> str:
    safe = html.escape(label.strip() or "Botanical illustration")[:80]
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 520'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        "<stop stop-color='#efe5c8'/><stop offset='1' stop-color='#bcc9a5'/></linearGradient></defs>"
        "<rect width='800' height='520' rx='28' fill='url(#g)'/>"
        "<g fill='none' stroke='#4d6746' stroke-width='12' stroke-linecap='round'>"
        "<path d='M400 420C388 315 430 205 514 104'/><path d='M405 330C325 295 273 233 248 150'/>"
        "<path d='M438 260C516 249 574 208 615 142'/></g>"
        "<g fill='#6f8b61'><ellipse cx='278' cy='180' rx='72' ry='34' transform='rotate(35 278 180)'/>"
        "<ellipse cx='520' cy='145' rx='72' ry='34' transform='rotate(-35 520 145)'/>"
        "<ellipse cx='574' cy='230' rx='64' ry='31' transform='rotate(-18 574 230)'/></g>"
        f"<text x='400' y='475' text-anchor='middle' font-family='Georgia,serif' font-size='28' fill='#3e4e39'>{safe}</text>"
        "</svg>"
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


def _embed_missing_images(source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        prefix, quote, value, _closing = match.groups()
        first = value.split(",", 1)[0].strip().split()[0] if value.strip() else ""
        if _is_embedded_or_remote(first):
            return match.group(0)
        label = first.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
        return f"{prefix}{quote}{_svg_placeholder(label)}{quote}"

    return _IMAGE_ATTR.sub(replace, source)


def install_self_contained_html_patch() -> None:
    from sophyane import adaptive_execution as adaptive

    if getattr(adaptive, "_self_contained_html_patch_installed", False):
        return

    original_prompt = adaptive._raw_html_prompt
    original_extract = adaptive._extract_html
    original_validate = adaptive._validate_html

    def raw_html_prompt(original_request: str, existing: str = "") -> str:
        base = original_prompt(original_request, existing)
        return (
            base
            + "\nQUALITY CONTRACT: Create a polished responsive page with a clear header/hero, at least three useful content cards or sections, readable mobile spacing, and a footer. "
            "Never reference local image names such as plant1.jpg. Embed illustrations as inline SVG/data URIs or draw them with CSS. "
            "Do not use external scripts, stylesheets, fonts, or assets. Aim for roughly 2500-6000 characters while remaining complete."
        )

    def extract_html(text: str) -> str | None:
        value = original_extract(text)
        return _embed_missing_images(value) if value is not None else None

    def validate_html(source: str, request: str) -> str:
        problem = original_validate(source, request)
        if problem:
            return problem
        missing = _LOCAL_RESOURCE.search(source)
        if missing:
            return f"HTML references a missing local script or stylesheet: {missing.group(1)}"
        css_missing = _CSS_LOCAL_URL.search(source)
        if css_missing:
            return f"HTML references a missing local CSS asset: {css_missing.group(2)}"
        return ""

    adaptive._raw_html_prompt = raw_html_prompt
    adaptive._extract_html = extract_html
    adaptive._validate_html = validate_html
    adaptive._self_contained_html_patch_installed = True
