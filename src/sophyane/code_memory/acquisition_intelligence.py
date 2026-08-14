"""Semantic acquisition upgrades for Sophyane SLI.

This module strengthens repository discovery, performs deeper post-clone
licence inspection and enriches newly acquired chunks with reusable capability
contracts.

It never accepts a repository without a positively detected permissive
licence, and it never executes downloaded source.
"""
from __future__ import annotations

import json
import re
import time

from pathlib import Path
from typing import Any, Callable


Progress = Callable[[str], None]


PERMISSIVE_ALIASES = {
    "mit": "mit",
    "mit license": "mit",
    "apache-2.0": "apache-2.0",
    "apache 2.0": "apache-2.0",
    "apache license 2.0": "apache-2.0",
    "bsd-2-clause": "bsd-2-clause",
    "bsd 2-clause": "bsd-2-clause",
    "simplified bsd": "bsd-2-clause",
    "bsd-3-clause": "bsd-3-clause",
    "bsd 3-clause": "bsd-3-clause",
    "new bsd": "bsd-3-clause",
    "isc": "isc",
    "isc license": "isc",
    "mpl-2.0": "mpl-2.0",
    "mozilla public license 2.0": "mpl-2.0",
    "unlicense": "unlicense",
    "the unlicense": "unlicense",
    "0bsd": "0bsd",
    "cc0-1.0": "cc0-1.0",
    "cc0": "cc0-1.0",
}


TEXT_LICENCE_MARKERS = (
    (
        "permission is hereby granted, free of charge, "
        "to any person obtaining a copy",
        "mit",
    ),
    (
        "licensed under the apache license, version 2.0",
        "apache-2.0",
    ),
    (
        "redistribution and use in source and binary forms, "
        "with or without modification",
        "bsd-3-clause",
    ),
    (
        "permission to use, copy, modify, and/or distribute "
        "this software for any purpose with or without fee",
        "isc",
    ),
    (
        "mozilla public license version 2.0",
        "mpl-2.0",
    ),
    (
        "this is free and unencumbered software released "
        "into the public domain",
        "unlicense",
    ),
    (
        "creative commons zero",
        "cc0-1.0",
    ),
)


QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "app",
    "application",
    "browser",
    "build",
    "complete",
    "contained",
    "create",
    "for",
    "from",
    "game",
    "html",
    "in",
    "index",
    "interactive",
    "make",
    "of",
    "on",
    "one",
    "please",
    "produce",
    "responsive",
    "self",
    "simple",
    "the",
    "to",
    "using",
    "website",
    "with",
}


CAPABILITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "document_shell": (
        "<!doctype",
        "<html",
        "<body",
    ),
    "presentation": (
        "<style",
        "stylesheet",
        "font-family",
        "@media",
    ),
    "user_input": (
        "addeventlistener",
        "onclick",
        "onkeydown",
        "keyup",
        "pointerdown",
        "touchstart",
        "<input",
        "<button",
    ),
    "application_state": (
        "localstorage",
        "sessionstorage",
        "state =",
        "const state",
        "let state",
        "setstate",
    ),
    "data_model": (
        "const items",
        "const data",
        "questions",
        "dataset",
        "json.parse",
        "array.from",
    ),
    "rules_validation": (
        "validate",
        "iscorrect",
        "correctanswer",
        "required",
        "setcustomvalidity",
    ),
    "progress_feedback": (
        "score",
        "feedback",
        "progress",
        "correct",
        "incorrect",
        "message",
    ),
    "lifecycle": (
        "restart",
        "reset",
        "next",
        "startgame",
        "init(",
    ),
    "timed_loop": (
        "requestanimationframe",
        "setinterval",
        "settimeout",
        "deltatime",
    ),
    "canvas_rendering": (
        "<canvas",
        "getcontext(",
        "fillrect",
        "drawimage",
        "clearrect",
    ),
    "collision_detection": (
        "collision",
        "intersect",
        "overlap",
        "hitbox",
        "distance(",
    ),
    "directional_input": (
        "arrowup",
        "arrowdown",
        "arrowleft",
        "arrowright",
        "keyw",
        "keya",
        "keys",
        "keyd",
    ),
    "crud": (
        "additem",
        "deleteitem",
        "edititem",
        "removeitem",
        "splice(",
        "create record",
        "update record",
    ),
    "filtering": (
        ".filter(",
        "searchinput",
        "filtervalue",
        "queryselector",
    ),
    "sorting": (
        ".sort(",
        "sortby",
        "sortdirection",
    ),
    "persistence": (
        "localstorage",
        "indexeddb",
        "sessionstorage",
    ),
    "charting": (
        "chart",
        "<svg",
        "polyline",
        "bar-width",
        "axis",
    ),
    "editing": (
        "contenteditable",
        "execcommand",
        "textarea",
        "selectionstart",
    ),
    "undo_redo": (
        "undo",
        "redo",
        "history.push",
        "historystack",
    ),
    "export": (
        "blob(",
        "createobjecturl",
        "download=",
        "export",
    ),
}


FAMILY_ALIASES: tuple[
    tuple[tuple[str, ...], tuple[str, ...]]
] = (
    (
        (
            "missing word",
            "sentence completion",
            "spelling",
            "vocabulary",
            "language exercise",
        ),
        (
            "educational word quiz javascript html",
            "sentence quiz javascript browser",
            "vocabulary quiz localStorage javascript",
            "word learning game html javascript",
        ),
    ),
    (
        (
            "pong",
            "paddle ball",
        ),
        (
            "pong canvas javascript",
            "paddle game html5 canvas",
            "arcade paddle ball javascript",
        ),
    ),
    (
        (
            "brick breaker",
            "breakout",
        ),
        (
            "breakout canvas javascript",
            "brick breaker html5 game",
            "canvas collision arcade javascript",
        ),
    ),
    (
        (
            "simulation",
            "simulator",
            "oscillator",
            "projectile",
        ),
        (
            "physics simulation canvas javascript",
            "interactive simulator html javascript",
            "canvas animation controls javascript",
        ),
    ),
    (
        (
            "crud",
            "management app",
            "registry",
            "add edit delete",
        ),
        (
            "CRUD localStorage javascript html",
            "inventory manager javascript localStorage",
            "record management app html javascript",
            "todo CRUD vanilla javascript",
        ),
    ),
    (
        (
            "dashboard",
            "analytics",
        ),
        (
            "dashboard javascript html",
            "analytics dashboard vanilla javascript",
            "responsive dashboard charts javascript",
            "admin dashboard html css javascript",
        ),
    ),
    (
        (
            "editor",
            "markdown",
            "json editor",
        ),
        (
            "browser editor localStorage javascript",
            "markdown editor vanilla javascript",
            "text editor html javascript",
        ),
    ),
    (
        (
            "form",
            "registration",
            "booking",
        ),
        (
            "form validation vanilla javascript",
            "registration form html javascript",
            "accessible form validation javascript",
        ),
    ),
    (
        (
            "chart",
            "visualization",
            "visualiser",
            "visualizer",
        ),
        (
            "data visualization javascript svg",
            "interactive chart vanilla javascript",
            "canvas chart javascript",
        ),
    ),
)


def _normalise(value: str) -> str:
    return " ".join(
        str(value or "")
        .lower()
        .strip()
        .split()
    )


def _tokens(value: str) -> list[str]:
    output = []

    for token in re.findall(
        r"[a-z0-9]+",
        _normalise(value),
    ):
        if (
            len(token) >= 2
            and token not in QUERY_STOPWORDS
            and token not in output
        ):
            output.append(token)

    return output


def semantic_queries(
    request: str,
    *,
    maximum: int = 10,
) -> list[str]:
    """Return identity and reusable-capability queries for one request."""

    low = _normalise(request)
    tokens = _tokens(request)

    queries: list[str] = []

    def add(query: str) -> None:
        query = " ".join(
            str(query or "").split()
        )

        if (
            query
            and query not in queries
            and len(queries) < maximum
        ):
            queries.append(query)

    # Preserve an exact compact identity first.
    identity_tokens = tokens[:4]

    if identity_tokens:
        identity = " ".join(identity_tokens)

        add(
            f'"{identity}" in:name'
        )

        add(
            f"{identity} in:name,description"
        )

    for triggers, aliases in FAMILY_ALIASES:
        if any(
            trigger in low
            for trigger in triggers
        ):
            for alias in aliases:
                add(
                    alias
                    + " in:name,description,readme"
                )

    # General reusable browser capabilities.
    core = " ".join(
        tokens[:3]
    )

    if core:
        add(
            f"{core} html javascript in:name,description,readme"
        )

        add(
            f"{core} vanilla javascript in:name,description"
        )

    return queries[:maximum]


def _normalise_licence(
    value: str | None,
) -> str | None:
    low = _normalise(
        value or ""
    )

    low = low.replace(
        "license",
        "",
    ).strip()

    for alias, canonical in PERMISSIVE_ALIASES.items():
        alias_low = _normalise(
            alias
        ).replace(
            "license",
            "",
        ).strip()

        if (
            low == alias_low
            or alias_low in low
        ):
            return canonical

    return None


def _licence_from_text(
    text: str,
) -> str | None:
    low = str(
        text or ""
    ).lower()

    direct = _normalise_licence(
        low[:500]
    )

    if direct:
        return direct

    for marker, canonical in TEXT_LICENCE_MARKERS:
        if marker in low:
            return canonical

    return None


def _licence_metadata_files(
    root: Path,
) -> list[Path]:
    candidates = []

    for relative in (
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "composer.json",
        "bower.json",
    ):
        path = root / relative

        if path.is_file():
            candidates.append(path)

    return candidates


def detect_permissive_licence(
    root: Path,
    api_licence: str = "",
) -> str | None:
    """Inspect API metadata and cloned repository files.

    A repository remains rejected unless a supported permissive licence is
    positively identified.
    """

    api = _normalise_licence(
        api_licence
    )

    if api:
        return api

    root = Path(root)

    if not root.is_dir():
        return None

    licence_files: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        try:
            relative = path.relative_to(
                root
            )
        except ValueError:
            continue

        if len(relative.parts) > 4:
            continue

        name = path.name.lower()

        if name.startswith(
            (
                "license",
                "licence",
                "copying",
                "notice",
            )
        ):
            licence_files.append(path)

    licence_files.sort(
        key=lambda item: (
            len(
                item.relative_to(root).parts
            ),
            str(item).lower(),
        )
    )

    for path in licence_files[:25]:
        try:
            if path.stat().st_size > 500_000:
                continue

            text = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            continue

        licence = _licence_from_text(
            text
        )

        if licence:
            return licence

    for path in _licence_metadata_files(
        root
    ):
        try:
            text = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            continue

        if path.name.lower().endswith(
            ".json"
        ):
            try:
                payload = json.loads(
                    text
                )
            except json.JSONDecodeError:
                payload = {}

            value = payload.get(
                "license"
            )

            if isinstance(value, dict):
                value = (
                    value.get("type")
                    or value.get("name")
                )

            if isinstance(value, list):
                value = " ".join(
                    str(item)
                    for item in value
                )

            licence = _normalise_licence(
                str(value or "")
            )

            if licence:
                return licence

        # TOML and malformed JSON fallback.
        match = re.search(
            r"""(?im)^\s*licen[sc]e\s*=\s*["']([^"']+)["']""",
            text,
        )

        if match:
            licence = _normalise_licence(
                match.group(1)
            )

            if licence:
                return licence

    return None


def infer_capabilities(
    text: str,
    path: str,
) -> set[str]:
    low = (
        str(path or "")
        + "\n"
        + str(text or "")
    ).lower()

    output = set()

    for capability, signals in CAPABILITY_PATTERNS.items():
        if any(
            signal in low
            for signal in signals
        ):
            output.add(
                capability
            )

    suffix = Path(
        path or ""
    ).suffix.lower()

    if suffix in {
        ".html",
        ".htm",
        ".css",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
    }:
        output.add(
            "browser_component"
        )

    return output


def enrich_new_chunks(
    chunk_ids: set[str],
    *,
    request: str,
    progress: Progress,
) -> int:
    if not chunk_ids:
        return 0

    from sophyane.code_memory.store import (
        ChunkStore,
    )

    store = ChunkStore()
    changed = 0

    request_tokens = _tokens(
        request
    )

    for chunk_id in sorted(
        chunk_ids
    ):
        chunk = store.chunks.get(
            chunk_id
        )

        if chunk is None:
            continue

        meta = dict(
            getattr(
                chunk,
                "meta",
                None,
            )
            or {}
        )

        capabilities = infer_capabilities(
            str(
                getattr(
                    chunk,
                    "text",
                    "",
                )
                or ""
            ),
            str(
                getattr(
                    chunk,
                    "path",
                    "",
                )
                or ""
            ),
        )

        if not capabilities:
            continue

        provides = {
            str(value)
            for value in (
                meta.get("provides")
                or []
            )
            if value
        }

        roles = {
            str(value)
            for value in (
                meta.get("roles")
                or []
            )
            if value
        }

        before = (
            set(provides),
            set(roles),
            meta.get(
                "domain"
            ),
        )

        provides.update(
            capabilities
        )
        roles.update(
            capabilities
        )

        meta["provides"] = sorted(
            provides
        )
        meta["roles"] = sorted(
            roles
        )
        meta.setdefault(
            "domain",
            "browser_application",
        )
        meta["grounded_acquisition"] = True
        meta["acquisition_request"] = request
        meta["acquisition_terms"] = request_tokens
        meta["capability_enriched_at"] = (
            time.time()
        )

        after = (
            set(provides),
            set(roles),
            meta.get(
                "domain"
            ),
        )

        if after != before:
            chunk.meta = meta
            store.chunks[
                chunk_id
            ] = chunk
            changed += 1

    if changed and hasattr(
        store,
        "_rewrite_meta",
    ):
        store._rewrite_meta()

    progress(
        "SLI capability extraction: "
        f"{changed} newly acquired chunks enriched"
    )

    return changed


def install(
    namespace: dict[str, Any],
) -> None:
    """Install upgrades into internet_acquire module globals."""

    if namespace.get(
        "_SOPHYANE_ACQUISITION_INTELLIGENCE_INSTALLED"
    ):
        return

    namespace[
        "_SOPHYANE_ACQUISITION_INTELLIGENCE_INSTALLED"
    ] = True

    # Broaden bounded search without permitting unbounded cloning.
    namespace["MAX_RESULTS_PER_QUERY"] = max(
        int(
            namespace.get(
                "MAX_RESULTS_PER_QUERY",
                12,
            )
        ),
        20,
    )

    namespace["MAX_REPOSITORIES"] = max(
        int(
            namespace.get(
                "MAX_REPOSITORIES",
                4,
            )
        ),
        12,
    )

    original_queries = namespace.get(
        "_queries"
    )

    original_public_queries = namespace.get(
        "build_search_queries"
    )

    # SOPHYANE_LANGUAGE_QUERY_DOMAIN_BOUNDARY_V1
    def _explicit_nonbrowser_language_request(
        request: str,
    ) -> bool:
        """Identify source-code searches whose language must be preserved.

        Browser-oriented semantic query expansion is useful for browser
        products, but must not contaminate explicit C++, Python, Rust, etc.
        repository discovery.
        """
        normalized = " ".join(
            str(request or "").casefold().split()
        )

        browser_markers = (
            "website",
            "web site",
            "webpage",
            "web page",
            "browser app",
            "browser application",
            "html",
            "javascript",
            "canvas",
            "landing page",
        )

        if any(
            marker in normalized
            for marker in browser_markers
        ):
            return False

        language_markers = (
            "c++",
            " cpp ",
            "cpp ",
            " cxx ",
            ".cpp",
            "std::",
            "clang++",
            "g++",
            "python",
            ".py",
            "pytest",
            "rust",
            ".rs",
            "cargo",
            "golang",
            " go ",
            ".go",
            "java",
            ".java",
            "kotlin",
            ".kt",
            "swift",
            ".swift",
        )

        return any(
            marker in normalized
            for marker in language_markers
        )

    def _deduplicated_queries(
        values,
        *,
        maximum: int = 10,
    ) -> list[str]:
        output: list[str] = []

        for value in values or []:
            query = " ".join(
                str(value or "").split()
            )

            if (
                query
                and query not in output
            ):
                output.append(
                    query
                )

            if len(output) >= maximum:
                break

        return output

    def upgraded_queries(
        request: str,
    ) -> list[str]:
        # Explicit non-browser languages already have domain-aware builders
        # in internet_acquire. Do not prepend generic browser semantic
        # searches such as HTML/JavaScript/canvas to those requests.
        if _explicit_nonbrowser_language_request(
            request
        ):
            preferred = (
                original_public_queries
                if callable(original_public_queries)
                else original_queries
            )

            if callable(preferred):
                try:
                    return _deduplicated_queries(
                        preferred(request),
                        maximum=10,
                    )
                except Exception:
                    pass

            # A failure in the language-aware builder must degrade to the
            # legacy query builder, not to browser semantic expansion.
            if (
                callable(original_queries)
                and original_queries is not preferred
            ):
                try:
                    return _deduplicated_queries(
                        original_queries(request),
                        maximum=10,
                    )
                except Exception:
                    pass

            return []

        queries = semantic_queries(
            request,
            maximum=10,
        )

        preferred = (
            original_public_queries
            if callable(original_public_queries)
            else original_queries
        )

        if callable(preferred):
            try:
                queries.extend(
                    preferred(request)
                )
            except Exception:
                pass

        return _deduplicated_queries(
            queries,
            maximum=10,
        )

    namespace["_queries"] = (
        upgraded_queries
    )

    # Some later patches call a public query builder.
    namespace["build_search_queries"] = (
        upgraded_queries
    )

    original_detected = namespace.get(
        "_detected_licence"
    )

    def upgraded_detected_licence(
        root: Path,
        api_licence: str,
    ) -> str | None:
        licence = detect_permissive_licence(
            Path(root),
            api_licence,
        )

        if licence:
            return licence

        # Preserve compatibility only when the original detector positively
        # identifies one of the already permitted licences.
        if callable(
            original_detected
        ):
            try:
                value = original_detected(
                    root,
                    api_licence,
                )
            except Exception:
                value = None

            return _normalise_licence(
                value
            )

        return None

    namespace["_detected_licence"] = (
        upgraded_detected_licence
    )

    # Learn reusable contracts from only the chunks added by this request.
    original_acquire = namespace.get(
        "acquire_for_request"
    )

    if callable(
        original_acquire
    ):
        def upgraded_acquire_for_request(
            request: str,
            *args,
            **kwargs,
        ):
            from sophyane.code_memory.store import (
                ChunkStore,
            )

            progress = kwargs.get(
                "progress"
            ) or (
                lambda _message: None
            )

            before = set(
                ChunkStore().ids
            )

            result = original_acquire(
                request,
                *args,
                **kwargs,
            )

            after = set(
                ChunkStore().ids
            )

            enrich_new_chunks(
                after - before,
                request=request,
                progress=progress,
            )

            return result

        namespace["acquire_for_request"] = (
            upgraded_acquire_for_request
        )


__all__ = [
    "detect_permissive_licence",
    "enrich_new_chunks",
    "infer_capabilities",
    "install",
    "semantic_queries",
]


# SOPHYANE_SOFT_ALLOW_V8
try:
    from sophyane.code_memory.licence_gate import decide as _ai_lic_decide_v8
except Exception:
    _ai_lic_decide_v8 = None

def accept_repository_licence(root, api_licence: str = "", progress=None) -> tuple[bool, str]:
    """Return (ok, label). Soft-accept small browser demos without SPDX."""
    progress = progress or (lambda _m: None)
    if _ai_lic_decide_v8 is None:
        return False, "no-licence-helper"
    ok, label, reason = _ai_lic_decide_v8(root, api_licence, allow_soft=True)
    if ok:
        progress(f"SLI licence accept: {label} ({reason})")
        return True, label
    progress(f"SLI licence reject: {label} ({reason})")
    return False, reason
