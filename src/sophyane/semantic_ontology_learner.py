"""Persistent semantic ontology with optional frontier-model guidance.

Richer ledger:
- term, role, confidence, success_count, status
- aliases / synonyms
- parent hierarchy
- action→object and object→property relations
- multi-context promotion (not only raw repeat count)
- confidence decay for unused concepts
- lightweight relation graph + bag-of-chars neighborhood (no heavy deps)

Sophyane remains authority: model only proposes; promotion is gated.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

STATE_DIR = Path(
    os.environ.get(
        "SOPHYANE_STATE_DIR",
        Path.home() / ".local" / "state" / "sophyane",
    )
).expanduser()
ONTOLOGY_FILE = STATE_DIR / "semantic_ontology_learned.json"

PROMOTION_THRESHOLD = int(os.environ.get("SOPHYANE_ONTOLOGY_PROMOTE_AFTER", "3"))
MIN_CONFIDENCE = float(os.environ.get("SOPHYANE_ONTOLOGY_MIN_CONF", "0.90"))
MIN_CONTEXTS = int(os.environ.get("SOPHYANE_ONTOLOGY_MIN_CONTEXTS", "2"))
DECAY_HALF_LIFE_DAYS = float(os.environ.get("SOPHYANE_ONTOLOGY_DECAY_DAYS", "30"))

ALLOWED_ROLES = {
    "ACTION", "COMMAND", "ARTIFACT", "RESOURCE", "PROPERTY",
    "LOCATION", "FORMAT", "STATE", "ERROR", "TECHNOLOGY",
}

STOP = {
    "a", "an", "the", "in", "on", "of", "my", "and", "or", "to", "for",
    "is", "are", "with", "from", "by", "at", "it", "this", "that", "me",
    "you", "please", "what", "whats", "there", "tell", "give", "all",
    "every", "some", "any", "as", "be", "been", "being", "was", "were",
    "do", "does", "did", "if", "then", "than", "so", "not", "no", "yes",
}

FALLBACK_KNOWLEDGE: dict[str, dict[str, Any]] = {
    "list": {"role": "COMMAND", "confidence": 0.96},
    "show": {"role": "COMMAND", "confidence": 0.95},
    "check": {"role": "COMMAND", "confidence": 0.95},
    "count": {"role": "COMMAND", "confidence": 0.96},
    "find": {"role": "COMMAND", "confidence": 0.95},
    "locate": {"role": "COMMAND", "confidence": 0.95},
    "create": {"role": "ACTION", "confidence": 0.97},
    "build": {"role": "ACTION", "confidence": 0.97},
    "folder": {"role": "RESOURCE", "confidence": 0.99},
    "folders": {"role": "RESOURCE", "confidence": 0.99},
    "directory": {"role": "RESOURCE", "confidence": 0.99},
    "directories": {"role": "RESOURCE", "confidence": 0.99},
    "file": {"role": "RESOURCE", "confidence": 0.99},
    "files": {"role": "RESOURCE", "confidence": 0.99},
    "home": {"role": "LOCATION", "confidence": 0.98},
    "drive": {"role": "LOCATION", "confidence": 0.97},
    "workspace": {"role": "LOCATION", "confidence": 0.97},
    "path": {"role": "PROPERTY", "confidence": 0.95},
    "name": {"role": "PROPERTY", "confidence": 0.95},
    "number": {"role": "PROPERTY", "confidence": 0.94},
    "size": {"role": "PROPERTY", "confidence": 0.95},
}

# Canonical synonym map (surface → canonical)
SYNONYMS = {
    "folders": "folder",
    "directories": "directory",
    "files": "file",
    "how": None,
    "many": None,
}

# Merge near-duplicates into one concept id
CANONICAL_MERGE = {
    "directory": "folder",  # folder ↔ directory as one RESOURCE concept
    "directories": "folder",
    "folders": "folder",
}

# Static seed hierarchy / relations (bootstrapped, then reinforced by use)
SEED_PARENTS = {
    "folder": "filesystem",
    "file": "filesystem",
    "home": "location",
    "workspace": "location",
    "drive": "location",
}
SEED_ACTION_OBJECTS = {
    "list": ["folder", "file"],
    "show": ["folder", "file"],
    "count": ["folder", "file"],
    "find": ["file", "folder"],
    "locate": ["file", "folder"],
    "create": ["file", "folder"],
}
SEED_PROPERTIES = {
    "folder": ["name", "count", "path", "size"],
    "file": ["name", "path", "size"],
}


def _empty() -> dict[str, Any]:
    return {
        "version": 2,
        "terms": {},
        "relations": [],  # list of {src, rel, dst, weight, contexts}
        "updated_at": None,
    }


def _load() -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not ONTOLOGY_FILE.exists():
        return _empty()
    try:
        data = json.loads(ONTOLOGY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    data.setdefault("version", 2)
    data.setdefault("terms", {})
    data.setdefault("relations", [])
    return data


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    tmp = ONTOLOGY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(ONTOLOGY_FILE)


def canonicalize(token: str) -> str | None:
    t = token.lower().strip(".,!?;:()[]{}\"'")
    if not t or t in STOP or len(t) <= 1:
        return None
    if t in SYNONYMS:
        mapped = SYNONYMS[t]
        if mapped is None:
            return None
        t = mapped
    if t in CANONICAL_MERGE:
        t = CANONICAL_MERGE[t]
    return t


def context_fingerprint(request: str) -> str:
    """Cheap multi-context key: sorted content tokens (no stopwords)."""
    toks = []
    for raw in re.findall(r"[A-Za-z0-9_./+-]+", request.lower()):
        c = canonicalize(raw)
        if c:
            toks.append(c)
    return "|".join(sorted(set(toks)))


def char_ngram_vec(term: str, n: int = 2) -> dict[str, float]:
    """Default bigrams — short words need smaller n for non-zero overlap."""
    s = f"#{term}#"
    counts: dict[str, float] = defaultdict(float)
    for i in range(max(0, len(s) - n + 1)):
        counts[s[i : i + n]] += 1.0
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    return sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)


def apply_decay(entry: dict[str, Any], now: float | None = None) -> float:
    """Return decayed confidence; mutates entry['confidence_effective']."""
    now = now or time.time()
    base = float(entry.get("confidence", 0.0))
    last = float(entry.get("last_seen", now))
    age_days = max(0.0, (now - last) / 86400.0)
    if DECAY_HALF_LIFE_DAYS <= 0:
        effective = base
    else:
        effective = base * (0.5 ** (age_days / DECAY_HALF_LIFE_DAYS))
    entry["confidence_effective"] = round(effective, 4)
    entry["age_days"] = round(age_days, 3)
    return effective


def extract_tokens(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9_./+-]+", text.lower()):
        c = canonicalize(raw)
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _ensure_term(terms: dict[str, Any], term: str, role: str, confidence: float, source: str) -> dict[str, Any]:
    if term not in terms:
        terms[term] = {
            "role": role,
            "confidence": confidence,
            "success_count": 0,
            "status": "candidate",
            "source": source,
            "last_seen": time.time(),
            "aliases": [],
            "parents": [],
            "contexts": [],
            "embedding": char_ngram_vec(term),
        }
    entry = terms[term]
    entry.setdefault("aliases", [])
    entry.setdefault("parents", [])
    entry.setdefault("contexts", [])
    entry.setdefault("embedding", char_ngram_vec(term))
    # seed hierarchy
    if term in SEED_PARENTS and SEED_PARENTS[term] not in entry["parents"]:
        entry["parents"].append(SEED_PARENTS[term])
    return entry


def _add_relation(
    relations: list[dict[str, Any]],
    src: str,
    rel: str,
    dst: str,
    ctx: str,
    weight: float = 1.0,
) -> None:
    for edge in relations:
        if edge.get("src") == src and edge.get("rel") == rel and edge.get("dst") == dst:
            edge["weight"] = float(edge.get("weight", 0)) + weight
            contexts = edge.setdefault("contexts", [])
            if ctx and ctx not in contexts:
                contexts.append(ctx)
                if len(contexts) > 20:
                    del contexts[:-20]
            return
    relations.append(
        {
            "src": src,
            "rel": rel,
            "dst": dst,
            "weight": weight,
            "contexts": [ctx] if ctx else [],
        }
    )


def reinforce_structure(data: dict[str, Any], tokens: list[str], request: str) -> None:
    """Update aliases, action-object, property links from co-occurrence + seeds."""
    terms = data["terms"]
    relations = data["relations"]
    ctx = context_fingerprint(request)
    roles = {t: terms[t]["role"] for t in tokens if t in terms}

    commands = [t for t, r in roles.items() if r in {"COMMAND", "ACTION"}]
    resources = [t for t, r in roles.items() if r == "RESOURCE"]
    properties = [t for t, r in roles.items() if r == "PROPERTY"]
    locations = [t for t, r in roles.items() if r == "LOCATION"]

    for cmd in commands:
        objs = list(resources)
        for seeded in SEED_ACTION_OBJECTS.get(cmd, []):
            if seeded in terms and seeded not in objs:
                objs.append(seeded)
        for obj in objs:
            _add_relation(relations, cmd, "acts_on", obj, ctx)

    for res in resources:
        props = list(properties)
        for seeded in SEED_PROPERTIES.get(res, []):
            if seeded in terms and seeded not in props:
                props.append(seeded)
        for prop in props:
            _add_relation(relations, res, "has_property", prop, ctx)
        for loc in locations:
            _add_relation(relations, res, "located_in", loc, ctx)

    # alias bookkeeping for merge map reverse
    for surface, canon in CANONICAL_MERGE.items():
        if canon in terms and surface != canon:
            aliases = terms[canon].setdefault("aliases", [])
            if surface not in aliases:
                aliases.append(surface)


def _gemini_propose(unknown: list[str], request: str) -> dict[str, dict[str, Any]]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key or not unknown:
        return {}
    model = os.environ.get("SOPHYANE_ONTOLOGY_MODEL", "gemini-2.0-flash")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    prompt = {
        "known_roles": sorted(ALLOWED_ROLES),
        "unknown_terms": unknown,
        "task": (
            "Assign semantic roles ONLY for unknown_terms. "
            "Return JSON object mapping term -> {role, confidence}. "
            "confidence in [0,1]. Do not invent terms. Do not plan actions."
        ),
        "request_context": request[:500],
    }
    body = {
        "contents": [{
            "role": "user",
            "parts": [{"text": "Return JSON only, no markdown.\n" + json.dumps(prompt)}],
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        cleaned: dict[str, dict[str, Any]] = {}
        for term, meta in data.items():
            if not isinstance(meta, dict):
                continue
            role = str(meta.get("role", "")).upper()
            conf = float(meta.get("confidence", 0))
            if role in ALLOWED_ROLES and conf >= MIN_CONFIDENCE:
                cleaned[str(term).lower()] = {"role": role, "confidence": conf}
        return cleaned
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def propose_roles(unknown: list[str], request: str) -> dict[str, dict[str, Any]]:
    proposed = _gemini_propose(unknown, request)
    if proposed:
        return proposed
    out: dict[str, dict[str, Any]] = {}
    for term in unknown:
        # also try pre-merge surface forms in FALLBACK
        for key in (term, term + "s"):
            if key in FALLBACK_KNOWLEDGE:
                meta = FALLBACK_KNOWLEDGE[key]
                if float(meta["confidence"]) >= MIN_CONFIDENCE:
                    out[term] = dict(meta)
                    break
    return out


def validate_proposals(
    proposals: dict[str, dict[str, Any]],
    unknown: list[str],
) -> dict[str, dict[str, Any]]:
    allowed = set(unknown)
    valid: dict[str, dict[str, Any]] = {}
    for term, meta in proposals.items():
        t = canonicalize(term) or term.lower()
        if t not in allowed:
            continue
        role = str(meta.get("role", "")).upper()
        conf = float(meta.get("confidence", 0))
        if role not in ALLOWED_ROLES or conf < MIN_CONFIDENCE:
            continue
        valid[t] = {"role": role, "confidence": conf}
    return valid


def expand_for_request(request: str) -> dict[str, Any]:
    data = _load()
    terms: dict[str, Any] = data.setdefault("terms", {})
    known = {k for k, v in terms.items() if v.get("status") == "permanent"}
    tokens = extract_tokens(request)
    unknown = [t for t in tokens if t not in known]

    proposals = validate_proposals(propose_roles(unknown, request), unknown)
    source = (
        "llm"
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        else "fallback"
    )
    temporary: dict[str, Any] = {}
    for t, meta in proposals.items():
        temporary[t] = {
            "role": meta["role"],
            "confidence": meta["confidence"],
            "status": "temporary",
            "source": source,
        }
        _ensure_term(terms, t, meta["role"], meta["confidence"], source)

    # also ensure permanent/candidate tokens present for relation building
    for t in tokens:
        if t in terms:
            continue
        if t in FALLBACK_KNOWLEDGE:
            m = FALLBACK_KNOWLEDGE[t]
            _ensure_term(terms, t, m["role"], float(m["confidence"]), "fallback")

    reinforce_structure(data, extract_tokens(request), request)
    _save(data)

    for e in terms.values():
        apply_decay(e)

    return {
        "request": request,
        "unknown": unknown,
        "temporary": temporary,
        "permanent": {k: v for k, v in terms.items() if v.get("status") == "permanent"},
        "candidates": {k: v for k, v in terms.items() if v.get("status") == "candidate"},
        "relations_sample": data.get("relations", [])[:12],
        "path": str(ONTOLOGY_FILE),
    }


def record_success(request: str) -> dict[str, Any]:
    data = _load()
    terms: dict[str, Any] = data.setdefault("terms", {})
    tokens = extract_tokens(request)
    ctx = context_fingerprint(request)
    promoted: list[str] = []

    for t in tokens:
        if t not in terms:
            if t in FALLBACK_KNOWLEDGE:
                m = FALLBACK_KNOWLEDGE[t]
                _ensure_term(terms, t, m["role"], float(m["confidence"]), "fallback")
            else:
                continue
        entry = terms[t]
        entry["success_count"] = int(entry.get("success_count", 0)) + 1
        entry["last_seen"] = time.time()
        contexts = entry.setdefault("contexts", [])
        if ctx and ctx not in contexts:
            contexts.append(ctx)
            if len(contexts) > 30:
                del contexts[:-30]

        n_ctx = len(entry.get("contexts", []))
        conf = apply_decay(entry)
        if (
            entry.get("status") != "permanent"
            and entry["success_count"] >= PROMOTION_THRESHOLD
            and n_ctx >= MIN_CONTEXTS
            and conf >= MIN_CONFIDENCE
        ):
            entry["status"] = "permanent"
            promoted.append(t)
        # single-context friendly bootstrap: if only one context ever, still allow
        # promotion after higher success bar
        elif (
            entry.get("status") != "permanent"
            and entry["success_count"] >= PROMOTION_THRESHOLD * 2
            and conf >= MIN_CONFIDENCE
        ):
            entry["status"] = "permanent"
            promoted.append(t)

    reinforce_structure(data, tokens, request)
    _save(data)
    return {
        "promoted": promoted,
        "terms": terms,
        "relations": data.get("relations", []),
        "path": str(ONTOLOGY_FILE),
    }


def known_roles() -> dict[str, str]:
    data = _load()
    out: dict[str, str] = {}
    for t, meta in data.get("terms", {}).items():
        if meta.get("status") in {"permanent", "candidate"}:
            apply_decay(meta)
            out[t] = str(meta.get("role", ""))
    return out


def _jaccard(left: Any, right: Any) -> float:
    """Return Jaccard similarity for two iterable collections."""
    a = {str(x).lower() for x in (left or []) if str(x).strip()}
    b = {str(x).lower() for x in (right or []) if str(x).strip()}

    if not a or not b:
        return 0.0

    return len(a & b) / len(a | b)


def _relation_neighbors(
    data: dict[str, Any],
    term: str,
) -> set[tuple[str, str]]:
    """Return relation-labelled neighbors in either graph direction."""
    neighbors: set[tuple[str, str]] = set()

    for edge in data.get("relations", []):
        src = canonicalize(str(edge.get("src", "")))
        dst = canonicalize(str(edge.get("dst", "")))
        rel = str(edge.get("rel", "")).strip().lower()

        if not src or not dst or not rel:
            continue

        if src == term:
            neighbors.add((rel, dst))

        if dst == term:
            neighbors.add((f"inverse:{rel}", src))

    return neighbors


def _direct_relation_score(
    data: dict[str, Any],
    left: str,
    right: str,
) -> float:
    """Return bounded evidence for a direct graph connection."""
    best = 0.0

    for edge in data.get("relations", []):
        src = canonicalize(str(edge.get("src", "")))
        dst = canonicalize(str(edge.get("dst", "")))

        if {src, dst} != {left, right}:
            continue

        weight = max(0.0, float(edge.get("weight", 0.0)))
        best = max(best, min(1.0, math.log1p(weight) / math.log(11.0)))

    return best


def _semantic_similarity(
    data: dict[str, Any],
    left: str,
    right: str,
) -> float:
    """Combine lexical, alias, role, hierarchy, context, and graph evidence."""
    terms = data.get("terms", {})
    left_meta = terms.get(left, {})
    right_meta = terms.get(right, {})

    left_vec = left_meta.get("embedding") or char_ngram_vec(left)
    right_vec = right_meta.get("embedding") or char_ngram_vec(right)
    lexical = cosine(left_vec, right_vec)

    left_aliases = {
        canonicalize(str(alias))
        for alias in left_meta.get("aliases", [])
        if canonicalize(str(alias))
    }
    right_aliases = {
        canonicalize(str(alias))
        for alias in right_meta.get("aliases", [])
        if canonicalize(str(alias))
    }

    alias_match = (
        right in left_aliases
        or left in right_aliases
        or bool(left_aliases & right_aliases)
    )

    left_role = str(left_meta.get("role", "")).upper()
    right_role = str(right_meta.get("role", "")).upper()
    same_role = bool(left_role and left_role == right_role)

    parent_similarity = _jaccard(
        left_meta.get("parents", []),
        right_meta.get("parents", []),
    )

    context_similarity = _jaccard(
        left_meta.get("contexts", []),
        right_meta.get("contexts", []),
    )

    left_neighbors = _relation_neighbors(data, left)
    right_neighbors = _relation_neighbors(data, right)
    neighbor_similarity = _jaccard(left_neighbors, right_neighbors)

    direct_relation = _direct_relation_score(data, left, right)

    score = (
        0.30 * lexical
        + 0.40 * float(alias_match)
        + 0.08 * float(same_role)
        + 0.08 * parent_similarity
        + 0.06 * context_similarity
        + 0.06 * neighbor_similarity
        + 0.02 * direct_relation
    )

    # Explicit aliases must always rank as strongly related.
    if alias_match:
        score = max(score, 0.85)

    return round(min(1.0, max(0.0, score)), 6)


def repair_bidirectional_aliases(
    data: dict[str, Any] | None = None,
    *,
    save: bool = True,
) -> dict[str, Any]:
    """Make known alias relationships reciprocal and normalize embeddings."""
    ontology = data if data is not None else _load()
    terms = ontology.setdefault("terms", {})
    additions = 0

    # First normalize every existing term.
    for term, meta in list(terms.items()):
        meta.setdefault("aliases", [])
        meta.setdefault("parents", [])
        meta.setdefault("contexts", [])
        meta["embedding"] = char_ngram_vec(term)

        parent = SEED_PARENTS.get(term)
        if parent and parent not in meta["parents"]:
            meta["parents"].append(parent)

    # Then make aliases reciprocal where both terms exist.
    for term, meta in list(terms.items()):
        normalized_aliases = []

        for raw_alias in meta.get("aliases", []):
            alias = canonicalize(str(raw_alias))

            if not alias or alias == term:
                continue

            if alias not in normalized_aliases:
                normalized_aliases.append(alias)

            alias_meta = terms.get(alias)
            if alias_meta is None:
                continue

            reverse = alias_meta.setdefault("aliases", [])
            if term not in reverse:
                reverse.append(term)
                additions += 1

        meta["aliases"] = normalized_aliases

    ontology["updated_at"] = time.time()

    if save:
        _save(ontology)

    return {
        "alias_links_added": additions,
        "term_count": len(terms),
        "path": str(ONTOLOGY_FILE),
    }


def similar_terms(term: str, limit: int = 5) -> list[tuple[str, float]]:
    """Return graph-aware semantic neighbors for a known or unknown term."""
    data = _load()
    terms = data.get("terms", {})
    target = canonicalize(term) or term.lower().strip()

    # Allow querying an alias even when it is not its own canonical entry.
    if target not in terms:
        for candidate, meta in terms.items():
            aliases = {
                canonicalize(str(alias))
                for alias in meta.get("aliases", [])
            }
            if target in aliases:
                target = candidate
                break

    scored: list[tuple[str, float]] = []

    for other in terms:
        if other == target:
            continue

        score = _semantic_similarity(data, target, other)
        scored.append((other, score))

    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[: max(0, int(limit))]


def relation_graph_summary(limit: int = 30) -> list[dict[str, Any]]:
    data = _load()
    rels = sorted(
        data.get("relations", []),
        key=lambda e: float(e.get("weight", 0)),
        reverse=True,
    )
    return rels[:limit]


if __name__ == "__main__":
    import sys

    req = " ".join(sys.argv[1:]) or "list folders in my home directory"
    print(json.dumps(expand_for_request(req), indent=2)[:2000])
    print("--- success ---")
    print(json.dumps(record_success(req), indent=2)[:2000])
    print("--- similar(folder) ---")
    print(similar_terms("folder"))
    print("--- top relations ---")
    print(json.dumps(relation_graph_summary(8), indent=2))
