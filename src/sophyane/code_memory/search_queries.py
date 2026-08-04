"""Short, searchable identity queries for SLI internet acquire."""
from __future__ import annotations
import re

STOP = {
    "make", "create", "build", "a", "an", "the", "complete", "simple",
    "interactive", "self", "contained", "index", "html", "please",
    "produce", "one", "with", "and", "for", "in", "on", "of", "to",
    "application", "app", "website", "webpage", "browser", "javascript",
    "source", "exactly", "file", "implementing", "implement", "named",
    "returning", "json", "parameters", "adjustable", "responsive",
}

ALIASES = {
    "ping": "pong",
    "pingpong": "pong",
    "pong": "pong",
    "snake": "snake",
    "dashboard": "dashboard",
    "registry": "registry",
    "crud": "crud",
    "todo": "todo",
    "calculator": "calculator",
    "simulation": "simulation",
    "spring": "spring",
    "oscillation": "oscillation",
    "memory": "memory",
    "match": "match",
    "kids": "kids",
    "phonics": "phonics",
}

def _tokens(request: str) -> list[str]:
    r = re.sub(r"[^a-z0-9\s\-+]", " ", (request or "").lower())
    out: list[str] = []
    for t in r.split():
        if not t or t in STOP or len(t) < 2:
            continue
        out.append(ALIASES.get(t, t))
    # de-dupe preserve order
    seen = set()
    uniq = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:8]

def build_search_queries(request: str) -> list[str]:
    toks = _tokens(request)
    if not toks:
        return ["canvas html game in:name"]
    # Prefer 1-2 core identity terms, never the full sentence
    core = toks[:3]
    primary = " ".join(core[:2])
    qs = [
        f'"{primary}" in:name' if len(core) >= 2 else f"{core[0]} in:name",
        f"{core[0]} canvas javascript in:name,description",
        f"{core[0]} html5 in:name,description",
        f"{' '.join(core[:3])} javascript in:name,description",
    ]
    # family hints
    low = (request or "").lower()
    if "dashboard" in low:
        qs.insert(0, "dashboard javascript html in:name,description")
    if any(x in low for x in ("registry", "crud", "student", "todo")):
        qs.insert(0, "todo localStorage javascript in:name,description")
        qs.insert(0, "crud javascript html in:name,description")
    if "simulation" in low or "spring" in low:
        qs.insert(0, "spring simulation canvas javascript in:name,description")
        qs.insert(0, "physics simulation canvas in:name,description")
    if "pong" in low or "ping" in low:
        qs = ['"pong" in:name', "pong canvas html in:name", "ping-pong javascript in:name"]
    if "snake" in low:
        qs = ['"snake" game canvas in:name', "snake canvas javascript in:name,description"]
    # unique preserve order, max 5
    seen = set()
    out = []
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:5]

def candidate_matches_request(full_name: str, description: str, request: str) -> bool:
    blob = f"{full_name} {description}".lower()
    toks = _tokens(request)
    if not toks:
        return True
    hits = sum(1 for t in toks[:4] if t in blob)
    return hits >= 1
