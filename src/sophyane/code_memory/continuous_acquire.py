
"""Continuous chunk acquisition from local code roots and GitHub clones.

Safety:
- Only scans configured roots (not arbitrary system secrets).
- Skips .git, venv, node_modules, caches, huge files.
- Rate-limited batches so it can run forever in the background.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from sophyane.code_memory.acquire import acquire_tree
from sophyane.code_memory.merge import auto_merge_by_shared_tags, merge_chunks
from sophyane.code_memory.store import ChunkStore
from collections import defaultdict


DEFAULT_LOCAL_ROOTS = [
    str(Path.home() / "sophyane-repo"),
    str(Path.home() / "hermes-agent"),
    str(Path.home() / "code"),
    str(Path.home() / "repos"),
    str(Path.home() / "github"),
    str(Path.home() / "src"),
    str(Path.home() / "projects"),
    str(Path.home() / "SHMRY"),
    str(Path.home() / "NIFDU"),
]

# High-signal public corpora (shallow clone into SOPHYANE_HOME/github_cache)
DEFAULT_GITHUB_REPOS = [
    "https://github.com/sindresorhus/awesome.git",  # mostly markdown; low code — replaced below
]

# Prefer actual code-heavy small/medium repos as starters
DEFAULT_GITHUB_REPOS = [
    "https://github.com/pallets/flask.git",
    "https://github.com/encode/starlette.git",
    "https://github.com/tiangolo/fastapi.git",
    "https://github.com/expressjs/express.git",
    "https://github.com/jquery/jquery.git",
]


def _home() -> Path:
    return Path(os.environ.get("SOPHYANE_HOME", Path.home() / ".local/share/sophyane")).expanduser()


def config_path() -> Path:
    return _home() / "code_memory" / "acquire_sources.json"


def state_path() -> Path:
    return _home() / "code_memory" / "continuous_state.json"


def github_cache() -> Path:
    d = _home() / "github_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_config() -> dict:
    path = config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg = {
        "local_roots": DEFAULT_LOCAL_ROOTS,
        "github_repos": DEFAULT_GITHUB_REPOS,
        "limit_files_per_root": 80,
        "limit_chunks_per_root": 250,
        "sleep_seconds": 120,
        "enable_github": True,
        "enable_local": True,
        "auto_merge": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def load_state() -> dict:
    path = state_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"cursor": 0, "cycles": 0, "last_report": None}


def save_state(state: dict) -> None:
    state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def ensure_github_clone(url: str) -> Path | None:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    dest = github_cache() / name
    if dest.exists():
        # cheap update
        try:
            subprocess.run(
                ["git", "-C", str(dest), "pull", "--ff-only"],
                check=False, capture_output=True, timeout=120,
            )
        except Exception:
            pass
        return dest
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=False, capture_output=True, timeout=300,
        )
        return dest if dest.exists() else None
    except Exception:
        return None


def family_merge(store: ChunkStore, max_merges: int = 10) -> int:
    families: dict[str, list[str]] = defaultdict(list)
    for cid, c in store.chunks.items():
        if (c.meta or {}).get("kind") == "rich":
            continue
        path = c.path or ""
        family = path.split("::", 1)[0] if "::" in path else str(Path(path).parent if path else "unknown")
        families[family].append(cid)
    n = 0
    for family, ids in sorted(families.items(), key=lambda kv: -len(kv[1])):
        if n >= max_merges:
            break
        if len(ids) < 2:
            continue
        rich = merge_chunks(store, ids[:5], name=Path(family).name or "family", tags=["family"])
        if rich is not None:
            n += 1
    return n


def one_cycle(progress=None) -> dict:
    progress = progress or print
    cfg = load_config()
    state = load_state()
    reports = []

    roots: list[Path] = []
    if cfg.get("enable_local", True):
        for r in cfg.get("local_roots") or []:
            p = Path(r).expanduser()
            if p.exists():
                roots.append(p)

    if cfg.get("enable_github", True):
        for url in cfg.get("github_repos") or []:
            progress(f"github: ensure {url}")
            cloned = ensure_github_clone(url)
            if cloned is not None:
                roots.append(cloned)

    if not roots:
        return {"error": "no roots available", "memory": len(ChunkStore().ids)}

    # rotate through roots so continuous runs cover everything over time
    idx = int(state.get("cursor") or 0) % len(roots)
    chosen = roots[idx]
    state["cursor"] = idx + 1
    progress(f"cycle root [{idx+1}/{len(roots)}]: {chosen}")

    rep = acquire_tree(
        chosen,
        limit_files=int(cfg.get("limit_files_per_root") or 80),
        limit_chunks=int(cfg.get("limit_chunks_per_root") or 250),
        source=f"continuous:{chosen.name}",
        progress=progress,
    )
    reports.append(rep)

    merged = 0
    if cfg.get("auto_merge", True):
        store = ChunkStore()
        merged = family_merge(store, max_merges=8)
        try:
            auto_merge_by_shared_tags(store, min_parts=2, max_merges=5)
        except Exception:
            pass

    state["cycles"] = int(state.get("cycles") or 0) + 1
    state["last_report"] = {
        "ts": time.time(),
        "root": str(chosen),
        "acquire": rep,
        "rich_merged": merged,
        "memory": len(ChunkStore().ids),
    }
    save_state(state)
    progress(f"memory now: {state['last_report']['memory']} rich_merged={merged}")
    return state["last_report"]


def run_forever() -> None:
    cfg = load_config()
    sleep_s = float(cfg.get("sleep_seconds") or 120)
    print(f"continuous acquire started; sleep={sleep_s}s; config={config_path()}")
    while True:
        try:
            one_cycle(progress=print)
        except KeyboardInterrupt:
            print("stopped")
            return
        except Exception as e:
            print(f"cycle error: {e}")
        time.sleep(sleep_s)

# SOPHYANE_REVISION_MANIFEST_V1
#
# Skip unchanged repository roots before file traversal and avoid merging when
# the current cycle learned no new chunks.

_one_cycle_before_revision_manifest = one_cycle


def one_cycle(progress=None) -> dict:
    from sophyane.code_memory.repository_efficiency import (
        record_manifest,
        repository_revision,
        should_skip_revision,
        unchanged_report,
    )

    progress = progress or print
    cfg = load_config()
    state = load_state()

    roots: list[Path] = []

    if cfg.get("enable_local", True):
        for raw_root in (
            cfg.get("local_roots")
            or []
        ):
            root = Path(
                raw_root
            ).expanduser()

            if root.exists():
                roots.append(
                    root
                )

    if cfg.get("enable_github", True):
        for url in (
            cfg.get("github_repos")
            or []
        ):
            progress(
                f"github: ensure {url}"
            )

            cloned = ensure_github_clone(
                url
            )

            if cloned is not None:
                roots.append(
                    cloned
                )

    if not roots:
        return {
            "error":
                "no roots available",

            "memory":
                len(
                    ChunkStore().ids
                ),
        }

    index = (
        int(
            state.get(
                "cursor"
            )
            or 0
        )
        % len(roots)
    )

    chosen = roots[index]

    state["cursor"] = (
        index
        + 1
    )

    progress(
        "cycle root "
        f"[{index + 1}/{len(roots)}]: "
        f"{chosen}"
    )

    limit_files = int(
        cfg.get(
            "limit_files_per_root"
        )
        or 80
    )

    limit_chunks = int(
        cfg.get(
            "limit_chunks_per_root"
        )
        or 250
    )

    source = (
        "continuous:"
        + chosen.name
    )

    revision = repository_revision(
        chosen
    )

    skip, reason = should_skip_revision(
        chosen,
        source=source,
        revision=revision,
        limit_files=limit_files,
        limit_chunks=limit_chunks,
    )

    if skip:
        memory_size = len(
            ChunkStore().ids
        )

        report = unchanged_report(
            chosen,
            revision=revision,
            memory_size=memory_size,
            reason=reason,
        )

        progress(
            "revision manifest hit: "
            f"{chosen}; {reason}"
        )

        merged = 0

    else:
        progress(
            "revision manifest miss: "
            f"{reason}; revision={revision[:36]}"
        )

        report = acquire_tree(
            chosen,
            limit_files=limit_files,
            limit_chunks=limit_chunks,
            source=source,
            progress=progress,
        )

        report["revision"] = (
            revision
        )

        manifest = record_manifest(
            chosen,
            source=source,
            revision=revision,
            limit_files=limit_files,
            limit_chunks=limit_chunks,
            report=report,
        )

        report["manifest"] = str(
            manifest
        )

        learned = int(
            report.get(
                "chunks_added",
                0,
            )
            or 0
        )

        merged = 0

        if (
            learned > 0
            and cfg.get(
                "auto_merge",
                True,
            )
        ):
            store = ChunkStore()

            merged = family_merge(
                store,
                max_merges=8,
            )

            try:
                auto_merge_by_shared_tags(
                    store,
                    min_parts=2,
                    max_merges=5,
                )
            except Exception:
                pass

        elif learned == 0:
            progress(
                "merge skipped: acquisition added zero chunks"
            )

    state["cycles"] = (
        int(
            state.get(
                "cycles"
            )
            or 0
        )
        + 1
    )

    state["last_report"] = {
        "ts":
            time.time(),

        "root":
            str(chosen),

        "acquire":
            report,

        "rich_merged":
            merged,

        "memory":
            len(
                ChunkStore().ids
            ),
    }

    save_state(
        state
    )

    progress(
        "memory now: "
        f"{state['last_report']['memory']} "
        f"rich_merged={merged}"
    )

    return state[
        "last_report"
    ]

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        print(json.dumps(one_cycle(progress=print), indent=2))
    else:
        run_forever()
