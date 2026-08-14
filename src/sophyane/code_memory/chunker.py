
"""Split source files into code chunks with coarse I/O + placement."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

@dataclass
class RawChunk:
    text: str
    language: str
    path: str
    tags: list[str] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)
    placement: str = "fragment"
    checks: list[str] = field(default_factory=list)

_PY_DEF = re.compile(r"^(async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*:", re.M)
_JS_FN = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*\{|"
    r"(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>",
    re.M,
)

def _lang(path: Path) -> str:
    return {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".html": "html",
        ".css": "css",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".h": "cpp",
        ".hpp": "cpp",
        ".hh": "cpp",
        ".hxx": "cpp",
        ".rs": "rust",
    }.get(path.suffix.lower(), "")

def _infer_html(text: str, path: str) -> list[RawChunk]:
    low = text.lower()
    tags = []
    if "canvas" in low: tags.append("canvas")
    if "snake" in low: tags.append("snake")
    if any(k in low for k in ("game", "keydown", "requestanimationframe")): tags.append("game")
    outputs = []
    if "canvas" in low:
        outputs.append({"name": "canvas", "type": "HTMLCanvasElement"})
    if "keydown" in low or "keyup" in low:
        outputs.append({"name": "keyboard", "type": "input_source"})
        tags.append("keyboard")
    checks = []
    if "<html" in low: checks.append("has_html")
    if "canvas" in low: checks.append("has_canvas")
    return [RawChunk(
        text=text, language="html", path=path, tags=tags or ["html"],
        outputs=outputs,
        placement="html_document" if "<html" in low else "fragment",
        checks=checks,
    )]

def _infer_python(text: str, path: str) -> list[RawChunk]:
    chunks = [RawChunk(
        text=text, language="python", path=path, tags=["python", "module"],
        outputs=[{"name": Path(path).stem, "type": "python_module"}],
        placement="python_module", checks=["python_compile"],
    )]
    matches = list(_PY_DEF.finditer(text))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if len(body) < 40:
            continue
        name = m.group(2)
        args = m.group(3)
        inputs = [{"name": a.strip().split("=")[0].strip(), "type": "any"}
                  for a in args.split(",") if a.strip() and a.strip() != "self"]
        chunks.append(RawChunk(
            text=body, language="python", path=f"{path}::{name}",
            tags=["python", "function", name], inputs=inputs,
            outputs=[{"name": name, "type": "function"}],
            placement="function", checks=["python_compile"],
        ))
    return chunks

def _infer_js(text: str, path: str) -> list[RawChunk]:
    chunks = [RawChunk(
        text=text, language="javascript", path=path, tags=["javascript"],
        placement="script", checks=["js_balanced_braces"],
    )]
    for m in _JS_FN.finditer(text):
        name = m.group(1) or m.group(3)
        if not name:
            continue
        chunks.append(RawChunk(
            text=m.group(0), language="javascript", path=f"{path}::{name}",
            tags=["javascript", "function", name],
            outputs=[{"name": name, "type": "function"}],
            placement="function", checks=["js_balanced_braces"],
        ))
    return chunks

def chunk_file(path: Path) -> list[RawChunk]:
    path = path.expanduser()
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if len(text) < 40 or len(text) > 300_000:
        return []
    lang = _lang(path)
    rel = str(path)
    if lang == "html":
        return _infer_html(text, rel)
    if lang == "python":
        return _infer_python(text, rel)
    if lang in {"javascript", "typescript"}:
        return _infer_js(text, rel)
    if lang == "css":
        return [RawChunk(text=text, language="css", path=rel, tags=["css"], placement="style")]
    return [RawChunk(text=text, language=lang or "text", path=rel, tags=[lang or "text"], placement="fragment")]

def iter_source_files(root: Path) -> Iterator[Path]:
    root = root.expanduser().resolve()
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
    for pat in (
        "*.py",
        "*.js",
        "*.ts",
        "*.html",
        "*.css",
        "*.cpp",
        "*.cc",
        "*.cxx",
        "*.h",
        "*.hpp",
        "*.hh",
        "*.hxx",
        "*.rs",
    ):
        for p in root.rglob(pat):
            if any(part in skip for part in p.parts):
                continue
            yield p
