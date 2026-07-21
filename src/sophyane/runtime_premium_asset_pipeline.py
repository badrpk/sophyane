"""Curate relevant internet photography before browser generation.

The runtime, not the model, discovers and downloads images. The model receives a
verified local asset manifest and must use those paths. This avoids invented URLs,
hotlink failures, and broken premium demos.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

_ACTIVE_ASSETS: list[str] = []


def _visual_request(message: str) -> bool:
    text = message.lower()
    return any(word in text for word in (
        "website", "landing page", "portfolio", "shop", "plants", "flowers",
        "fashion", "travel", "food", "hotel", "luxury", "photography", "gallery",
    ))


def _search_terms(message: str) -> str:
    words = re.findall(r"[a-zA-Z]{3,}", message.lower())
    stop = {
        "create", "make", "build", "website", "mobile", "responsive", "with",
        "beautiful", "fancy", "animations", "luxurious", "complete", "index",
        "html", "using", "inline", "javascript", "photos", "photography",
    }
    useful = [word for word in words if word not in stop]
    return " ".join(useful[:5]) or "nature editorial"


def _commons_candidates(query: str, limit: int = 8) -> list[tuple[str, str]]:
    params = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": "1600",
        "format": "json",
        "origin": "*",
    })
    request = urllib.request.Request(
        f"https://commons.wikimedia.org/w/api.php?{params}",
        headers={"User-Agent": "Sophyane/20.3 premium-demo asset curator"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.loads(response.read().decode("utf-8"))
    candidates: list[tuple[str, str]] = []
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = str(info.get("mime") or "")
        url = str(info.get("thumburl") or info.get("url") or "")
        title = str(page.get("title") or "image")
        if url.startswith("https://") and mime in {"image/jpeg", "image/png", "image/webp"}:
            candidates.append((title, url))
    return candidates


def _download_assets(message: str, workspace: Path, progress: Callable[[str], None]) -> list[str]:
    if not _visual_request(message):
        return []
    target_dir = workspace / "assets" / "images"
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    try:
        candidates = _commons_candidates(_search_terms(message))
    except Exception as error:  # noqa: BLE001
        progress(f"Premium photo discovery unavailable: {type(error).__name__}")
        return []
    for index, (_title, url) in enumerate(candidates, 1):
        if len(paths) >= 4:
            break
        suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        relative = f"assets/images/editorial-{index}{suffix}"
        destination = workspace / relative
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Sophyane/20.3"})
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read(5_000_001)
            if not 20_000 <= len(body) <= 5_000_000:
                continue
            destination.write_bytes(body)
            paths.append(relative)
            progress(f"Curated premium photo: {relative} ({len(body)} bytes)")
        except Exception as error:  # noqa: BLE001
            progress(f"Premium photo candidate skipped: {type(error).__name__}")
    return paths


def install_premium_asset_pipeline() -> None:
    from sophyane import adaptive_execution

    if getattr(adaptive_execution, "_premium_asset_pipeline_installed", False):
        return

    original_one_shot = adaptive_execution._one_shot_browser_artifact
    original_prompt = adaptive_execution._raw_html_prompt
    original_validate = adaptive_execution._validate_html

    def premium_prompt(original_request: str, existing: str = "") -> str:
        base = original_prompt(original_request, existing)
        if not _ACTIVE_ASSETS:
            return base
        manifest = "\n".join(f"- {path}" for path in _ACTIVE_ASSETS)
        return (
            base
            + "\n\nVERIFIED LOCAL PREMIUM PHOTO MANIFEST:\n"
            + manifest
            + "\nUse at least three of these exact local relative paths in meaningful hero/gallery/card compositions. "
              "Do not invent image paths and do not use any internet URL. Add descriptive alt text, object-fit cropping, "
              "dark overlays where needed for legibility, cinematic composition, and tasteful motion."
        )

    def premium_validate(html: str, request: str) -> str:
        problem = original_validate(html, request)
        if problem:
            return problem
        lower = html.lower()
        if _visual_request(request):
            generic = re.search(r"\bplant\s*[123]\b|another beautiful plant|special feature|learn more\s*</a>", lower)
            if generic:
                return "premium demo contains generic placeholder copy"
            if _ACTIVE_ASSETS and sum(path.lower() in lower for path in _ACTIVE_ASSETS) < min(3, len(_ACTIVE_ASSETS)):
                return "premium demo did not use the verified local photography manifest"
            if "prefers-reduced-motion" not in lower:
                return "premium animated demo lacks prefers-reduced-motion support"
        return ""

    def one_shot(*, ask: Any, original_request: str, workspace: Path, progress: Any) -> str | None:
        global _ACTIVE_ASSETS
        previous = _ACTIVE_ASSETS
        _ACTIVE_ASSETS = _download_assets(original_request, workspace, progress)
        if _visual_request(original_request) and not _ACTIVE_ASSETS:
            progress("No verified premium photos were available; provider must use embedded visual artwork")
        try:
            return original_one_shot(
                ask=ask,
                original_request=original_request,
                workspace=workspace,
                progress=progress,
            )
        finally:
            _ACTIVE_ASSETS = previous

    adaptive_execution._raw_html_prompt = premium_prompt
    adaptive_execution._validate_html = premium_validate
    adaptive_execution._one_shot_browser_artifact = one_shot
    adaptive_execution._premium_asset_pipeline_installed = True
