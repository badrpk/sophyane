"""Grounded acquire-on-miss for SLI browser applications.

The module searches public repositories, clones a bounded set, verifies a
permissive licence, ingests reusable source into Sophyane code memory and
materializes the most relevant browser entry point.

Downloaded Python, shell and build scripts are never executed.
No local or cloud LLM is used.
"""
from __future__ import annotations
import os as _sli_os
MAX_IDENTITY_QUERIES = 2 if not _sli_os.environ.get('GITHUB_TOKEN') else 6


def repo_request_score(full_name: str, description: str, request: str, stars: int, size_kb: float) -> float:
    name = (full_name or "").lower()
    desc = (description or "").lower()
    req = (request or "").lower()
    terms = [t for t in re.findall(r"[a-z0-9]+", req) if t not in {
        "make","create","build","a","the","game","html","javascript","complete","simple"
    }]
    score = 0.0
    blob = name + " " + desc
    for t in terms:
        if t in name:
            score += 8.0
        elif t in desc:
            score += 3.0
    if "pong" in req or "ping" in req:
        if "pong" in name:
            score += 15.0
        if "snake" in name and "pong" not in name:
            score -= 20.0
        if "100-days" in name or "days-of-javascript" in name:
            score -= 30.0
    # prefer small focused repos
    if size_kb and size_kb > 5000:
        score -= 10.0
    if size_kb and size_kb > 20000:
        score -= 25.0
    score += min(3.0, (stars or 0) / 50.0)
    return score


import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


Progress = Callable[[str], None]

MEMORY = Path.home() / ".local/share/sophyane/code_memory"
CACHE = MEMORY / "internet_repositories"
EVENTS = MEMORY / "internet_acquire_events.jsonl"

MAX_RESULTS_PER_QUERY = 12
MAX_REPOSITORIES = 4
MAX_REPOSITORY_KB = 120_000
MAX_FILES = 500
MAX_CHUNKS = 2_000
MAX_HTML_BYTES = 400_000
MAX_INLINE_BYTES = 500_000

SOURCE_SUFFIXES = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
}

SKIP_PARTS = {
    ".git",
    "node_modules",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    "coverage",
    "dist",
    "build",
}

STOPWORDS = {
    "a", "an", "and", "app", "application", "browser", "build",
    "complete", "contained", "create", "develop", "for", "from",
    "game", "generate", "html", "implement", "in", "index",
    "interactive", "make", "one", "page", "playable", "please",
    "project", "self", "simple", "the", "to", "using", "web", "with",
}

PERMISSIVE_SPDX = {
    "mit",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "mpl-2.0",
    "unlicense",
    "0bsd",
}

LICENCE_MARKERS = {
    "mit license": "mit",
    "apache license": "apache-2.0",
    "bsd 2-clause": "bsd-2-clause",
    "bsd 3-clause": "bsd-3-clause",
    "isc license": "isc",
    "mozilla public license": "mpl-2.0",
    "the unlicense": "unlicense",
}


@dataclass(frozen=True)
class Repository:
    full_name: str
    clone_url: str
    default_branch: str
    description: str
    stars: int
    size_kb: int
    api_licence: str
    query: str
    score: float


@dataclass
class Candidate:
    repository: str
    source_path: str
    score: float
    document: str
    issues: list[str]


def _progress(progress: Progress | None) -> Progress:
    return progress or (lambda _message: None)


def _normalise(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _tokens(value: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    for token in re.findall(r"[a-z][a-z0-9_-]{1,}", _normalise(value)):
        token = token.strip("-_")

        if (
            len(token) < 2
            or token in STOPWORDS
            or token in seen
        ):
            continue

        seen.add(token)
        output.append(token)

    return output


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Sophyane-SLI-Acquisition/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def _get_json(url: str, timeout: int = 25) -> dict:
    request = urllib.request.Request(url, headers=_headers())

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _queries(request: str) -> list[str]:
    concepts = _tokens(request)
    primary = concepts[:6]

    queries = [
        " ".join(primary + ["javascript", "html5"]),
        " ".join(primary[:4] + ["canvas", "javascript"]),
        " ".join(primary[:3] + ["browser", "source", "javascript"]),
    ]

    result: list[str] = []

    for query in list(queries)[:MAX_IDENTITY_QUERIES]:
        query = " ".join(query.split())

        if query and query not in result:
            result.append(query)

    return result


def search_repositories(
    request: str,
    *,
    progress: Progress | None = None,
) -> list[Repository]:
    progress = _progress(progress)
    request_tokens = set(_tokens(request))
    found: dict[str, Repository] = {}

    for query in _queries(request):
        progress(f"SLI web search: {query}")

        encoded = urllib.parse.urlencode(
            {
                "q": f"{query} in:name,description,readme fork:false archived:false",
                "sort": "stars",
                "order": "desc",
                "per_page": str(MAX_RESULTS_PER_QUERY),
            }
        )

        try:
            payload = _get_json(
                "https://api.github.com/search/repositories?" + encoded
            )
        except Exception as error:
            progress(
                f"SLI web search error: {type(error).__name__}: {error}"
            )
            continue

        progress(
            "SLI web search results: "
            f"{int(payload.get('total_count') or 0)}"
        )

        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue

            full_name = str(item.get("full_name") or "")
            clone_url = str(item.get("clone_url") or "")
            description = str(item.get("description") or "")
            size_kb = int(item.get("size") or 0)
            stars = int(item.get("stargazers_count") or 0)

            if (
                not full_name
                or not clone_url
                or size_kb <= 0
                or size_kb > MAX_REPOSITORY_KB
            ):
                continue

            licence = str(
                (item.get("license") or {}).get("spdx_id") or ""
            ).lower()

            repository_tokens = set(
                _tokens(full_name.replace("/", " ") + " " + description)
            )

            overlap = len(request_tokens & repository_tokens)

            score = (
                overlap * 25.0
                + min(stars, 50_000) / 5_000
                - min(size_kb, MAX_REPOSITORY_KB) / MAX_REPOSITORY_KB
            )

            candidate = Repository(
                full_name=full_name,
                clone_url=clone_url,
                default_branch=str(item.get("default_branch") or "main"),
                description=description,
                stars=stars,
                size_kb=size_kb,
                api_licence=licence,
                query=query,
                score=score,
            )

            previous = found.get(full_name)

            if previous is None or candidate.score > previous.score:
                found[full_name] = candidate

    ranked = sorted(
        found.values(),
        key=lambda item: (
            -item.score,
            -item.stars,
            item.size_kb,
            item.full_name,
        ),
    )

    progress(f"SLI repository candidates: {len(ranked)}")

    for item in ranked[:10]:
        progress(
            f"  {item.full_name}: score={item.score:.2f}, "
            f"stars={item.stars}, size={item.size_kb}KB, "
            f"licence={item.api_licence or 'inspect-after-clone'}"
        )

    return ranked[:MAX_REPOSITORIES]


def _cache_name(repository: Repository) -> str:
    digest = hashlib.sha256(
        repository.full_name.encode("utf-8")
    ).hexdigest()[:10]

    slug = re.sub(
        r"[^a-zA-Z0-9._-]+",
        "-",
        repository.full_name,
    ).strip("-")

    return f"{slug}-{digest}"


def clone_repository(
    repository: Repository,
    *,
    progress: Progress | None = None,
) -> Path | None:
    progress = _progress(progress)
    CACHE.mkdir(parents=True, exist_ok=True)

    destination = CACHE / _cache_name(repository)

    if (destination / ".git").is_dir():
        progress(f"SLI cache hit: {repository.full_name}")
        return destination

    shutil.rmtree(destination, ignore_errors=True)

    progress(f"SLI cloning: {repository.full_name}")

    try:
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--no-tags",
                repository.clone_url,
                str(destination),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as error:
        progress(f"SLI clone error: {type(error).__name__}: {error}")
        return None

    if result.returncode != 0:
        progress(
            "SLI clone rejected: "
            + result.stderr.replace("\n", " ")[:400]
        )
        shutil.rmtree(destination, ignore_errors=True)
        return None

    return destination


def _detected_licence(root: Path, api_licence: str) -> str | None:
    if api_licence in PERMISSIVE_SPDX:
        return api_licence

    licence_files = [
        path
        for path in root.iterdir()
        if path.is_file()
        and path.name.lower().startswith(
            ("license", "licence", "copying")
        )
    ]

    for path in licence_files[:5]:
        try:
            text = path.read_text(
                encoding="utf-8",
                errors="ignore",
            ).lower()[:100_000]
        except OSError:
            continue

        for marker, licence in LICENCE_MARKERS.items():
            if marker in text:
                return licence

    return None


def _browser_files(root: Path) -> list[Path]:
    files: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue

        if any(part in SKIP_PARTS for part in path.parts):
            continue

        files.append(path)

    files.sort(
        key=lambda path: (
            path.suffix.lower() not in {".html", ".htm"},
            len(path.parts),
            str(path).lower(),
        )
    )

    return files


def _safe_local_dependency(
    html_path: Path,
    reference: str,
    repository_root: Path,
) -> Path | None:
    reference = urllib.parse.unquote(reference.split("?", 1)[0].split("#", 1)[0])

    if not reference or reference.startswith(
        ("http://", "https://", "//", "data:", "javascript:")
    ):
        return None

    candidate = (html_path.parent / reference).resolve()

    try:
        candidate.relative_to(repository_root.resolve())
    except ValueError:
        return None

    if not candidate.is_file():
        return None

    if candidate.stat().st_size > MAX_INLINE_BYTES:
        return None

    return candidate


def _inline_document(
    html_path: Path,
    repository_root: Path,
) -> str | None:
    try:
        source = html_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        return None

    if (
        len(source) < 200
        or len(source) > MAX_HTML_BYTES
        or "<html" not in source.lower()
    ):
        return None

    stylesheet_pattern = re.compile(
        r"""<link\b[^>]*rel=["']?stylesheet["']?[^>]*href=["']([^"']+)["'][^>]*>""",
        flags=re.I,
    )

    script_pattern = re.compile(
        r"""<script\b([^>]*)src=["']([^"']+)["']([^>]*)>\s*</script>""",
        flags=re.I,
    )

    def replace_stylesheet(match: re.Match[str]) -> str:
        dependency = _safe_local_dependency(
            html_path,
            match.group(1),
            repository_root,
        )

        if dependency is None:
            return match.group(0)

        try:
            css = dependency.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            return match.group(0)

        return (
            f"<style data-sli-source={json.dumps(str(dependency))}>\n"
            + css
            + "\n</style>"
        )

    def replace_script(match: re.Match[str]) -> str:
        dependency = _safe_local_dependency(
            html_path,
            match.group(2),
            repository_root,
        )

        if dependency is None:
            return match.group(0)

        if dependency.suffix.lower() not in {
            ".js",
            ".mjs",
            ".cjs",
        }:
            return match.group(0)

        try:
            javascript = dependency.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            return match.group(0)

        attributes = (match.group(1) + " " + match.group(3)).strip()

        return (
            f"<script {attributes} data-sli-source="
            f"{json.dumps(str(dependency))}>\n"
            + javascript
            + "\n</script>"
        )

    source = stylesheet_pattern.sub(replace_stylesheet, source)
    source = script_pattern.sub(replace_script, source)

    return source


def _evaluate(
    document: str,
    request: str,
    source_path: Path,
) -> tuple[float, list[str]]:
    low = document.lower()
    request_tokens = set(_tokens(request))
    issues: list[str] = []
    score = 0.0

    path_tokens = set(_tokens(str(source_path)))
    content_overlap = {
        token
        for token in request_tokens
        if token in low or token in path_tokens
    }

    score += len(content_overlap) * 12.0

    if "<script" in low:
        score += 15
    else:
        issues.append("no script")

    if any(
        signal in low
        for signal in (
            "addeventlistener",
            "onkeydown",
            "onkeyup",
            "onclick",
            "pointerdown",
            "touchstart",
        )
    ):
        score += 15
    else:
        issues.append("no input events")

    if any(
        signal in low
        for signal in (
            "requestanimationframe",
            "setinterval",
            "settimeout",
        )
    ):
        score += 15
    else:
        issues.append("no update lifecycle")

    if any(
        signal in low
        for signal in (
            "<canvas",
            "getcontext(",
            "transform:",
            "position:absolute",
        )
    ):
        score += 12

    if any(
        signal in low
        for signal in (
            "score",
            "state",
            "position",
            "velocity",
            "restart",
            "reset",
        )
    ):
        score += 10

    external_dependencies = len(
        re.findall(
            r"""(?:src|href)=["'](?:https?:)?//""",
            document,
            flags=re.I,
        )
    )

    score -= external_dependencies * 5

    if external_dependencies:
        issues.append(
            f"{external_dependencies} external dependencies remain"
        )

    forbidden = [
        marker
        for marker in (
            "todo: implement",
            "not implemented",
            "coming soon",
            "your code here",
            "lorem ipsum",
        )
        if marker in low
    ]

    if forbidden:
        score -= 40
        issues.append(
            "unfinished markers: " + ", ".join(forbidden)
        )

    if not content_overlap:
        score -= 40
        issues.append("no request-concept overlap")

    return score, issues


def _ingest(
    root: Path,
    repository: Repository,
    progress: Progress,
) -> dict:
    from sophyane.code_memory.acquire import acquire_tree

    report = acquire_tree(
        root,
        limit_files=MAX_FILES,
        limit_chunks=MAX_CHUNKS,
        source=f"internet:{repository.full_name}",
        progress=progress,
    )

    return report


def acquire_for_request(
    request: str,
    *,
    progress: Progress | None = None,
) -> dict:
    progress = _progress(progress)
    started = time.time()
    repositories = search_repositories(
        request,
        progress=progress,
    )

    accepted_repositories: list[dict] = []
    candidates: list[Candidate] = []
    total_added = 0

    for repository in repositories:
        root = clone_repository(
            repository,
            progress=progress,
        )

        if root is None:
            continue

        licence = _detected_licence(
            root,
            repository.api_licence,
        )

        if licence is None:
            progress(
                f"SLI repository skipped: {repository.full_name}: "
                "no verified permissive licence"
            )
            continue

        files = _browser_files(root)

        progress(
            f"SLI repository accepted: {repository.full_name}; "
            f"licence={licence}; browser_files={len(files)}"
        )

        if not files:
            continue

        ingest_report = _ingest(
            root,
            repository,
            progress,
        )

        total_added += int(
            ingest_report.get("chunks_added") or 0
        )

        accepted_repositories.append(
            {
                "repository": repository.full_name,
                "licence": licence,
                "browser_files": len(files),
                "ingest": ingest_report,
            }
        )

        for html_path in [
            path
            for path in files
            if path.suffix.lower() in {".html", ".htm"}
        ][:80]:
            document = _inline_document(
                html_path,
                root,
            )

            if document is None:
                continue

            score, issues = _evaluate(
                document,
                request,
                html_path,
            )

            candidates.append(
                Candidate(
                    repository=repository.full_name,
                    source_path=str(html_path),
                    score=score,
                    document=document,
                    issues=issues,
                )
            )

    candidates.sort(
        key=lambda item: (
            -item.score,
            len(item.issues),
            item.repository,
            item.source_path,
        )
    )

    best = candidates[0] if candidates else None

    event = {
        "request": request,
        "queries": _queries(request),
        "repositories_found": len(repositories),
        "repositories_accepted": accepted_repositories,
        "chunks_added": total_added,
        "candidates": [
            {
                "repository": item.repository,
                "source_path": item.source_path,
                "score": item.score,
                "issues": item.issues,
            }
            for item in candidates[:20]
        ],
        "best": (
            {
                "repository": best.repository,
                "source_path": best.source_path,
                "score": best.score,
                "issues": best.issues,
            }
            if best
            else None
        ),
        "elapsed_seconds": round(time.time() - started, 3),
        "timestamp": time.time(),
    }

    MEMORY.mkdir(parents=True, exist_ok=True)

    with EVENTS.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(event, ensure_ascii=False) + "\n"
        )

    return {
        "event": event,
        "best_document": best.document if best else None,
        "best_score": best.score if best else None,
        "best_issues": best.issues if best else [],
    }


def acquire_and_build(
    request: str,
    workspace: Path,
    *,
    progress: Progress | None = None,
) -> str:
    progress = _progress(progress)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    result = acquire_for_request(
        request,
        progress=progress,
    )

    event = result["event"]
    document = result["best_document"]
    score = result["best_score"]

    if document is None:
        return "\n".join(
            [
                "SLI grounded internet acquisition failed.",
                f"Repositories found: {event['repositories_found']}",
                (
                    "Repositories accepted: "
                    f"{len(event['repositories_accepted'])}"
                ),
                f"Chunks added: {event['chunks_added']}",
                "No relevant HTML entry point passed materialization.",
                "No downloaded code was executed.",
                "No LLM fallback was used.",
            ]
        )

    if score is None or score < 45:
        return "\n".join(
            [
                "SLI grounded internet acquisition found candidates, "
                "but relevance validation failed.",
                f"Best score: {score}",
                "Issues: " + "; ".join(result["best_issues"]),
                f"Chunks added: {event['chunks_added']}",
                "No downloaded code was executed.",
                "No LLM fallback was used.",
            ]
        )

    output = workspace / "index.html"
    output.write_text(document, encoding="utf-8")

    report = "\n".join(
        [
            "Sophyane grounded internet-acquisition composer",
            f"Request: {request}",
            (
                "Source repository: "
                f"{event['best']['repository']}"
            ),
            (
                "Source entry point: "
                f"{event['best']['source_path']}"
            ),
            f"Relevance score: {score:.1f}",
            f"Chunks added to SLI memory: {event['chunks_added']}",
            "Local CSS/JavaScript dependencies: inlined where available",
            "Files: index.html",
            "Success: True",
            (
                "Inference: grounded internet acquisition + SLI memory; "
                "no local/cloud LLM"
            ),
        ]
    )

    try:
        from sophyane.sli_capability_engine import preview_sli_artifact

        preview = preview_sli_artifact(
            workspace,
            progress=progress,
        )

        report += "\n" + str(preview)

    except Exception as error:
        report += (
            "\nPreview warning: "
            f"{type(error).__name__}: {error}"
        )

    return report


__all__ = [
    "acquire_and_build",
    "acquire_for_request",
    "clone_repository",
    "search_repositories",
]

# SOPHYANE_REQUEST_RELEVANCE_GUARD_V1
# Prevent stale or wrong-family applications from being reported/opened.

_acquire_and_build_before_relevance_guard = acquire_and_build


def _sli_request_identity_terms(request: str) -> list[str]:
    import re as _re

    stop = {
        "make", "create", "build", "develop", "generate",
        "implement", "complete", "simple", "interactive",
        "playable", "browser", "web", "website", "application",
        "app", "game", "one", "self", "contained", "html",
        "index", "the", "a", "an", "in", "for", "with",
        "two", "player",
    }

    terms = []

    for token in re.findall(
        r"[a-z][a-z0-9_-]{1,}",
        str(request or "").lower(),
    ):
        token = token.strip("-_")

        if (
            token
            and token not in stop
            and token not in terms
        ):
            terms.append(token)

    return terms


def _sli_artifact_matches_request(
    request: str,
    artifact,
) -> tuple[bool, list[str]]:
    from pathlib import Path as _Path

    path = _Path(artifact)

    if not path.is_file():
        return False, []

    source = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).lower()

    terms = _sli_request_identity_terms(
        request
    )

    if not terms:
        return True, []

    matched = [
        term
        for term in terms
        if term in source
        or term in str(path).lower()
    ]

    # For a short identity such as "ping pong", at least one identity term
    # must be present. For longer requests, require two.
    required = 1 if len(terms) <= 2 else 2

    return len(matched) >= required, matched


def acquire_and_build(
    request,
    workspace,
    *,
    progress=None,
):
    from pathlib import Path as _Path

    target = _Path(workspace)
    artifact = target / "index.html"

    # Remove stale artifacts before acquisition.
    artifact.unlink(
        missing_ok=True,
    )

    report = _acquire_and_build_before_relevance_guard(
        request,
        target,
        progress=progress,
    )

    if not artifact.is_file():
        return report

    relevant, matched = _sli_artifact_matches_request(
        request,
        artifact,
    )

    if not relevant:
        artifact.unlink(
            missing_ok=True,
        )

        return (
            "SLI acquired and composed a browser artifact, but rejected it "
            "as unrelated to the request.\n"
            f"Request identity terms: "
            f"{', '.join(_sli_request_identity_terms(request)) or 'none'}\n"
            f"Matched identity terms: {', '.join(matched) or 'none'}\n"
            "The artifact was not opened.\n"
            "No LLM fallback was used."
        )

    return report


# RANK_FILTER_V2
def filter_and_sort_candidates(cands, request: str):
    """Prefer small pong-named repos; drop giant tutorial monorepos."""
    req = (request or "").lower()
    scored = []
    for c in cands:
        if isinstance(c, dict):
            name = str(c.get("full_name") or c.get("name") or "")
            stars = int(c.get("stars") or c.get("stargazers_count") or 0)
            size = float(c.get("size") or c.get("size_kb") or 0)
            desc = str(c.get("description") or "")
        else:
            name = str(getattr(c, "full_name", "") or getattr(c, "name", ""))
            stars = int(getattr(c, "stars", 0) or 0)
            size = float(getattr(c, "size", 0) or 0)
            desc = str(getattr(c, "description", "") or "")
        sc = repo_request_score(name, desc, request, stars, size)
        if sc < 0:
            continue
        scored.append((sc, c))
    scored.sort(key=lambda x: -x[0])
    return [c for sc, c in scored]

# SOPHYANE_SEMANTIC_SOURCE_RANKING_V3
#
# Generic semantic ranking for acquired browser projects.
#
# Principles:
#   * request identity must appear in repository/path/title/content;
#   * compact runnable entry points outrank test aggregators;
#   * documentation, benchmark and collection repositories are penalized;
#   * browser behavior remains necessary but is not treated as semantic proof;
#   * no application-specific rules or templates are embedded here.

_search_repositories_before_semantic_rank = search_repositories
_acquire_for_request_before_semantic_rank = acquire_for_request


def _sli_identity_terms(request: str) -> list[str]:
    import re as _re

    stop = {
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
        "develop",
        "design",
        "for",
        "from",
        "game",
        "generate",
        "html",
        "implement",
        "in",
        "index",
        "interactive",
        "make",
        "one",
        "page",
        "playable",
        "please",
        "project",
        "self",
        "simple",
        "the",
        "to",
        "two",
        "using",
        "web",
        "webpage",
        "website",
        "with",
    }

    terms: list[str] = []

    for token in re.findall(
        r"[a-z][a-z0-9_-]{1,}",
        str(request or "").lower(),
    ):
        token = token.strip("-_")

        if (
            len(token) >= 2
            and token not in stop
            and token not in terms
        ):
            terms.append(token)

    return terms


def _sli_repository_semantic_score(
    repository,
    request: str,
) -> float:
    terms = _sli_identity_terms(request)

    full_name = str(
        getattr(
            repository,
            "full_name",
            "",
        )
        or ""
    ).lower()

    description = str(
        getattr(
            repository,
            "description",
            "",
        )
        or ""
    ).lower()

    searchable = (
        full_name.replace("/", " ")
        + " "
        + description
    )

    matched = [
        term
        for term in terms
        if term in searchable
    ]

    score = float(
        getattr(
            repository,
            "score",
            0.0,
        )
        or 0.0
    )

    # Identity is much more important than popularity.
    score += len(matched) * 45.0

    if terms:
        coverage = len(matched) / len(terms)
        score += coverage * 70.0

        if not matched:
            score -= 90.0

    # A match in the repository name is stronger than description-only.
    for term in matched:
        if term in full_name:
            score += 25.0

    generic_collection_markers = (
        "awesome",
        "collection",
        "project-based-learning",
        "tutorials",
        "tutorial",
        "examples",
        "demo-collection",
        "100-days",
        "100projects",
        "resources",
        "curated",
    )

    for marker in generic_collection_markers:
        if marker in searchable:
            score -= 50.0

    # Prefer small, focused repositories.
    size_kb = int(
        getattr(
            repository,
            "size_kb",
            0,
        )
        or 0
    )

    if 0 < size_kb <= 5_000:
        score += 15.0
    elif size_kb > 50_000:
        score -= 20.0

    return score


def search_repositories(
    request: str,
    *,
    progress=None,
):
    global MAX_REPOSITORIES

    # Ask the original search for a broader pool, then rank semantically.
    previous_limit = MAX_REPOSITORIES
    MAX_REPOSITORIES = max(
        int(previous_limit),
        20,
    )

    try:
        repositories = (
            _search_repositories_before_semantic_rank(
                request,
                progress=progress,
            )
        )
    finally:
        MAX_REPOSITORIES = previous_limit

    ranked = sorted(
        repositories,
        key=lambda repository: (
            -_sli_repository_semantic_score(
                repository,
                request,
            ),
            -int(
                getattr(
                    repository,
                    "stars",
                    0,
                )
                or 0
            ),
            int(
                getattr(
                    repository,
                    "size_kb",
                    0,
                )
                or 0
            ),
            str(
                getattr(
                    repository,
                    "full_name",
                    "",
                )
            ).lower(),
        ),
    )

    selected = ranked[
        : max(
            4,
            int(previous_limit),
        )
    ]

    if progress:
        progress(
            "SLI semantic repository ranking:"
        )

        for repository in selected:
            progress(
                "  "
                + str(
                    getattr(
                        repository,
                        "full_name",
                        "",
                    )
                )
                + ": semantic_score="
                + (
                    f"{_sli_repository_semantic_score(repository, request):.2f}"
                )
            )

    return selected


def _sli_repository_root(path):
    from pathlib import Path as _Path

    current = _Path(path).resolve()

    if current.is_file():
        current = current.parent

    for candidate in (
        current,
        *current.parents,
    ):
        if (candidate / ".git").is_dir():
            return candidate

    return None


def _sli_document_title(document: str) -> str:
    import re as _re

    match = re.search(
        r"<title[^>]*>(.*?)</title>",
        str(document or ""),
        flags=re.I | re.S,
    )

    if not match:
        return ""

    return re.sub(
        r"\s+",
        " ",
        match.group(1),
    ).strip().lower()


def _sli_candidate_semantic_score(
    *,
    request: str,
    repository: str,
    source_path: str,
    document: str,
    original_score: float,
) -> tuple[float, list[str], list[str]]:
    from pathlib import Path as _Path
    import re as _re

    terms = _sli_identity_terms(request)

    repository_low = str(
        repository or ""
    ).lower()

    path_low = str(
        source_path or ""
    ).lower()

    title_low = _sli_document_title(document)

    # Strip tags for limited visible-text matching.
    visible = re.sub(
        r"<script\b.*?</script>",
        " ",
        str(document or ""),
        flags=re.I | re.S,
    )

    visible = re.sub(
        r"<style\b.*?</style>",
        " ",
        visible,
        flags=re.I | re.S,
    )

    visible = re.sub(
        r"<[^>]+>",
        " ",
        visible,
    ).lower()

    matched_repository = [
        term
        for term in terms
        if term in repository_low
    ]

    matched_path = [
        term
        for term in terms
        if term in path_low
    ]

    matched_title = [
        term
        for term in terms
        if term in title_low
    ]

    matched_visible = [
        term
        for term in terms
        if term in visible
    ]

    matched = sorted(
        set(
            matched_repository
            + matched_path
            + matched_title
            + matched_visible
        )
    )

    score = float(
        original_score
        or 0.0
    )

    score += len(matched_repository) * 45.0
    score += len(matched_path) * 40.0
    score += len(matched_title) * 55.0
    score += len(matched_visible) * 12.0

    if terms:
        coverage = len(matched) / len(terms)
        score += coverage * 100.0

        if not matched:
            score -= 140.0

    path = _Path(source_path)

    depth = len(path.parts)

    if depth <= 8:
        score += 10.0

    filename = path.name.lower()

    preferred_entry_names = {
        "index.html",
        "index.htm",
        "main.html",
        "app.html",
    }

    if filename in preferred_entry_names:
        score += 18.0

    # A filename containing identity terms is highly relevant.
    if any(
        term in filename
        for term in terms
    ):
        score += 35.0

    bad_path_parts = {
        "test",
        "tests",
        "spec",
        "specs",
        "benchmark",
        "benchmarks",
        "coverage",
        "fixtures",
        "docs",
        "documentation",
        "node_modules",
        "vendor",
    }

    path_parts = {
        part.lower()
        for part in path.parts
    }

    bad_hits = sorted(
        path_parts & bad_path_parts
    )

    score -= len(bad_hits) * 55.0

    bad_filenames = {
        "all.html",
        "tests.html",
        "test.html",
        "runner.html",
        "benchmark.html",
        "coverage.html",
    }

    if filename in bad_filenames:
        score -= 100.0
        bad_hits.append(
            f"aggregator:{filename}"
        )

    document_size = len(
        document.encode(
            "utf-8",
            errors="ignore",
        )
    )

    if document_size <= 150_000:
        score += 15.0
    elif document_size > 500_000:
        score -= 45.0
    elif document_size > 250_000:
        score -= 20.0

    # Generic behavior remains useful, but cannot replace identity.
    low = document.lower()

    if "<canvas" in low:
        score += 8.0

    if (
        "requestanimationframe" in low
        or "setinterval" in low
    ):
        score += 8.0

    if (
        "addeventlistener" in low
        or "onkeydown" in low
        or "onkeyup" in low
    ):
        score += 8.0

    issues = []

    if not matched:
        issues.append(
            "no request identity"
        )

    if bad_hits:
        issues.append(
            "test/documentation path: "
            + ", ".join(bad_hits)
        )

    if document_size > 500_000:
        issues.append(
            f"oversized entry point: {document_size} bytes"
        )

    return score, issues, matched


def acquire_for_request(
    request: str,
    *,
    progress=None,
):
    result = (
        _acquire_for_request_before_semantic_rank(
            request,
            progress=progress,
        )
    )

    event = dict(
        result.get(
            "event",
            {},
        )
        or {}
    )

    existing_candidates = list(
        event.get(
            "candidates",
            [],
        )
        or []
    )

    # Include the original best even when the event candidate list was short.
    original_best = event.get(
        "best"
    )

    if (
        isinstance(
            original_best,
            dict,
        )
        and original_best not in existing_candidates
    ):
        existing_candidates.append(
            original_best
        )

    reranked = []

    for candidate in existing_candidates:
        if not isinstance(
            candidate,
            dict,
        ):
            continue

        source_path = str(
            candidate.get(
                "source_path",
                "",
            )
            or ""
        )

        if not source_path:
            continue

        from pathlib import Path as _Path

        path = _Path(source_path)

        if not path.is_file():
            continue

        repository_root = _sli_repository_root(
            path
        )

        if repository_root is None:
            continue

        try:
            document = _inline_document(
                path,
                repository_root,
            )
        except Exception:
            document = None

        if not document:
            continue

        repository = str(
            candidate.get(
                "repository",
                "",
            )
            or ""
        )

        score, issues, matched = (
            _sli_candidate_semantic_score(
                request=request,
                repository=repository,
                source_path=source_path,
                document=document,
                original_score=float(
                    candidate.get(
                        "score",
                        0.0,
                    )
                    or 0.0
                ),
            )
        )

        reranked.append(
            {
                "repository": repository,
                "source_path": source_path,
                "score": score,
                "issues": issues,
                "matched_identity": matched,
                "_document": document,
            }
        )

    reranked.sort(
        key=lambda candidate: (
            -float(
                candidate["score"]
            ),
            len(
                candidate["issues"]
            ),
            len(
                candidate["_document"]
            ),
            candidate["repository"],
            candidate["source_path"],
        )
    )

    if progress:
        progress(
            "SLI semantic entry-point ranking:"
        )

        for candidate in reranked[:10]:
            progress(
                "  "
                + candidate["repository"]
                + " :: "
                + candidate["source_path"]
                + " score="
                + f"{candidate['score']:.1f}"
                + " identity="
                + (
                    ",".join(
                        candidate[
                            "matched_identity"
                        ]
                    )
                    or "none"
                )
                + (
                    " issues="
                    + ";".join(
                        candidate["issues"]
                    )
                    if candidate["issues"]
                    else ""
                )
            )

    accepted = [
        candidate
        for candidate in reranked
        if (
            candidate["score"] >= 70.0
            and candidate[
                "matched_identity"
            ]
            and not any(
                issue.startswith(
                    "test/documentation"
                )
                for issue in candidate[
                    "issues"
                ]
            )
        )
    ]

    if not accepted:
        result["best_document"] = None
        result["best_score"] = None
        result["best_issues"] = [
            "no semantically grounded runnable entry point"
        ]

        event["best"] = None
        event["candidates"] = [
            {
                key: value
                for key, value in candidate.items()
                if key != "_document"
            }
            for candidate in reranked[:20]
        ]

        result["event"] = event

        return result

    best = accepted[0]

    event["best"] = {
        key: value
        for key, value in best.items()
        if key != "_document"
    }

    event["candidates"] = [
        {
            key: value
            for key, value in candidate.items()
            if key != "_document"
        }
        for candidate in reranked[:20]
    ]

    result["event"] = event
    result["best_document"] = best[
        "_document"
    ]
    result["best_score"] = best[
        "score"
    ]
    result["best_issues"] = best[
        "issues"
    ]

    return result

# SOPHYANE_IDENTITY_FIRST_SEARCH_V4
#
# Search is driven by request identity before stars or generic browser terms.
# This is generic: no application or game name is hardcoded.

_search_repositories_before_identity_v4 = search_repositories


def build_search_queries(
    request: str,
) -> list[str]:
    """Build exact and progressively broader repository queries."""

    import re as _re

    stop = {
        "a", "an", "and", "app", "application",
        "browser", "build", "complete", "contained",
        "create", "develop", "design", "for", "from",
        "game", "generate", "html", "implement", "in",
        "index", "interactive", "make", "one", "page",
        "playable", "please", "project", "self",
        "simple", "the", "to", "using", "web",
        "webpage", "website", "with",
    }

    terms: list[str] = []

    for token in re.findall(
        r"[a-z][a-z0-9_-]{1,}",
        str(request or "").lower(),
    ):
        token = token.strip("-_")

        if (
            len(token) >= 2
            and token not in stop
            and token not in terms
        ):
            terms.append(token)

    if not terms:
        terms = ["canvas"]

    identity = terms[:4]
    phrase = " ".join(identity)
    hyphenated = "-".join(identity)
    compact = "".join(identity)

    queries = [
        f'"{phrase}" in:name',
        f'{hyphenated} in:name',
        f'{phrase} in:name,description',
        f'{phrase} canvas javascript in:name,description',
        f'{phrase} html5 javascript in:name,description',
    ]

    # A compact variant helps requests whose repository names join words.
    if len(identity) > 1:
        queries.append(
            f'{compact} in:name'
        )

    output: list[str] = []

    for query in queries:
        query = " ".join(
            query.split()
        )

        if query and query not in output:
            output.append(query)

    return output


def _sli_identity_terms_v4(
    request: str,
) -> list[str]:
    import re as _re

    stop = {
        "a", "an", "and", "app", "application",
        "browser", "build", "complete", "contained",
        "create", "develop", "design", "for", "from",
        "game", "generate", "html", "implement", "in",
        "index", "interactive", "make", "one", "page",
        "playable", "please", "project", "self",
        "simple", "the", "to", "using", "web",
        "webpage", "website", "with",
    }

    result = []

    for token in re.findall(
        r"[a-z][a-z0-9_-]{1,}",
        str(request or "").lower(),
    ):
        token = token.strip("-_")

        if (
            token not in stop
            and token not in result
        ):
            result.append(token)

    return result[:6]


def _sli_github_json_v4(
    url: str,
):
    import json as _json
    import os as _os
    import urllib.request as _request

    headers = {
        "Accept":
            "application/vnd.github+json",

        "User-Agent":
            "Sophyane-SLI-Identity-Search/4",

        "X-GitHub-Api-Version":
            "2022-11-28",
    }

    token = (
        _os.environ.get("GITHUB_TOKEN")
        or _os.environ.get("GH_TOKEN")
    )

    if token:
        headers["Authorization"] = (
            f"Bearer {token}"
        )

    request = _request.Request(
        url,
        headers=headers,
    )

    with _request.urlopen(
        request,
        timeout=25,
    ) as response:
        return _json.loads(
            response.read().decode(
                "utf-8",
                errors="replace",
            )
        )


def _sli_repository_identity_score_v4(
    item: dict,
    terms: list[str],
) -> float:
    import re as _re

    full_name = str(
        item.get("full_name") or ""
    ).lower()

    repository_name = full_name.split("/")[-1]

    description = str(
        item.get("description") or ""
    ).lower()

    name_normalized = (
        repository_name
        .replace("-", " ")
        .replace("_", " ")
        .replace(".", " ")
    )

    searchable = (
        name_normalized
        + " "
        + description
    )

    name_matches = [
        term
        for term in terms
        if term in name_normalized
    ]

    description_matches = [
        term
        for term in terms
        if term in description
    ]

    all_matches = set(
        name_matches
        + description_matches
    )

    if not all_matches:
        return -1000.0

    score = 0.0

    score += len(name_matches) * 80.0
    score += len(description_matches) * 20.0

    if terms:
        score += (
            len(all_matches)
            / len(terms)
        ) * 120.0

    phrase = " ".join(terms)

    if phrase and phrase in name_normalized:
        score += 100.0

    joined = "".join(terms)

    repository_compact = re.sub(
        r"[^a-z0-9]",
        "",
        repository_name,
    )

    if (
        joined
        and joined in repository_compact
    ):
        score += 80.0

    generic_markers = (
        "awesome",
        "collection",
        "tutorial",
        "examples",
        "project-based-learning",
        "100-days",
        "resources",
        "curated",
    )

    for marker in generic_markers:
        if marker in searchable:
            score -= 100.0

    stars = int(
        item.get("stargazers_count")
        or 0
    )

    # Stars are only a small tie-breaker.
    score += min(stars, 10000) / 10000

    size = int(
        item.get("size")
        or 0
    )

    if 0 < size <= 5000:
        score += 10.0
    elif size > 50000:
        score -= 15.0

    return score


def search_repositories(
    request: str,
    *,
    progress=None,
):
    import urllib.parse as _parse

    terms = _sli_identity_terms_v4(
        request
    )

    found = {}

    for query in build_search_queries(
        request
    ):
        if progress:
            progress(
                "SLI identity search: "
                + query
            )

        encoded = _parse.urlencode(
            {
                "q": (
                    query
                    + " fork:false archived:false"
                ),
                # Deliberately omit sort=stars.
                # GitHub's default is best-match relevance.
                "order": "desc",
                "per_page": "30",
            }
        )

        try:
            payload = _sli_github_json_v4(
                "https://api.github.com/"
                "search/repositories?"
                + encoded
            )
        except Exception as error:
            if progress:
                progress(
                    "SLI identity search error: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            continue

        items = payload.get(
            "items",
            [],
        )

        if progress:
            progress(
                "SLI identity results: "
                + str(len(items))
            )

        for item in items:
            if not isinstance(
                item,
                dict,
            ):
                continue

            full_name = str(
                item.get("full_name")
                or ""
            )

            clone_url = str(
                item.get("clone_url")
                or ""
            )

            if not full_name or not clone_url:
                continue

            size_kb = int(
                item.get("size")
                or 0
            )

            if (
                size_kb <= 0
                or size_kb > 120000
            ):
                continue

            semantic_score = (
                _sli_repository_identity_score_v4(
                    item,
                    terms,
                )
            )

            # No identity = no clone.
            if semantic_score < 0:
                continue

            licence = str(
                (
                    item.get("license")
                    or {}
                ).get("spdx_id")
                or ""
            ).lower()

            repository = Repository(
                full_name=full_name,
                clone_url=clone_url,
                default_branch=str(
                    item.get(
                        "default_branch"
                    )
                    or "main"
                ),
                description=str(
                    item.get("description")
                    or ""
                ),
                stars=int(
                    item.get(
                        "stargazers_count"
                    )
                    or 0
                ),
                size_kb=size_kb,
                api_licence=licence,
                query=query,
                score=semantic_score,
            )

            previous = found.get(
                full_name
            )

            if (
                previous is None
                or repository.score
                > previous.score
            ):
                found[full_name] = repository

    ranked = sorted(
        found.values(),
        key=lambda repository: (
            -repository.score,
            repository.size_kb,
            -repository.stars,
            repository.full_name.lower(),
        ),
    )

    # Keep acquisition bounded.
    selected = ranked[:8]

    if progress:
        progress(
            "SLI identity-first repositories:"
        )

        for repository in selected:
            progress(
                "  "
                + repository.full_name
                + " score="
                + f"{repository.score:.1f}"
                + " size="
                + str(repository.size_kb)
                + "KB licence="
                + (
                    repository.api_licence
                    or "inspect-after-clone"
                )
            )

    return selected

# SOPHYANE_RATE_LIMIT_CACHE_V5
#
# Adds authenticated GitHub search, persistent response caching,
# rate-limit backoff and local-clone fallback. It contains no
# application-specific implementation or artifact template.

import base64 as _sli_base64
import hashlib as _sli_hashlib
import json as _sli_json
import os as _sli_os
import re as _sli_re
import subprocess as _sli_subprocess
import time as _sli_time
import urllib.error as _sli_urlerror
import urllib.request as _sli_urlrequest
from pathlib import Path as _SliPath


_sli_search_before_v5 = search_repositories
_sli_licence_before_v5 = _detected_licence

_SLI_SEARCH_CACHE = (
    MEMORY
    / "github_search_cache"
)

_SLI_RATE_STATE = (
    MEMORY
    / "github_rate_state.json"
)

_SLI_SEARCH_TTL = 24 * 60 * 60


def _sli_identity_v5(
    request: str,
) -> list[str]:
    stop = {
        "a", "an", "and", "app", "application",
        "browser", "build", "complete", "contained",
        "create", "develop", "design", "for", "from",
        "game", "generate", "html", "implement", "in",
        "index", "interactive", "make", "one", "page",
        "playable", "please", "project", "self",
        "simple", "the", "to", "using", "web",
        "webpage", "website", "with",
    }

    result = []

    for token in _sli_re.findall(
        r"[a-z][a-z0-9_-]{1,}",
        str(request or "").lower(),
    ):
        token = token.strip("-_")

        if (
            token
            and token not in stop
            and token not in result
        ):
            result.append(token)

    return result[:5]


def build_search_queries(
    request: str,
) -> list[str]:
    """Use two identity-rich searches instead of repeated broad queries."""

    terms = _sli_identity_v5(
        request
    )

    if not terms:
        terms = ["canvas"]

    phrase = " ".join(terms)
    hyphenated = "-".join(terms)

    queries = [
        f'"{phrase}" in:name',
        (
            f'{hyphenated} canvas javascript '
            'in:name,description'
        ),
    ]

    return list(
        dict.fromkeys(queries)
    )


def _sli_api_token_v5() -> str:
    token = (
        _sli_os.environ.get(
            "GITHUB_TOKEN"
        )
        or _sli_os.environ.get(
            "GH_TOKEN"
        )
    )

    if token:
        return token.strip()

    if not shutil.which("gh"):
        return ""

    try:
        result = _sli_subprocess.run(
            [
                "gh",
                "auth",
                "token",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    except Exception:
        return ""

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def _sli_api_headers_v5() -> dict[str, str]:
    headers = {
        "Accept":
            "application/vnd.github+json",

        "User-Agent":
            "Sophyane-SLI-Acquisition/5",

        "X-GitHub-Api-Version":
            "2022-11-28",
    }

    token = _sli_api_token_v5()

    if token:
        headers["Authorization"] = (
            f"Bearer {token}"
        )

    return headers


def _sli_cache_path_v5(
    url: str,
) -> _SliPath:
    digest = _sli_hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()

    return (
        _SLI_SEARCH_CACHE
        / f"{digest}.json"
    )


def _sli_read_cache_v5(
    url: str,
    *,
    allow_stale: bool = False,
):
    path = _sli_cache_path_v5(
        url
    )

    if not path.is_file():
        return None

    try:
        record = _sli_json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

    except Exception:
        return None

    age = (
        _sli_time.time()
        - float(
            record.get(
                "timestamp",
                0,
            )
            or 0
        )
    )

    if (
        not allow_stale
        and age > _SLI_SEARCH_TTL
    ):
        return None

    payload = record.get(
        "payload"
    )

    return (
        payload
        if isinstance(payload, dict)
        else None
    )


def _sli_write_cache_v5(
    url: str,
    payload: dict,
) -> None:
    _SLI_SEARCH_CACHE.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = _sli_cache_path_v5(
        url
    )

    temporary = target.with_suffix(
        ".tmp"
    )

    temporary.write_text(
        _sli_json.dumps(
            {
                "timestamp":
                    _sli_time.time(),

                "url":
                    url,

                "payload":
                    payload,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _sli_os.replace(
        temporary,
        target,
    )


def _sli_rate_state_v5() -> dict:
    if not _SLI_RATE_STATE.is_file():
        return {}

    try:
        return _sli_json.loads(
            _SLI_RATE_STATE.read_text(
                encoding="utf-8",
            )
        )

    except Exception:
        return {}


def _sli_set_rate_state_v5(
    *,
    reset: int,
    reason: str,
) -> None:
    _SLI_RATE_STATE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    _SLI_RATE_STATE.write_text(
        _sli_json.dumps(
            {
                "reset":
                    int(reset),

                "reason":
                    str(reason),

                "recorded_at":
                    int(
                        _sli_time.time()
                    ),
            }
        ),
        encoding="utf-8",
    )


def _sli_github_json_v5(
    url: str,
):
    cached = _sli_read_cache_v5(
        url
    )

    if cached is not None:
        return cached

    rate_state = _sli_rate_state_v5()
    reset = int(
        rate_state.get(
            "reset",
            0,
        )
        or 0
    )

    if reset > int(
        _sli_time.time()
    ):
        stale = _sli_read_cache_v5(
            url,
            allow_stale=True,
        )

        if stale is not None:
            return stale

        remaining = (
            reset
            - int(
                _sli_time.time()
            )
        )

        raise RuntimeError(
            "GitHub search is rate-limited; "
            f"reset in approximately {remaining} seconds"
        )

    request = _sli_urlrequest.Request(
        url,
        headers=_sli_api_headers_v5(),
    )

    try:
        with _sli_urlrequest.urlopen(
            request,
            timeout=25,
        ) as response:
            payload = _sli_json.loads(
                response.read().decode(
                    "utf-8",
                    errors="replace",
                )
            )

            _sli_write_cache_v5(
                url,
                payload,
            )

            return payload

    except _sli_urlerror.HTTPError as error:
        reset_header = error.headers.get(
            "x-ratelimit-reset"
        )

        retry_after = error.headers.get(
            "retry-after"
        )

        now = int(
            _sli_time.time()
        )

        if reset_header:
            try:
                reset = int(
                    reset_header
                )
            except ValueError:
                reset = now + 60

        elif retry_after:
            try:
                reset = (
                    now
                    + int(
                        retry_after
                    )
                )
            except ValueError:
                reset = now + 60

        else:
            reset = now + 60

        if error.code in {
            403,
            429,
        }:
            _sli_set_rate_state_v5(
                reset=reset,
                reason=f"HTTP {error.code}",
            )

            stale = _sli_read_cache_v5(
                url,
                allow_stale=True,
            )

            if stale is not None:
                return stale

        raise


# Functions defined earlier resolve this global name at runtime.
_sli_github_json_v4 = _sli_github_json_v5


def _sli_cached_repositories_v5(
    request: str,
) -> list:
    terms = _sli_identity_v5(
        request
    )

    roots = []

    for cache_root in (
        MEMORY
        / "internet_repositories",

        MEMORY
        / "github_cache",
    ):
        if not cache_root.is_dir():
            continue

        roots.extend(
            path
            for path in cache_root.iterdir()
            if path.is_dir()
        )

    output = []

    for root in roots:
        searchable = (
            root.name
            .replace("-", " ")
            .replace("_", " ")
            .lower()
        )

        matches = [
            term
            for term in terms
            if term in searchable
        ]

        if not matches:
            continue

        remote = ""

        try:
            result = _sli_subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "--get",
                    "remote.origin.url",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            remote = (
                result.stdout.strip()
            )

        except Exception:
            pass

        full_name = root.name

        match = _sli_re.search(
            r"github\.com[/:]"
            r"([^/]+/[^/]+?)"
            r"(?:\.git)?$",
            remote,
        )

        if match:
            full_name = (
                match.group(1)
            )

        size_kb = sum(
            path.stat().st_size
            for path in root.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
        ) // 1024

        output.append(
            Repository(
                full_name=full_name,
                clone_url=remote,
                default_branch="main",
                description=(
                    "locally cached identity match"
                ),
                stars=0,
                size_kb=max(
                    1,
                    int(size_kb),
                ),
                api_licence="",
                query="local-cache",
                score=(
                    len(matches)
                    * 100.0
                ),
            )
        )

    output.sort(
        key=lambda repository: (
            -repository.score,
            repository.size_kb,
            repository.full_name,
        )
    )

    return output[:8]


def search_repositories(
    request: str,
    *,
    progress=None,
):
    try:
        repositories = (
            _sli_search_before_v5(
                request,
                progress=progress,
            )
        )

    except Exception as error:
        if progress:
            progress(
                "SLI remote search unavailable: "
                f"{type(error).__name__}: {error}"
            )

        repositories = []

    cached = _sli_cached_repositories_v5(
        request
    )

    by_name = {}

    for repository in (
        list(repositories)
        + cached
    ):
        previous = by_name.get(
            repository.full_name
        )

        if (
            previous is None
            or repository.score
            > previous.score
        ):
            by_name[
                repository.full_name
            ] = repository

    ranked = sorted(
        by_name.values(),
        key=lambda repository: (
            -repository.score,
            repository.size_kb,
            repository.full_name,
        ),
    )

    if progress:
        authenticated = bool(
            _sli_api_token_v5()
        )

        progress(
            "SLI GitHub authentication: "
            + (
                "authenticated"
                if authenticated
                else "unauthenticated"
            )
        )

        progress(
            "SLI remote/cache repositories: "
            + str(
                len(ranked)
            )
        )

    return ranked[:8]


def _detected_licence(
    root,
    api_licence,
):
    detected = (
        _sli_licence_before_v5(
            root,
            api_licence,
        )
    )

    if detected:
        return detected

    root = _SliPath(root)

    # Check common licence files up to two directories deep.
    candidates = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        try:
            relative = path.relative_to(
                root
            )
        except ValueError:
            continue

        if len(
            relative.parts
        ) > 3:
            continue

        name = path.name.lower()

        if name.startswith(
            (
                "license",
                "licence",
                "copying",
            )
        ):
            candidates.append(
                path
            )

    markers = {
        "mit license":
            "mit",

        "apache license":
            "apache-2.0",

        "bsd 2-clause":
            "bsd-2-clause",

        "bsd 3-clause":
            "bsd-3-clause",

        "isc license":
            "isc",

        "mozilla public license":
            "mpl-2.0",

        "the unlicense":
            "unlicense",
    }

    for candidate in candidates[:20]:
        try:
            text = candidate.read_text(
                encoding="utf-8",
                errors="ignore",
            ).lower()[:150000]
        except OSError:
            continue

        for marker, licence in markers.items():
            if marker in text:
                return licence

    # package.json often declares the repository licence.
    for package in root.rglob(
        "package.json"
    ):
        try:
            relative = package.relative_to(
                root
            )

            if len(
                relative.parts
            ) > 3:
                continue

            data = _sli_json.loads(
                package.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )

        except Exception:
            continue

        licence = str(
            data.get("license")
            or ""
        ).strip().lower()

        aliases = {
            "mit":
                "mit",

            "apache-2.0":
                "apache-2.0",

            "bsd-2-clause":
                "bsd-2-clause",

            "bsd-3-clause":
                "bsd-3-clause",

            "isc":
                "isc",

            "mpl-2.0":
                "mpl-2.0",

            "unlicense":
                "unlicense",
        }

        if licence in aliases:
            return aliases[licence]

    return None
