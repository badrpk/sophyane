"""Blockchain-style append-only improvement ledger for Sophyane.

Devices propose improvements (prompt tweaks, docs, configs, learned facts).
Blocks are hash-linked. Daily epochs can be exported and published to GitHub
as an improvements catalog (not untrusted auto-merge of arbitrary code).
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
LEDGER_PATH = STATE_DIR / "improvement_chain.jsonl"
EPOCH_DIR = STATE_DIR / "improvement_epochs"
REPO_IMPROVEMENTS = Path(__file__).resolve().parents[3] / "improvements"


@dataclass
class ImprovementProposal:
    proposal_id: str
    kind: str  # fact | prompt | config | benchmark | scrape_insight | code_hint
    title: str
    body: str
    source_device: str
    evidence: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerBlock:
    index: int
    timestamp: float
    proposal: dict[str, Any]
    prev_hash: str
    hash: str
    device: str
    version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _device_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()).hex[:8]}"


def _hash_block(
    index: int,
    timestamp: float,
    proposal: dict[str, Any],
    prev_hash: str,
    device: str,
    version: str | None = None,
) -> str:
    payload = json.dumps(
        {
            "index": index,
            "timestamp": timestamp,
            "proposal": proposal,
            "prev_hash": prev_hash,
            "device": device,
            "version": version or __version__,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_blocks() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    blocks: list[dict[str, Any]] = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            blocks.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return blocks


def chain_tip() -> dict[str, Any]:
    blocks = _load_blocks()
    if not blocks:
        return {"index": -1, "hash": "0" * 64, "length": 0}
    last = blocks[-1]
    return {"index": last.get("index", len(blocks) - 1), "hash": last.get("hash"), "length": len(blocks)}


def verify_chain() -> dict[str, Any]:
    blocks = _load_blocks()
    if not blocks:
        return {"ok": True, "length": 0, "message": "empty chain"}
    prev = "0" * 64
    for i, block in enumerate(blocks):
        expected = _hash_block(
            int(block["index"]),
            float(block["timestamp"]),
            block["proposal"],
            block["prev_hash"],
            str(block.get("device") or ""),
            version=str(block.get("version") or __version__),
        )
        if block.get("prev_hash") != prev:
            return {"ok": False, "error": f"prev_hash mismatch at {i}", "length": len(blocks)}
        if block.get("hash") != expected:
            return {"ok": False, "error": f"hash mismatch at {i}", "length": len(blocks)}
        if int(block.get("index", -1)) != i:
            return {"ok": False, "error": f"index mismatch at {i}", "length": len(blocks)}
        prev = block["hash"]
    return {"ok": True, "length": len(blocks), "tip": prev}


def propose_improvement(
    kind: str,
    title: str,
    body: str,
    *,
    evidence: dict[str, Any] | None = None,
    score: float = 0.0,
) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tip = chain_tip()
    proposal = ImprovementProposal(
        proposal_id=str(uuid.uuid4()),
        kind=(kind or "fact").strip().lower()[:40],
        title=(title or "untitled")[:200],
        body=(body or "")[:8000],
        source_device=_device_id(),
        evidence=evidence or {},
        score=float(score),
    )
    index = int(tip["index"]) + 1
    timestamp = time.time()
    prev_hash = str(tip["hash"])
    device = proposal.source_device
    block_hash = _hash_block(
        index, timestamp, proposal.to_dict(), prev_hash, device, version=__version__
    )
    block = LedgerBlock(
        index=index,
        timestamp=timestamp,
        proposal=proposal.to_dict(),
        prev_hash=prev_hash,
        hash=block_hash,
        device=device,
        version=__version__,
    )
    with LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(block.to_dict(), ensure_ascii=False) + "\n")
    return {"ok": True, "block": block.to_dict()}


def list_proposals(limit: int = 50) -> list[dict[str, Any]]:
    blocks = _load_blocks()
    return blocks[-limit:]


def export_daily_epoch(day: str | None = None) -> dict[str, Any]:
    """Bundle today's proposals into an epoch file (local + repo improvements/)."""
    day = day or time.strftime("%Y-%m-%d")
    blocks = _load_blocks()
    day_blocks = []
    for block in blocks:
        ts = float(block.get("timestamp") or 0)
        if time.strftime("%Y-%m-%d", time.localtime(ts)) == day:
            day_blocks.append(block)

    epoch = {
        "day": day,
        "exported_at": time.time(),
        "device": _device_id(),
        "sophyane_version": __version__,
        "chain_verify": verify_chain(),
        "count": len(day_blocks),
        "blocks": day_blocks,
        "merkle_root": _merkle_root([str(b.get("hash")) for b in day_blocks]),
    }

    EPOCH_DIR.mkdir(parents=True, exist_ok=True)
    local_path = EPOCH_DIR / f"epoch-{day}.json"
    local_path.write_text(json.dumps(epoch, indent=2) + "\n", encoding="utf-8")

    # Also write into repo tree when running from a git checkout
    repo_dir = REPO_IMPROVEMENTS
    try:
        repo_dir.mkdir(parents=True, exist_ok=True)
        repo_path = repo_dir / f"epoch-{day}.json"
        repo_path.write_text(json.dumps(epoch, indent=2) + "\n", encoding="utf-8")
        # append to catalog
        catalog = repo_dir / "CATALOG.md"
        line = f"- {day}: {len(day_blocks)} proposals · merkle `{epoch['merkle_root'][:16]}…` · device `{epoch['device']}`\n"
        if catalog.exists():
            existing = catalog.read_text(encoding="utf-8")
            if day not in existing:
                catalog.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
        else:
            catalog.write_text(
                "# Sophyane daily improvement catalog\n\n"
                "Hash-linked proposals from the field mesh. "
                "Human/CI review before code merges.\n\n" + line,
                encoding="utf-8",
            )
        epoch["repo_path"] = str(repo_path)
    except OSError:
        epoch["repo_path"] = ""

    epoch["local_path"] = str(local_path)
    return epoch


def _merkle_root(hashes: list[str]) -> str:
    if not hashes:
        return hashlib.sha256(b"empty").hexdigest()
    layer = [h.encode("utf-8") for h in hashes]
    while len(layer) > 1:
        nxt: list[bytes] = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else left
            nxt.append(hashlib.sha256(left + right).hexdigest().encode("utf-8"))
        layer = nxt
    return layer[0].decode("utf-8") if isinstance(layer[0], bytes) else str(layer[0])


def ingest_remote_epoch(epoch: dict[str, Any]) -> dict[str, Any]:
    """Merge proposals from another device epoch into local chain (idempotent by proposal_id)."""
    existing = _load_blocks()
    seen = {
        str((b.get("proposal") or {}).get("proposal_id"))
        for b in existing
        if isinstance(b.get("proposal"), dict)
    }
    added = 0
    for block in epoch.get("blocks") or []:
        prop = block.get("proposal") if isinstance(block, dict) else None
        if not isinstance(prop, dict):
            continue
        pid = str(prop.get("proposal_id") or "")
        if not pid or pid in seen:
            continue
        propose_improvement(
            str(prop.get("kind") or "fact"),
            str(prop.get("title") or "remote"),
            str(prop.get("body") or ""),
            evidence={
                **(prop.get("evidence") or {}),
                "remote_device": prop.get("source_device"),
                "ingested_from_epoch": epoch.get("day"),
            },
            score=float(prop.get("score") or 0),
        )
        seen.add(pid)
        added += 1
    return {"ok": True, "added": added, "tip": chain_tip()}


def auto_propose_from_scrape(scrape_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn scrape summaries into ledger proposals."""
    created = []
    for item in scrape_bundle.get("results") or []:
        if not item.get("ok"):
            continue
        title = f"Web insight: {item.get('title') or item.get('url')}"
        body = (
            f"Source: {item.get('url')}\n"
            f"Hash: {item.get('hash')}\n\n"
            f"{item.get('summary') or ''}"
        )
        created.append(
            propose_improvement(
                "scrape_insight",
                title[:200],
                body,
                evidence={"url": item.get("url"), "hash": item.get("hash")},
                score=0.3,
            )
        )
    return created
