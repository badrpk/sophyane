
"""Licence gate + clone ranking helpers for SLI internet acquire."""
from __future__ import annotations

from pathlib import Path

PERMISSIVE = {
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc",
    "mpl-2.0", "unlicense", "0bsd", "cc0-1.0", "wtfpl", "zlib", "bsl-1.0",
}
MARKERS = {
    "mit license": "mit",
    "permission is hereby granted, free of charge": "mit",
    "licensed under the mit": "mit",
    "apache license": "apache-2.0",
    "bsd 2-clause": "bsd-2-clause",
    "bsd 3-clause": "bsd-3-clause",
    "redistribution and use in source and binary forms": "bsd-3-clause",
    "isc license": "isc",
    "mozilla public license": "mpl-2.0",
    "the unlicense": "unlicense",
    "creative commons zero": "cc0-1.0",
    "cc0 1.0": "cc0-1.0",
    "do what the fuck you want": "wtfpl",
    "zlib license": "zlib",
    "boost software license": "bsl-1.0",
}
COPYLEFT = (
    "gnu general public license", "gpl-3.0", "gpl-2.0", "agpl",
    "affero general public", "lesser general public license", "lgpl",
)

def scan_text(text: str) -> str | None:
    low = (text or "").lower()
    for bad in COPYLEFT:
        if bad in low:
            return "COPYLEFT:" + bad
    for marker, spdx in MARKERS.items():
        if marker in low:
            return spdx
    return None

def detect_licence(root: Path | str, api_licence: str = "") -> str | None:
    api = str(api_licence or "").strip().lower()
    if api in PERMISSIVE:
        return api
    if api in {"gpl-2.0", "gpl-3.0", "agpl-3.0", "lgpl-2.1", "lgpl-3.0"}:
        return "COPYLEFT:" + api
    root = Path(root)
    if not root.is_dir():
        return None
    files: list[Path] = []
    try:
        for p in root.iterdir():
            if p.is_file() and p.name.lower().startswith(
                ("license", "licence", "copying", "readme")
            ):
                files.append(p)
    except OSError:
        pass
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if not p.name.lower().startswith(("license", "licence", "copying")):
                continue
            if len(p.relative_to(root).parts) > 3:
                continue
            if p not in files:
                files.append(p)
            if len(files) >= 12:
                break
    except OSError:
        pass
    for path in files[:12]:
        try:
            blob = path.read_text(encoding="utf-8", errors="ignore")[:120_000]
        except OSError:
            continue
        hit = scan_text(blob)
        if hit:
            return hit
    return None

def is_small_browser_demo(root: Path | str) -> bool:
    root = Path(root)
    if not root.is_dir():
        return False
    total = 0
    html = 0
    js = 0
    skip = {".git", "node_modules", "vendor", "dist", "build", "__pycache__"}
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if skip & {x.lower() for x in p.parts}:
                continue
            suf = p.suffix.lower()
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            total += sz
            if total > 2_500_000:
                return False
            if suf in {".html", ".htm"}:
                html += 1
            if suf in {".js", ".mjs", ".cjs"}:
                js += 1
    except OSError:
        return False
    if html < 1:
        return False
    det = detect_licence(root, "")
    if det and str(det).startswith("COPYLEFT:"):
        return False
    return True

def decide(root, api_licence: str = "", allow_soft: bool = True) -> tuple[bool, str, str]:
    det = detect_licence(root, api_licence)
    if det and str(det).startswith("COPYLEFT:"):
        return False, det, "copyleft-rejected"
    if det in PERMISSIVE:
        return True, det, "allowlist"
    if allow_soft and is_small_browser_demo(root):
        return True, det or "soft-browser-demo", "soft-browser-demo"
    return False, det or "none", "no-verified-permissive"

def rank_key(repo) -> tuple:
    """Lower sort key = better clone priority. Prefer known permissive SPDX."""
    api = str(getattr(repo, "api_licence", "") or "").strip().lower()
    size = float(getattr(repo, "size_kb", 0) or 0)
    score = float(getattr(repo, "score", 0) or 0)
    stars = float(getattr(repo, "stars", 0) or 0)
    name = str(getattr(repo, "full_name", "") or "")
    if api in PERMISSIVE:
        tier = 0
    elif api in {"", "none", "noassertion", "other"}:
        tier = 2
    else:
        tier = 1  # known non-empty but not allowlisted
    # Prefer smallish browser demos after SPDX
    size_pen = 0 if size < 500 else (1 if size < 5000 else 2)
    return (tier, size_pen, -score, -stars, name)

def sort_repositories(repos: list) -> list:
    return sorted(list(repos or []), key=rank_key)

# SOPHYANE_STRICT_LICENCE_OVERRIDE_V1
from sophyane.code_memory.strict_acquisition_guard import (
    normalise_licence as _strict_normalise_licence,
)


def strict_permissive_licence(
    value,
):
    return _strict_normalise_licence(
        value
    )


def allow_soft_browser_demo(
    *_args,
    **_kwargs,
):
    return False
