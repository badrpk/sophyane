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
import shutil
import subprocess

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


# SOPHYANE_CPP_SOFTWARE_COMPOSER_V1
def _looks_cpp_request(message: str) -> bool:
    """Return True only when C++ is explicitly the requested language.

    Mixed Python/C++ wording keeps the existing Python-compatible behavior
    until multi-language output is implemented deliberately.
    """
    text = " ".join(
        str(message or "").casefold().split()
    )

    cpp_markers = (
        "c++",
        "cpp",
        "cxx",
        ".cpp",
        "std::",
    )

    python_markers = (
        "python",
        ".py",
        "pytest",
    )

    wants_cpp = any(
        marker in text
        for marker in cpp_markers
    )

    also_python = any(
        marker in text
        for marker in python_markers
    )

    return wants_cpp and not also_python


def _validate_cpp(source: str) -> list[str]:
    """Validate C++ source with the local compiler without producing a binary."""
    errors: list[str] = []

    if not str(source or "").strip():
        return ["empty C++ source"]

    compiler = (
        shutil.which("clang++")
        or shutil.which("g++")
        or shutil.which("c++")
    )

    if compiler is None:
        return [
            "C++ compiler unavailable; expected clang++, g++ or c++"
        ]

    import tempfile

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".cpp",
            encoding="utf-8",
            delete=False,
        ) as handle:
            handle.write(source)
            temporary = Path(handle.name)

        completed = subprocess.run(
            [
                compiler,
                "-std=c++17",
                "-fsyntax-only",
                str(temporary),
            ],
            text=True,
            capture_output=True,
            timeout=30,
        )

        if completed.returncode != 0:
            diagnostic = (
                completed.stderr
                or completed.stdout
                or "C++ syntax validation failed"
            )

            errors.append(
                "C++ syntax validation failed: "
                + " ".join(diagnostic.split())[:1200]
            )

    except Exception as error:
        errors.append(
            "C++ validation error: "
            f"{type(error).__name__}: {error}"
        )

    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return errors



# SOPHYANE_CPP_DEPENDENCY_CLOSURE_V1
_CPP_SOURCE_SUFFIXES = {
    ".cpp",
    ".cc",
    ".cxx",
}

_CPP_HEADER_SUFFIXES = {
    ".h",
    ".hpp",
    ".hh",
    ".hxx",
}


def _cpp_chunk_path(chunk) -> Path | None:
    raw = str(
        getattr(chunk, "path", "")
        or ""
    ).split(
        "::",
        1,
    )[0]

    if not raw:
        return None

    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


def _cpp_common_repository_root(paths: list[Path]) -> Path | None:
    """Infer a stable repository root from acquired C++ chunk paths."""
    if not paths:
        return None

    resolved = [
        path.resolve()
        for path in paths
    ]

    common = Path(
        os.path.commonpath(
            [
                str(path)
                for path in resolved
            ]
        )
    )

    if common.is_file():
        common = common.parent

    # Prefer a conventional project root above src/include/tests.
    while (
        common.name.casefold()
        in {
            "src",
            "include",
            "tests",
            "test",
        }
        and common.parent != common
    ):
        common = common.parent

    return common


def _cpp_include_names(source: str) -> list[str]:
    import re

    return re.findall(
        r'^\s*#\s*include\s*"([^"]+)"',
        str(source or ""),
        flags=re.MULTILINE,
    )


def _cpp_resolve_include(
    including: Path,
    include_name: str,
    *,
    repository_root: Path,
    known_paths: set[Path],
) -> Path | None:
    candidates = [
        including.parent / include_name,
        repository_root / include_name,
        repository_root / "include" / include_name,
        repository_root / "src" / include_name,
    ]

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue

        if resolved in known_paths:
            return resolved

    # Last resort: unique basename match inside acquired C++ memory.
    basename_matches = [
        path
        for path in known_paths
        if path.name == Path(include_name).name
    ]

    if len(basename_matches) == 1:
        return basename_matches[0]

    return None


def _cpp_dependency_closure(
    entry_chunk,
    chunks,
):
    """Return selected translation unit + recursively required quoted headers."""
    entry_path = _cpp_chunk_path(
        entry_chunk
    )

    if entry_path is None:
        return None, [], [
            "selected C++ chunk has no usable source path"
        ]

    by_path = {}

    for chunk in chunks:
        path = _cpp_chunk_path(
            chunk
        )

        if path is None:
            continue

        language = str(
            getattr(chunk, "language", "")
            or ""
        ).casefold()

        if language not in {
            "cpp",
            "c++",
            "cxx",
            "cc",
        }:
            continue

        by_path.setdefault(
            path,
            chunk,
        )

    by_path.setdefault(
        entry_path,
        entry_chunk,
    )

    known_paths = set(
        by_path
    )

    repository_root = _cpp_common_repository_root(
        list(
            known_paths
        )
    )

    if repository_root is None:
        return None, [], [
            "unable to infer C++ repository root"
        ]

    visited = set()
    ordered = []
    errors = []

    def walk(path: Path):
        path = path.resolve()

        if path in visited:
            return

        visited.add(
            path
        )

        chunk = by_path.get(
            path
        )

        if chunk is None:
            errors.append(
                "missing acquired C++ dependency: "
                + str(path)
            )
            return

        ordered.append(
            chunk
        )

        body = str(
            getattr(chunk, "text", "")
            or ""
        )

        for include_name in _cpp_include_names(
            body
        ):
            resolved = _cpp_resolve_include(
                path,
                include_name,
                repository_root=repository_root,
                known_paths=known_paths,
            )

            if resolved is None:
                errors.append(
                    "unresolved quoted include: "
                    + include_name
                    + " from "
                    + str(path)
                )
                continue

            walk(
                resolved
            )

    walk(
        entry_path
    )

    return (
        repository_root,
        ordered,
        errors,
    )


def _materialize_cpp_closure(
    workspace: Path,
    *,
    repository_root: Path,
    chunks,
) -> list[Path]:
    """Copy closure into workspace while preserving repository-relative paths."""
    written = []

    for chunk in chunks:
        source_path = _cpp_chunk_path(
            chunk
        )

        if source_path is None:
            continue

        try:
            relative = source_path.relative_to(
                repository_root
            )
        except ValueError:
            relative = Path(
                source_path.name
            )

        target = (
            workspace
            / relative
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            str(
                getattr(chunk, "text", "")
                or ""
            ).rstrip()
            + "\n",
            encoding="utf-8",
        )

        written.append(
            target
        )

    return written


def _validate_cpp_workspace(
    entry: Path,
    *,
    workspace: Path,
) -> list[str]:
    """Validate a materialized C++ artifact with local include roots."""
    compiler = (
        shutil.which("clang++")
        or shutil.which("g++")
        or shutil.which("c++")
    )

    if compiler is None:
        return [
            "C++ compiler unavailable; expected clang++, g++ or c++"
        ]

    command = [
        compiler,
        "-std=c++17",
        "-fsyntax-only",
        "-I",
        str(workspace),
        "-I",
        str(workspace / "include"),
        "-I",
        str(workspace / "src"),
        str(entry),
    ]

    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except Exception as error:
        return [
            "C++ validation error: "
            f"{type(error).__name__}: {error}"
        ]

    if completed.returncode == 0:
        return []

    diagnostic = (
        completed.stderr
        or completed.stdout
        or "C++ syntax validation failed"
    )

    return [
        "C++ syntax validation failed: "
        + " ".join(
            diagnostic.split()
        )[:1600]
    ]


def _compose_cpp_with_closure(chunks):
    """Select a C++ entry unit and resolve its acquired quoted-header closure."""
    compatible = []

    for chunk in chunks:
        language = str(
            getattr(chunk, "language", "") or ""
        ).casefold()

        if language not in {
            "cpp",
            "c++",
            "cxx",
            "cc",
        }:
            continue

        try:
            if _is_test_chunk(chunk):
                continue
        except Exception:
            pass

        body = str(
            getattr(chunk, "text", "") or ""
        ).strip()

        path = _cpp_chunk_path(
            chunk
        )

        suffix = (
            path.suffix.casefold()
            if path is not None
            else ""
        )

        has_main = (
            "int main(" in body
            or "int main (" in body
        )

        implementation_signal = any(
            marker in body
            for marker in (
                "#include",
                "int main(",
                "int main (",
                "class ",
                "struct ",
                "namespace ",
                "std::",
            )
        )

        if not implementation_signal:
            continue

        # SOPHYANE_CPP_SHORT_ENTRYPOINT_V1
        #
        # A runnable C++ translation unit can legitimately be compact.
        # Preserve the old fragment-quality floor for ordinary chunks,
        # but never reject a structurally explicit main() solely because
        # its source is shorter than 120 characters.
        if (
            len(body) < 120
            and not has_main
        ):
            continue

        compatible.append(
            (
                chunk,
                suffix,
                has_main,
            )
        )

    if not compatible:
        return None, [], None, [], [
            "no compatible C++ implementation chunk found"
        ]

    # Prefer a runnable non-test translation unit with main().
    compatible.sort(
        key=lambda item: (
            not item[2],
            item[1] not in _CPP_SOURCE_SUFFIXES,
        )
    )

    chosen = compatible[0][0]

    repository_root, closure, errors = (
        _cpp_dependency_closure(
            chosen,
            chunks,
        )
    )

    used = [
        str(
            getattr(chunk, "id", "")
        )
        for chunk in closure
        if getattr(chunk, "id", None)
    ]

    return (
        str(chosen.text).strip() + "\n",
        used,
        repository_root,
        closure,
        errors,
    )


def compose_cpp_from_chunks(chunks):
    """Backward-compatible C++ composer.

    Public callers historically receive exactly:
        (source, used_ids)

    Dependency-aware internal callers use
    _compose_cpp_with_closure() for repository root,
    recursive header closure and validation diagnostics.
    """
    (
        source,
        used,
        _repository_root,
        _closure,
        _errors,
    ) = _compose_cpp_with_closure(
        chunks
    )

    return source, used


def compose_from_request(
    message: str,
    workspace: Path,
    *,
    store: ChunkStore | None = None,
    progress: Callable[[str], None] | None = None,
    selected_ids: list[str] | None = None,
    root_ids: list[str] | None = None,
) -> tuple[str | None, list[str]]:
    progress = progress or (lambda _m: None)
    store = store or ChunkStore()

    # SOPHYANE_AUTHORITATIVE_SELECTED_IDS_FORWARDING_V1
    #
    # When the semantic capability engine has already selected an
    # authoritative ordered candidate set, do not re-rank against the
    # entire store and accidentally replace those roots.
    if selected_ids is not None:
        ranked = []

        store_chunks = getattr(
            store,
            "chunks",
            {},
        )

        for chunk_id in selected_ids:
            chunk = store_chunks.get(
                str(chunk_id)
            )

            if chunk is None:
                continue

            # The numerical score is irrelevant in this path; ranking order
            # is the authoritative selected_ids order.
            ranked.append(
                (
                    chunk,
                    1.0,
                )
            )

    else:
        ranked = retrieve_ranked(
            store,
            message,
            top_k=12,
        )

    if not ranked:
        progress("compose: no ranked chunks")
        return None, []

    progress(
        f"compose: top={ranked[0][0].id} "
        f"score={ranked[0][1]:.3f}"
    )
    # SOPHYANE_NON_BROWSER_SOFTWARE_COMPOSER_V1
    #
    # Never force browser-safe chunks globally. The previous `or True`
    # made every request, including Python/C++ software requests, enter
    # browser-oriented retrieval.
    ranked_chunks = [c for c, _ in ranked]

    if _looks_web(message):
        chunks = _browser_safe_chunks(ranked_chunks)
    else:
        chunks = ranked_chunks

    workspace.mkdir(parents=True, exist_ok=True)
    used: list[str] = []
    written: list[Path] = []
    errors: list[str] = []

    # SOPHYANE_NON_BROWSER_SOFTWARE_COMPOSER_V1
    #
    # Artifact family is determined by the USER REQUEST, not by whichever
    # chunk language happened to rank highest. An HTML chunk in retrieval
    # must never turn a Python/C++ request into index.html.
    if _looks_web(message):
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
    elif _looks_cpp_request(message):
        # SOPHYANE_CPP_DEPENDENCY_CLOSURE_V1
        cpp, used, repository_root, closure, cpp_errors = (
            _compose_cpp_with_closure(
                chunks
            )
        )

        errors.extend(
            cpp_errors
        )

        if (
            cpp
            and repository_root is not None
            and closure
        ):
            closure_files = _materialize_cpp_closure(
                workspace,
                repository_root=repository_root,
                chunks=closure,
            )

            written.extend(
                closure_files
            )

            entry_source = _cpp_chunk_path(
                closure[0]
            )

            if entry_source is None:
                errors.append(
                    "selected C++ entry path unavailable"
                )

            else:
                try:
                    entry_relative = entry_source.relative_to(
                        repository_root
                    )
                except ValueError:
                    entry_relative = Path(
                        entry_source.name
                    )

                entry_target = (
                    workspace
                    / entry_relative
                )

                # Preserve the public main.cpp artifact contract as well.
                public_main = (
                    workspace
                    / "main.cpp"
                )

                if entry_target != public_main:
                    public_main.write_text(
                        cpp,
                        encoding="utf-8",
                    )

                    if public_main not in written:
                        written.append(
                            public_main
                        )

                errors.extend(
                    _validate_cpp_workspace(
                        entry_target,
                        workspace=workspace,
                    )
                )

    else:
        py, used = compose_python_from_chunks(
            chunks,
            root_ids=root_ids,
        )

        if not py:
            # fallback: write best single non-test chunk as-is if complete enough
            for c, s in ranked:
                if _is_test_chunk(c):
                    continue

                if len(c.text) < 120:
                    continue

                used = [c.id]

                name = Path(
                    (c.path or "snippet.txt").split("::")[0]
                ).name or "snippet.txt"

                target = workspace / name
                target.write_text(
                    c.text,
                    encoding="utf-8",
                )
                written.append(target)

                if c.language == "python":
                    errors.extend(
                        _validate_python(c.text)
                    )

                break

        else:
            errors.extend(
                _validate_python(py)
            )

            target = workspace / "main.py"
            target.write_text(
                py,
                encoding="utf-8",
            )
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
        # SOPHYANE_RELATIVE_ARTIFACT_REPORT_V1
        "Files: "
        + ", ".join(
            str(
                p.relative_to(workspace)
            )
            if (
                p == workspace
                or workspace in p.parents
            )
            else str(p)
            for p in written
        ),
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

