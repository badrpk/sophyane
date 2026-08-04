 # BLOCK_PYTHON_IN_BROWSER_COMPOSE

"""Compose artifacts from retrieved chunks — no product-specific hardcoding.

Uses:
- retrieval over weighted code memory
- filters (drop tests unless asked)
- placement roles (html_document / script / style / module)
- generic document frames only (structure), bodies come from chunks
"""
from __future__ import annotations

import os

import re
from pathlib import Path
from typing import Callable

from sophyane.code_memory.store import ChunkStore, CodeChunk
try:
    from sophyane.code_memory.semantic_retrieve import retrieve_semantic
except Exception:
    retrieve_semantic = None
from sophyane.code_memory.learner import apply_outcome


def _wants_tests(message: str) -> bool:
    t = message.lower()
    return any(x in t for x in ("test", "pytest", "unittest", "spec"))


def _is_test_chunk(c: CodeChunk) -> bool:
    p = (c.path or "").lower()
    name = Path(p.split("::")[0]).name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in p.replace("\\", "/")
        or "\\tests\\" in p
        or name.endswith(".test.js")
    )


def _placement(c: CodeChunk) -> str:
    return str((c.meta or {}).get("placement") or "")


def _score_adjust(message: str, chunk: CodeChunk, base: float) -> float:
    """Rerank for useful assembly, not library trivia."""
    s = base
    low = message.lower()
    path = (chunk.path or "").lower()
    text = chunk.text
    tags = " ".join(chunk.tags or []).lower()

    if not _wants_tests(message) and _is_test_chunk(chunk):
        s -= 1.0
    if _placement(chunk) in {"html_document", "python_module", "script"}:
        s += 0.15
    if len(text) < 80:
        s -= 0.4
    if len(text) > 400:
        s += 0.1
    # topical boosts from message tokens present in chunk
    for tok in re.findall(r"[a-z]{3,}", low):
        if tok in text.lower() or tok in tags or tok in path:
            s += 0.03
    if (chunk.meta or {}).get("kind") == "rich":
        s += 0.12
    s *= max(0.05, float(chunk.weight))
    return s


def retrieve_ranked(store: ChunkStore, message: str, top_k: int = 12) -> list[tuple[CodeChunk, float]]:
    # SEMANTIC_RETRIEVE
    if retrieve_semantic is not None:
        return retrieve_semantic(store, message, top_k=top_k)
    raw = store.retrieve(message, top_k=max(top_k * 3, 20))
    ranked = [(c, _score_adjust(message, c, score)) for c, score in raw]
    ranked.sort(key=lambda x: x[1], reverse=True)
    out = []
    for c, s in ranked:
        if not _wants_tests(message) and _is_test_chunk(c):
            continue
        out.append((c, s))
        if len(out) >= top_k:
            break
    return out


def _extract_script_bodies(html_or_js: str) -> str:
    parts = re.findall(r"<script\b[^>]*>(.*?)</script>", html_or_js, flags=re.I | re.S)
    if parts:
        return "\n\n".join(p.strip() for p in parts if p.strip())
    return html_or_js


def _looks_browser_game(message: str) -> bool:
    t = message.lower()
    return "game" in t or any(x in t for x in ("canvas", "snake", "pong", "tetris", "playable"))


def _looks_web(message: str) -> bool:
    t = message.lower()
    return any(x in t for x in ("website", "webpage", "html", "landing", "page", "browser")) or _looks_browser_game(message)


def _validate_python(text: str) -> list[str]:
    try:
        compile(text, "<chunk>", "exec")
        return []
    except SyntaxError as e:
        return [str(e)]


def _validate_html(text: str) -> list[str]:
    errs = []
    low = text.lower()
    if "<html" not in low:
        errs.append("missing html")
    if "<script" in low and text.count("{") != text.count("}"):
        errs.append("unbalanced braces in document")
    return errs


def compose_browser_from_chunks(message: str, chunks: list[CodeChunk]) -> tuple[str, list[str]]:
    """Generic HTML frame; behavior injected from chunk script/html bodies."""
    used = []
    scripts = []
    styles = []
    title = "SLI App"
    # pull title-ish token
    m = re.search(r"\b([A-Za-z][A-Za-z0-9_-]{2,})\b", message)
    if m:
        title = m.group(1).title()

    for c in chunks:
        used.append(c.id)
        if c.language == "css" or _placement(c) == "style":
            styles.append(c.text)
            continue
        body = c.text
        if c.language == "html" or "<html" in body.lower() or "<script" in body.lower():
            scripts.append(_extract_script_bodies(body))
            # if full html already good and long enough, prefer returning it directly
            if len(body) > 800 and "<html" in body.lower() and "<script" in body.lower():
                return body, used
        elif c.language in {"javascript", "typescript"} or _placement(c) == "script":
            scripts.append(body)
        else:
            # skip unrelated python for browser compose
            continue

    scripts = [s for s in scripts if s and len(s.strip()) > 20]
    if not scripts:
        return "", used

    css = "\n".join(styles) if styles else (
        "body{margin:0;font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0}"
        "main{max-width:960px;margin:0 auto;padding:16px}"
        "canvas{background:#1e293b;border-radius:12px;max-width:100%}"
        "button{padding:10px 14px;border:0;border-radius:8px;background:#334155;color:inherit}"
    )
    # structural frame only — not a specific game
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <div id="app"></div>
  <canvas id="c" width="400" height="400" aria-label="view"></canvas>
  <p><button id="restart" type="button">Restart</button> <span id="score"></span></p>
</main>
<script>
// composed by SLI from code-memory chunks
{chr(10).join(scripts)}
</script>
</body>
</html>
"""
    return html, used


def compose_python_from_chunks(chunks: list[CodeChunk]) -> tuple[str, list[str]]:
    used = []
    parts = []
    for c in chunks:
        if c.language != "python" and not (c.path or "").endswith(".py"):
            continue
        if _is_test_chunk(c):
            continue
        # prefer module-level complete-ish files
        if "::" in (c.path or "") and len(c.text) < 200:
            continue
        used.append(c.id)
        parts.append(f"# from chunk {c.id} path={c.path}\n{c.text}")
        if sum(len(p) for p in parts) > 8000:
            break
    return ("\n\n".join(parts), used)


def compose_from_request(
    message: str,
    workspace: Path,
    *,
    store: ChunkStore | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[str | None, list[str]]:
    progress = progress or (lambda _m: None)
    store = store or ChunkStore()
    ranked = retrieve_ranked(store, message, top_k=12)
    if not ranked:
        progress("compose: no ranked chunks")
        return None, []

    progress(f"compose: top={ranked[0][0].id} score={ranked[0][1]:.3f}")
    chunks = _browser_safe_chunks([c for c, _ in ranked]) if 'browser' in str(globals().get('intent','')) or True else [c for c, _ in ranked]

    workspace.mkdir(parents=True, exist_ok=True)
    used: list[str] = []
    written: list[Path] = []
    errors: list[str] = []

    if _looks_web(message) or any(c.language == "html" for c in chunks[:5]):
        html, used = compose_browser_from_chunks(message, chunks)
        if not html:
            progress("compose: browser compose produced empty body")
            return None, used
        errors.extend(_validate_html(html))
        # require some interactivity for "game" requests
        if _looks_browser_game(message):
            low = html.lower()
            if "canvas" not in low:
                errors.append("game request missing canvas")
            if "keydown" not in low and "touchstart" not in low and "addEventListener" not in html:
                errors.append("game request missing input handlers")
            if len(html) < 600:
                errors.append("game assembly too small to be useful")
        target = workspace / "index.html"
        target.write_text(html, encoding="utf-8")
        written.append(target)
    else:
        py, used = compose_python_from_chunks(chunks)
        if not py:
            # fallback: write best single non-test chunk as-is if complete enough
            for c, s in ranked:
                if _is_test_chunk(c):
                    continue
                if len(c.text) < 120:
                    continue
                used = [c.id]
                name = Path((c.path or "snippet.txt").split("::")[0]).name or "snippet.txt"
                target = workspace / name
                target.write_text(c.text, encoding="utf-8")
                written.append(target)
                if c.language == "python":
                    errors.extend(_validate_python(c.text))
                break
        else:
            errors.extend(_validate_python(py))
            target = workspace / "main.py"
            target.write_text(py, encoding="utf-8")
            written.append(target)

    if not written:
        return None, used

    success = not errors
    try:
        apply_outcome(store, used, success=success, strength=0.12 if success else 0.15)
    except Exception:
        pass

    # optional open browser for html success
    if success and any(p.suffix == ".html" for p in written):
        try:
            from sophyane import execution_runtime as runtime
            runtime.execute_action({"type": "open_browser"}, workspace, progress)
        except Exception:
            pass

    report = [
        "SLI composed from code-memory chunks (no hardcoded product template).",
        f"Request: {message}",
        f"Used: {', '.join(used)}",
        f"Files: {', '.join(p.name for p in written)}",
        f"Success: {success}",
    ]
    if errors:
        report.append("Validation:")
        report.extend(f"  - {e}" for e in errors[:10])
    return "\n".join(report), used

def _browser_safe_chunks(chunks):
    out = []
    for c in chunks:
        lang = (getattr(c, "language", None) or "").lower()
        path = (getattr(c, "path", None) or "").lower()
        place = str((getattr(c, "meta", None) or {}).get("placement") or "")
        if lang == "python" or path.endswith(".py") or place == "python_module":
            continue
        if "editable_canvas" in path:
            continue
        out.append(c)
    return out

