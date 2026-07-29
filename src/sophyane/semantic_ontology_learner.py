"""Persistent semantic ontology with optional frontier-model guidance.

Design:
- Sophyane remains authority: LLM only proposes roles for unknown terms.
- Temporary ontology is request-scoped.
- Permanent promotion requires repeated successful use + confidence gate.
- Never rewrites frozen SLI anchors from a single model reply.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
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

ALLOWED_ROLES = {
    "ACTION",
    "COMMAND",
    "ARTIFACT",
    "RESOURCE",
    "PROPERTY",
    "LOCATION",
    "FORMAT",
    "STATE",
    "ERROR",
    "TECHNOLOGY",
}

STOP = {
    "a", "an", "the", "in", "on", "of", "my", "and", "or", "to", "for",
    "is", "are", "with", "from", "by", "at", "it", "this", "that", "me",
    "you", "please", "what", "whats", "there", "tell", "give", "all",
    "every", "some", "any", "as", "be", "been", "being", "was", "were",
    "do", "does", "did", "if", "then", "than", "so", "not", "no", "yes",
}

# Lightweight fallback when no API key / offline.
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

SYNONYMS = {
    "folders": "folder",
    "directories": "directory",
    "files": "file",
    "how": None,
    "many": None,
}


def _load() -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not ONTOLOGY_FILE.exists():
        return {"terms": {}, "updated_at": None}
    try:
        return json.loads(ONTOLOGY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"terms": {}, "updated_at": None}


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
        return SYNONYMS[t]
    return t


def extract_unknown_terms(text: str, known: set[str]) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_./+-]+", text.lower())
    out: list[str] = []
    seen: set[str] = set()
    for raw in tokens:
        can = canonicalize(raw)
        if not can or can in known or can in seen:
            continue
        seen.add(can)
        out.append(can)
    return out


def _gemini_propose(unknown: list[str], request: str) -> dict[str, dict[str, Any]]:
    """Ask Gemini for role proposals. Returns {} on failure."""
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
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Return JSON only, no markdown.\n"
                            + json.dumps(prompt, ensure_ascii=False)
                        )
                    }
                ],
            }
        ],
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
    # Offline / no-key fallback
    out: dict[str, dict[str, Any]] = {}
    for term in unknown:
        if term in FALLBACK_KNOWLEDGE:
            meta = FALLBACK_KNOWLEDGE[term]
            if float(meta["confidence"]) >= MIN_CONFIDENCE:
                out[term] = dict(meta)
    return out


def validate_proposals(
    proposals: dict[str, dict[str, Any]],
    unknown: list[str],
) -> dict[str, dict[str, Any]]:
    allowed_unknown = set(unknown)
    valid: dict[str, dict[str, Any]] = {}
    for term, meta in proposals.items():
        t = term.lower()
        if t not in allowed_unknown:
            continue
        role = str(meta.get("role", "")).upper()
        conf = float(meta.get("confidence", 0))
        if role not in ALLOWED_ROLES or conf < MIN_CONFIDENCE:
            continue
        valid[t] = {"role": role, "confidence": conf}
    return valid


def expand_for_request(request: str) -> dict[str, Any]:
    """Request-scoped expansion + optional permanent promotion bookkeeping later."""
    data = _load()
    terms: dict[str, Any] = data.setdefault("terms", {})
    # Only permanent (and optionally strong candidates) suppress re-learning.
    # Fallback knowledge supplies roles; it must not hide terms from the ledger.
    known = {
        k
        for k, v in terms.items()
        if v.get("status") == "permanent"
    }

    unknown = extract_unknown_terms(request, known)
    # Role proposals: LLM first, else fallback dictionary for those unknowns.
    proposals = validate_proposals(propose_roles(unknown, request), unknown)

    temporary = {
        t: {
            "role": m["role"],
            "confidence": m["confidence"],
            "status": "temporary",
            "source": "llm" if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") else "fallback",
        }
        for t, m in proposals.items()
    }

    # Seed candidates for newly seen validated terms (not permanent yet)
    for t, meta in temporary.items():
        if t not in terms:
            terms[t] = {
                "role": meta["role"],
                "confidence": meta["confidence"],
                "success_count": 0,
                "status": "candidate",
                "source": meta["source"],
                "last_seen": time.time(),
            }
    _save(data)

    return {
        "request": request,
        "unknown": unknown,
        "temporary": temporary,
        "permanent": {
            k: v for k, v in terms.items() if v.get("status") == "permanent"
        },
        "candidates": {
            k: v for k, v in terms.items() if v.get("status") == "candidate"
        },
        "path": str(ONTOLOGY_FILE),
    }


def record_success(request: str) -> dict[str, Any]:
    """Increment success_count for terms present in a successful request; promote."""
    data = _load()
    terms: dict[str, Any] = data.setdefault("terms", {})
    tokens = []
    for raw in re.findall(r"[A-Za-z0-9_./+-]+", request.lower()):
        can = canonicalize(raw)
        if can:
            tokens.append(can)

    promoted: list[str] = []
    for t in set(tokens):
        if t not in terms:
            continue
        entry = terms[t]
        entry["success_count"] = int(entry.get("success_count", 0)) + 1
        entry["last_seen"] = time.time()
        if (
            entry.get("status") != "permanent"
            and entry["success_count"] >= PROMOTION_THRESHOLD
            and float(entry.get("confidence", 0)) >= MIN_CONFIDENCE
        ):
            entry["status"] = "permanent"
            promoted.append(t)

    _save(data)
    return {"promoted": promoted, "terms": terms, "path": str(ONTOLOGY_FILE)}


def known_roles() -> dict[str, str]:
    data = _load()
    out: dict[str, str] = {}
    for t, meta in data.get("terms", {}).items():
        if meta.get("status") in {"permanent", "candidate"}:
            out[t] = str(meta.get("role", ""))
    return out


if __name__ == "__main__":
    import sys

    req = " ".join(sys.argv[1:]) or "list folders in my home directory"
    result = expand_for_request(req)
    print(json.dumps(result, indent=2))
    # Simulate successful grounded execution
    print("--- after success ---")
    print(json.dumps(record_success(req), indent=2)[:800])
