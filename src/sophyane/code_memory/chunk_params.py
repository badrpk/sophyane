"""SLI generation as patching discrete code-chunk parameters (no LLM).

Each chunk is an unbreaking parameter:
  - id, weight, provides[], requires[], text, language, placement

Generation:
  1) read request → required capability set (small discrete needs)
  2) pick one chunk per need (weight × contract match)  [O(needs × catalog)]
  3) patch texts into one artifact by placement slots
  4) optional outcome weight update

This is not token generation and not transformer training.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from sophyane.code_memory.store import ChunkStore

Progress = Callable[[str], None]

# Discrete needs the linker knows how to ask for (parameters of the product)
NEED_SIGNALS: dict[str, tuple[str, ...]] = {
    "document_shell": ("<!doctype", "<html", "<body", "document_shell"),
    "presentation": ("<style", "css", "class=", "presentation"),
    "user_input": ("addEventListener", "keydown", "onclick", "input", "button"),
    "application_state": ("createState", "let state", "const state", "score"),
    "rules_validation": ("validate", "correct", "expected", "assert"),
    "progress_feedback": ("score", "feedback", "textContent"),
    "rendering": ("render", "innerHTML", "getContext", "canvas"),
    "game_loop": ("requestAnimationFrame", "setInterval", "game_loop"),
    "entry_point": ("DOMContentLoaded", "start", "main(", "onload"),
    "error_handling": ("try:", "except ", "PermissionError", "raise "),
    "http_endpoint": ("FastAPI", "@app.", "Flask", "APIRouter"),
    "python_module": ("^def ", "^class ", "from __future__"),
}

REQUEST_NEEDS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("website", "webpage", "informational", "about ", " on "),
     ("document_shell", "presentation", "entry_point")),
    (("snake", "pong", "game", "playable", "canvas"),
     ("document_shell", "user_input", "rendering", "game_loop", "application_state", "entry_point")),
    (("missing word", "missing letter", "quiz", "exercise"),
     ("document_shell", "user_input", "application_state", "rules_validation", "progress_feedback", "entry_point")),
    (("python", "implement", ".py", "fastapi", "audit_chain", "policy_engine", "sandbox"),
     ("python_module", "error_handling")),
]


@dataclass
class Param:
    """One unbreaking code parameter."""
    id: str
    weight: float
    provides: set[str]
    requires: set[str]
    text: str
    language: str
    path: str
    score: float = 0.0


def _meta_set(meta: dict, *keys: str) -> set[str]:
    out: set[str] = set()
    for k in keys:
        for x in meta.get(k) or []:
            s = str(x).strip()
            if s:
                out.add(s)
    return out


def _infer_provides(text: str, meta: dict) -> set[str]:
    got = _meta_set(meta, "provides", "roles")
    low = text.lower()
    for need, signals in NEED_SIGNALS.items():
        for sig in signals:
            if sig.startswith("^"):
                if re.search(sig, text, flags=re.M):
                    got.add(need)
                    break
            elif sig.lower() in low:
                got.add(need)
                break
    return got


def needs_for_request(request: str) -> list[str]:
    r = (request or "").lower()
    for keys, needs in REQUEST_NEEDS:
        if any(k in r for k in keys):
            return list(needs)
    # generic browser page
    if any(k in r for k in ("html", "page", "site", "ui")):
        return ["document_shell", "presentation", "entry_point"]
    return ["document_shell", "user_input", "entry_point"]


def catalog(store: ChunkStore, limit: int = 0) -> list[Param]:
    """Materialize chunks as discrete parameters (exclude poisoned)."""
    params: list[Param] = []
    ids = list(store.ids)
    if limit:
        ids = ids[:limit]
    for cid in ids:
        c = store.chunks.get(cid)
        if c is None:
            continue
        meta = dict(getattr(c, "meta", None) or {})
        if meta.get("exclude"):
            continue
        text = str(getattr(c, "text", "") or "")
        if len(text) < 40:
            continue
        # Prefer bounded parameters; skip giant dumps for patching core
        if len(text) > 80_000:
            continue
        provides = _infer_provides(text, meta)
        requires = _meta_set(meta, "requires")
        w = float(getattr(c, "weight", 1.0) or 1.0)
        params.append(
            Param(
                id=str(cid),
                weight=w,
                provides=provides,
                requires=requires,
                text=text,
                language=str(getattr(c, "language", "") or ""),
                path=str(getattr(c, "path", "") or ""),
            )
        )
    return params


def pick_params(
    params: list[Param],
    needs: Iterable[str],
    request: str,
) -> dict[str, Param]:
    """One parameter per need. Score = weight × need hit × light request overlap."""
    req_toks = set(re.findall(r"[a-z0-9_]{3,}", (request or "").lower()))
    chosen: dict[str, Param] = {}
    used_ids: set[str] = set()
    for need in needs:
        best: Param | None = None
        best_score = -1.0
        for p in params:
            if p.id in used_ids:
                continue
            if need not in p.provides:
                continue
            # domain soft filter
            if need == "python_module" and p.language and p.language != "python":
                continue
            if need == "document_shell" and p.language and p.language not in ("html", "htm", ""):
                # allow html-ish text
                if "<html" not in p.text.lower() and "<!doctype" not in p.text.lower():
                    continue
            overlap = 0.0
            if req_toks:
                pt = set(re.findall(r"[a-z0-9_]{3,}", (p.path + " " + p.text[:1500]).lower()))
                overlap = len(req_toks & pt) / max(4, len(req_toks))
            score = float(p.weight) * (1.0 + 0.5 * overlap)
            # prefer smaller unbreaking units
            score *= 1.0 / (1.0 + len(p.text) / 50_000.0)
            if score > best_score:
                best_score = score
                best = p
                best.score = score
        if best is not None:
            chosen[need] = best
            used_ids.add(best.id)
    return chosen


def _strip_outer_html(text: str) -> str:
    t = text.strip()
    # if full document, extract body inner if possible
    m = re.search(r"<body[^>]*>(.*)</body>", t, flags=re.I | re.S)
    if m:
        return m.group(1).strip()
    return t


def _extract_scripts_styles(text: str) -> tuple[str, str, str]:
    styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, flags=re.I | re.S))
    scripts = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.I | re.S))
    body = _strip_outer_html(text)
    body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.I | re.S)
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.I | re.S)
    return styles, scripts, body.strip()


def patch_html(request: str, chosen: dict[str, Param]) -> str:
    """Patch selected parameters into one self-contained HTML file."""
    title = re.sub(r"\s+", " ", request.strip())[:80] or "SLI patch product"
    style_parts: list[str] = []
    script_parts: list[str] = []
    body_parts: list[str] = []
    for need, p in chosen.items():
        if p.language == "python":
            continue
        st, sc, body = _extract_scripts_styles(p.text)
        if st:
            style_parts.append(f"/* param {p.id} need={need} */\n{st}")
        if sc:
            script_parts.append(f"/* param {p.id} need={need} */\n{sc}")
        if body and need in ("document_shell", "presentation", "rendering", "user_input"):
            body_parts.append(f"<!-- param {p.id} need={need} -->\n{body}")
    if not body_parts:
        body_parts.append(f"<main><h1>{title}</h1><p>Patched from SLI chunk parameters.</p></main>")
    css = "\n\n".join(style_parts) or "body{font-family:system-ui;margin:2rem}"
    js = "\n\n".join(script_parts)
    body_html = "\n".join(body_parts)
    return f"""<!doctype html>
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
{body_html}
<script>
{js}
</script>
</body>
</html>
"""


def patch_python(request: str, chosen: dict[str, Param]) -> tuple[str, str]:
    """Concatenate python module parameters (simple linear patch)."""
    blocks: list[str] = [
        '"""SLI chunk-parameter patch assembly."""',
        "from __future__ import annotations",
    ]
    name = "module.py"
    low = request.lower()
    for key in ("audit_chain", "policy_engine", "sandbox_guard", "retry_controller", "capability_solver"):
        if key in low.replace("-", "_"):
            name = f"{key}.py"
            break
    for need, p in chosen.items():
        if p.language and p.language != "python" and "def " not in p.text:
            continue
        blocks.append(f"\n# --- param {p.id} need={need} weight={p.weight:.3f} ---\n")
        # drop duplicate futures
        t = re.sub(r"from __future__ import annotations\n?", "", p.text)
        blocks.append(t.strip())
    return name, "\n\n".join(blocks).strip() + "\n"


def generate_by_patch(
    request: str,
    workspace: Path,
    *,
    store: ChunkStore | None = None,
    progress: Progress | None = None,
) -> tuple[str, list[str]]:
    progress = progress or (lambda _m: None)
    store = store or ChunkStore()
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    needs = needs_for_request(request)
    progress(f"chunk-params: needs={needs}")
    params = catalog(store)
    progress(f"chunk-params: catalog size={len(params)} (bounded, non-excluded)")
    chosen = pick_params(params, needs, request)
    missing = [n for n in needs if n not in chosen]
    progress(
        "chunk-params: selected "
        + ", ".join(f"{n}:{chosen[n].id}:{chosen[n].score:.2f}" for n in chosen)
    )
    if missing:
        progress(f"chunk-params: missing parameters {missing}")

    used = [p.id for p in chosen.values()]
    low = request.lower()
    pythonish = any(k in low for k in ("python", ".py", "implement", "fastapi", "audit_chain", "policy_engine", "sandbox", "retry_controller"))

    if pythonish:
        filename, content = patch_python(request, chosen)
        out = workspace / filename
        out.write_text(content, encoding="utf-8")
        ok = True
        issues: list[str] = []
        try:
            compile(content, str(out), "exec")
        except SyntaxError as e:
            ok = False
            issues.append(str(e))
    else:
        content = patch_html(request, chosen)
        filename = "index.html"
        out = workspace / filename
        out.write_text(content, encoding="utf-8")
        ok = "<html" in content.lower() and len(content) > 200
        issues = [] if ok else ["thin or invalid html patch"]
        if missing and not chosen:
            ok = False
            issues.append("no parameters selected")

    if used:
        try:
            from sophyane.code_memory.learner import apply_outcome
            apply_outcome(store, used, success=ok)
        except Exception:
            pass

    report = (
        "Sophyane SLI chunk-parameter patch generator\n"
        f"Request: {request}\n"
        f"Needs (discrete parameters): {', '.join(needs)}\n"
        f"Selected: {', '.join(f'{k}={v.id}' for k,v in chosen.items()) or '(none)'}\n"
        f"Missing: {', '.join(missing) if missing else 'none'}\n"
        f"Catalog scanned: {len(params)}\n"
        f"Files: {filename}\n"
        f"Success: {ok}\n"
        f"Issues: {'; '.join(issues) if issues else 'none'}\n"
        "Inference: generation = patching unbreaking code chunks; no LLM; no transformer training\n"
    )
    return report, used
