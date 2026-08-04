
"""Assemble code from weighted memory: prefer rich chunks, expand parts, validate."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from sophyane.code_memory.store import ChunkStore, CodeChunk
from sophyane.code_memory.learner import apply_outcome


def _is_rich(c: CodeChunk) -> bool:
    return (c.meta or {}).get("kind") == "rich"


def _expand(store: ChunkStore, chunk: CodeChunk) -> list[CodeChunk]:
    """Expand a rich chunk into ordered simple parts; simples stay themselves."""
    meta = chunk.meta or {}
    parts = list(meta.get("parts") or meta.get("defined_by") or [])
    if not parts:
        return [chunk]
    out: list[CodeChunk] = []
    for pid in parts:
        child = store.chunks.get(pid)
        if child is not None:
            out.extend(_expand(store, child))
    return out or [chunk]


def _validate_chunk_text(text: str, language: str, checks: list[str]) -> list[str]:
    errors: list[str] = []
    low = text.lower()
    for check in checks or []:
        if check == "has_html" and "<html" not in low:
            errors.append("missing <html>")
        if check == "has_canvas" and "canvas" not in low:
            errors.append("missing canvas")
        if check == "python_compile" and language == "python":
            try:
                compile(text, "<chunk>", "exec")
            except SyntaxError as e:
                errors.append(f"python syntax: {e}")
        if check == "js_balanced_braces":
            if text.count("{") != text.count("}"):
                errors.append("unbalanced JS braces")
    # always light sanity
    if language == "python" and text.strip():
        try:
            compile(text, "<chunk>", "exec")
        except SyntaxError as e:
            if f"python syntax: {e}" not in errors:
                errors.append(f"python syntax: {e}")
    return errors


def _pick_filename(chunk: CodeChunk, index: int) -> str:
    placement = (chunk.meta or {}).get("placement") or chunk.placement if hasattr(chunk, "placement") else ""
    placement = (chunk.meta or {}).get("placement") or "fragment"
    path = chunk.path or ""
    name = Path(path.split("::")[0]).name if path else ""
    if placement == "html_document" or chunk.language == "html" or "<html" in chunk.text.lower():
        return "index.html"
    if chunk.language == "python":
        base = name if name.endswith(".py") else (name or f"module_{index}.py")
        if not base.endswith(".py"):
            base += ".py"
        # function chunks still go into a module file name from path
        return base.replace("::", "_")
    if chunk.language in {"javascript", "typescript"}:
        return name if name.endswith((".js", ".ts")) else f"script_{index}.js"
    if chunk.language == "css":
        return name if name.endswith(".css") else f"style_{index}.css"
    return name or f"chunk_{index}.txt"


def assemble_from_request(
    message: str,
    workspace: Path,
    *,
    store: ChunkStore | None = None,
    top_k: int = 6,
    progress: Callable[[str], None] | None = None,
) -> tuple[str | None, list[str]]:
    """Retrieve (prefer rich), expand, emit, validate, return report + used ids."""
    progress = progress or (lambda _m: None)
    store = store or ChunkStore()
    hits = store.retrieve(message, top_k=top_k)
    if not hits:
        return None, []

    # Prefer rich chunks among top hits
    rich_hits = [(c, s) for c, s in hits if _is_rich(c)]
    chosen_pairs = rich_hits[:1] if rich_hits else hits[:1]
    progress(
        f"Assembler: selected {chosen_pairs[0][0].id} "
        f"({'rich' if _is_rich(chosen_pairs[0][0]) else 'simple'}) score={chosen_pairs[0][1]:.3f}"
    )

    used_ids: list[str] = []
    leaf_chunks: list[CodeChunk] = []
    for chunk, _score in chosen_pairs:
        used_ids.append(chunk.id)
        expanded = _expand(store, chunk)
        for ch in expanded:
            if ch.id not in used_ids:
                used_ids.append(ch.id)
            leaf_chunks.append(ch)

    workspace.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    errors: list[str] = []

    # Emit: group python function leaves by module filename when possible
    emitted_text: dict[str, list[str]] = {}
    for i, ch in enumerate(leaf_chunks):
        fname = _pick_filename(ch, i)
        emitted_text.setdefault(fname, []).append(ch.text)
        checks = list((ch.meta or {}).get("checks") or [])
        errs = _validate_chunk_text(ch.text, ch.language, checks)
        for e in errs:
            errors.append(f"{ch.id}: {e}")

    for fname, parts in emitted_text.items():
        target = workspace / fname
        # avoid duplicating identical bodies
        uniq_parts = []
        seen = set()
        for p in parts:
            h = hash(p)
            if h not in seen:
                seen.add(h)
                uniq_parts.append(p)
        body = "\n\n".join(uniq_parts)
        target.write_text(body, encoding="utf-8")
        written.append(target)
        progress(f"Assembler: wrote {fname} ({target.stat().st_size} bytes)")

    success = bool(written) and not any("syntax" in e for e in errors)
    try:
        apply_outcome(store, used_ids, success=success, strength=0.1 if success else 0.12)
    except Exception:
        pass

    report_lines = [
        "Sophyane assembler (rich→simple expansion, validate, weight update)",
        f"Request: {message}",
        f"Used chunks: {', '.join(used_ids)}",
        f"Files: {', '.join(p.name for p in written)}",
        f"Success: {success}",
    ]
    if errors:
        report_lines.append("Validation issues:")
        report_lines.extend(f"  - {e}" for e in errors[:12])
    return "\n".join(report_lines), used_ids
