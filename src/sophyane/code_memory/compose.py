 # BLOCK_PYTHON_IN_BROWSER_COMPOSE

"""Compose artifacts from retrieved chunks — no product-specific hardcoding.

Uses:
- retrieval over weighted code memory
- filters (drop tests unless asked)
- placement roles (html_document / script / style / module)
- generic document frames only (structure), bodies come from chunks
"""
from __future__ import annotations

import ast
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



# SOPHYANE_PYTHON_FUTURE_IMPORT_NORMALIZATION_V1
#
# Independently valid Python modules may each contain __future__ imports.
# When components are concatenated those imports can no longer remain at
# their original offsets. Extract them from component bodies, preserve
# feature order with stable deduplication, and emit one module preamble.
def _split_python_future_imports(
    source: str,
) -> tuple[str, list[str]]:
    try:
        tree = ast.parse(source)
    except (
        SyntaxError,
        ValueError,
        TypeError,
    ):
        return source, []

    future_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
    ]

    if not future_nodes:
        return source, []

    features: list[str] = []

    for node in future_nodes:
        for alias in node.names:
            feature = alias.name

            if alias.asname:
                feature = (
                    f"{feature} as {alias.asname}"
                )

            if feature not in features:
                features.append(feature)

    source_lines = source.splitlines(
        keepends=True,
    )

    remove_lines: set[int] = set()

    for node in future_nodes:
        start = node.lineno - 1
        end = (
            node.end_lineno
            if node.end_lineno is not None
            else node.lineno
        )

        remove_lines.update(
            range(start, end)
        )

    body = "".join(
        line
        for index, line in enumerate(source_lines)
        if index not in remove_lines
    )

    return body, features


def _merge_python_future_features(
    existing: list[str],
    additions: list[str],
) -> list[str]:
    merged = list(existing)
    seen = set(merged)

    for feature in additions:
        if feature in seen:
            continue

        seen.add(feature)
        merged.append(feature)

    return merged


def _python_future_preamble(
    features: list[str],
) -> str:
    if not features:
        return ""

    return (
        "from __future__ import "
        + ", ".join(features)
    )


def _assemble_python_parts(
    parts: list[str],
    future_features: list[str],
) -> str:
    body = "\n\n".join(parts)
    preamble = _python_future_preamble(
        future_features
    )

    if preamble and body:
        return preamble + "\n\n" + body

    return preamble or body


def compose_python_from_chunks(
    chunks: list[CodeChunk],
    *,
    root_ids: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Assemble bounded, syntactically valid Python components."""

    # SOPHYANE_PYTHON_AUTHORITATIVE_ROOTS_V2
    #
    # When semantic roots are known, assemble only those roots
    # plus their transitive requires -> provides dependencies.
    #
    # root_ids=None intentionally preserves historical behavior.
    if root_ids is not None:
        requested_root_ids = {
            str(chunk_id)
            for chunk_id in root_ids
        }

        def _chunk_id(chunk):
            return str(
                getattr(chunk, "id", "")
                or ""
            )

        def _meta_values(chunk, key):
            meta = getattr(
                chunk,
                "meta",
                None,
            )

            if not isinstance(meta, dict):
                return set()

            values = meta.get(
                key,
                (),
            )

            if isinstance(values, str):
                values = (values,)

            if not isinstance(
                values,
                (
                    list,
                    tuple,
                    set,
                    frozenset,
                ),
            ):
                return set()

            return {
                str(value)
                for value in values
                if str(value)
            }

        by_id = {
            _chunk_id(chunk): chunk
            for chunk in chunks
            if _chunk_id(chunk)
        }

        selected_ids = {
            chunk_id
            for chunk_id in requested_root_ids
            if chunk_id in by_id
        }

        provides_by_id = {
            chunk_id: _meta_values(
                chunk,
                "provides",
            )
            for chunk_id, chunk in by_id.items()
        }

        requires_by_id = {
            chunk_id: _meta_values(
                chunk,
                "requires",
            )
            for chunk_id, chunk in by_id.items()
        }

        while True:
            required = set()

            for chunk_id in selected_ids:
                required.update(
                    requires_by_id.get(
                        chunk_id,
                        set(),
                    )
                )

            provided = set()

            for chunk_id in selected_ids:
                provided.update(
                    provides_by_id.get(
                        chunk_id,
                        set(),
                    )
                )

            unresolved = required - provided

            if not unresolved:
                break

            additions = []

            # Preserve incoming semantic candidate order.
            for chunk in chunks:
                chunk_id = _chunk_id(chunk)

                if (
                    not chunk_id
                    or chunk_id in selected_ids
                ):
                    continue

                if (
                    provides_by_id.get(
                        chunk_id,
                        set(),
                    )
                    & unresolved
                ):
                    additions.append(
                        chunk_id
                    )

            if not additions:
                break

            selected_ids.update(
                additions
            )

        chunks = [
            chunk
            for chunk in chunks
            if _chunk_id(chunk) in selected_ids
        ]


    # SOPHYANE_PYTHON_COMPONENT_ASSEMBLY_V1
    #
    # Semantic retrieval may contain rich/compound evidence bundles.
    # Those bundles are useful for retrieval but are not themselves
    # executable Python modules. Only executable standalone component
    # source is admitted here.
    used: list[str] = []
    parts: list[str] = []
    future_import_features: list[str] = []

    # SOPHYANE_PYTHON_AUTHORITATIVE_ROOT_BUDGET_V1
    #
    # Ordinary candidate composition retains the historical
    # 32 KB ceiling. Explicit semantic root assembly receives
    # a larger but still bounded envelope so independently
    # valid authoritative roots are not silently treated as
    # optional candidates solely because of aggregate size.
    max_total_bytes = (
        64 * 1024
        if root_ids is not None
        else 32_000
    )
    max_component_bytes = 16_000
    total_bytes = 0

    for chunk in chunks:
        language = str(
            getattr(chunk, "language", "")
            or ""
        ).lower()

        chunk_path = str(
            getattr(chunk, "path", "")
            or ""
        )

        source = str(
            getattr(chunk, "text", "")
            or ""
        )

        if (
            language != "python"
            and not chunk_path.endswith(".py")
        ):
            continue

        if _is_test_chunk(chunk):
            continue

        # Rich/compound bundles contain retrieval metadata and multiple
        # source files. They must be decomposed upstream rather than copied
        # verbatim into one Python module.
        if (
            chunk_path.startswith("compound::")
            or "/* RICH CHUNK:" in source
            or "/* part:" in source
        ):
            continue

        if not source.strip():
            continue

        (
            source,
            chunk_future_features,
        ) = _split_python_future_imports(
            source
        )

        if (
            not source.strip()
            and not chunk_future_features
        ):
            continue

        component_bytes = len(
            source.encode(
                "utf-8",
                errors="replace",
            )
        )

        # One giant source file must not consume the entire component
        # budget and prevent smaller capability implementations from
        # participating.
        if component_bytes > max_component_bytes:
            continue

        individual_source = (
            _assemble_python_parts(
                [source],
                chunk_future_features,
            )
        )

        try:
            compile(
                individual_source,
                f"<chunk:{chunk.id}>",
                "exec",
            )
        except (
            SyntaxError,
            ValueError,
            TypeError,
        ):
            continue

        decorated = (
            f"# from chunk {chunk.id} "
            f"path={chunk_path}\n"
            f"{source}"
        )

        decorated_bytes = len(
            decorated.encode(
                "utf-8",
                errors="replace",
            )
        )

        if (
            total_bytes + decorated_bytes
            > max_total_bytes
        ):
            continue

        # Validate incrementally. Future imports from independently
        # valid modules are hoisted into one shared module preamble.
        candidate_future_features = (
            _merge_python_future_features(
                future_import_features,
                chunk_future_features,
            )
        )

        candidate = _assemble_python_parts(
            parts + [decorated],
            candidate_future_features,
        )

        try:
            compile(
                candidate,
                "<assembled>",
                "exec",
            )
        except (
            SyntaxError,
            ValueError,
            TypeError,
        ):
            continue

        parts.append(decorated)
        used.append(chunk.id)
        future_import_features = (
            candidate_future_features
        )
        total_bytes += decorated_bytes

    return (
        _assemble_python_parts(
            parts,
            future_import_features,
        ),
        used,
    )


def compose_from_request(
    message: str,
    workspace: Path,
    *,
    store: ChunkStore | None = None,
    progress: Callable[[str], None] | None = None,
    selected_ids: list[str] | None = None,
root_ids=None) -> tuple[str | None, list[str]]:
    progress = progress or (lambda _m: None)
    store = store or ChunkStore()

    # SOPHYANE_SEMANTIC_ASSEMBLY_BRIDGE_V1
    #
    # The semantic planner has already performed per-capability retrieval.
    # Preserve that evidence across the assembly boundary instead of
    # discarding it and performing an unrelated global top-k retrieval.
    #
    # Deduplication is stable so capability priority/order survives.
    semantic_ranked = []
    semantic_seen = set()

    for chunk_id in selected_ids or []:
        chunk_id = str(chunk_id)

        if chunk_id in semantic_seen:
            continue

        chunk = store.chunks.get(chunk_id)
        if chunk is None:
            continue

        semantic_seen.add(chunk_id)
        semantic_ranked.append((chunk, 1.0))

    if semantic_ranked:
        ranked = semantic_ranked
        progress(
            "compose: semantic bridge selected "
            f"{len(ranked)} capability chunks"
        )
    else:
        ranked = retrieve_ranked(store, message, top_k=12)
    if not ranked:
        progress("compose: no ranked chunks")
        return None, []

    progress(f"compose: top={ranked[0][0].id} score={ranked[0][1]:.3f}")
    # SOPHYANE_GENERIC_COMPOSER_ARTIFACT_AUTHORITY_V1
    #
    # Artifact family comes from request semantics, never from incidental
    # retrieved languages.  The historical `or True` forced every request
    # through browser-safe filtering and discarded Python candidates.
    try:
        from sophyane.sli_semantic_intelligence import (
            infer_target,
        )

        _target_language, _target_artifact = infer_target(
            message
        )
    except Exception:
        _target_language = None
        _target_artifact = None

    _browser_request = (
        _target_artifact
        == "browser_application"
        or _looks_web(message)
    )

    chunks = (
        _browser_safe_chunks(
            [c for c, _ in ranked]
        )
        if _browser_request
        else [c for c, _ in ranked]
    )

    workspace.mkdir(parents=True, exist_ok=True)
    used: list[str] = []
    written: list[Path] = []
    errors: list[str] = []

    if _browser_request:
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
        py, used = compose_python_from_chunks(chunks, root_ids=root_ids)
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

