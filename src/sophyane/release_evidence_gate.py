from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from typing import Iterable


class EvidenceGateError(ValueError):
    pass


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Evidence:
    peer: str
    capability: str
    kind: str
    status: str
    artifact_hash: str = ""

    def __post_init__(self):
        if not self.peer.strip() or not self.capability.strip():
            raise EvidenceGateError("peer and capability are required")
        if self.kind not in {"health", "native", "render", "security", "persistence", "compiler", "transport"}:
            raise EvidenceGateError(f"unsupported evidence kind: {self.kind}")
        if self.status not in {"pass", "fail", "skip"}:
            raise EvidenceGateError(f"unsupported evidence status: {self.status}")
        if self.artifact_hash and (len(self.artifact_hash) != 64 or any(c not in "0123456789abcdef" for c in self.artifact_hash.lower())):
            raise EvidenceGateError("artifact_hash must be a SHA-256 hex digest")


@dataclass(frozen=True)
class Requirement:
    peer: str
    capability: str
    minimum_kind: str


_KIND_RANK = {
    "health": 1,
    "render": 2,
    "persistence": 2,
    "compiler": 2,
    "transport": 2,
    "security": 3,
    "native": 4,
}


class ReleaseEvidenceGate:
    """Evaluate release readiness from explicitly scoped cross-repository evidence."""

    def __init__(self, requirements: Iterable[Requirement]):
        self.requirements = tuple(requirements)
        seen = set()
        for req in self.requirements:
            key = (req.peer, req.capability)
            if key in seen:
                raise EvidenceGateError(f"duplicate requirement: {req.peer}/{req.capability}")
            seen.add(key)
            if req.minimum_kind not in _KIND_RANK:
                raise EvidenceGateError(f"unsupported minimum kind: {req.minimum_kind}")

    def evaluate(self, evidence: Iterable[Evidence]) -> dict:
        evidence = tuple(evidence)
        index: dict[tuple[str, str], list[Evidence]] = {}
        for item in evidence:
            index.setdefault((item.peer, item.capability), []).append(item)

        checks = []
        ready = True
        for req in self.requirements:
            candidates = index.get((req.peer, req.capability), [])
            passing = [
                item for item in candidates
                if item.status == "pass"
                and _KIND_RANK[item.kind] >= _KIND_RANK[req.minimum_kind]
            ]
            failed = any(item.status == "fail" for item in candidates)
            ok = bool(passing) and not failed
            ready = ready and ok
            checks.append({
                "peer": req.peer,
                "capability": req.capability,
                "minimum_kind": req.minimum_kind,
                "ok": ok,
                "observed": sorted({f"{item.kind}:{item.status}" for item in candidates}),
            })

        body = {
            "format": "sophyane-release-evidence-v1",
            "ready": ready,
            "checks": checks,
        }
        return {**body, "evidence_hash": _hash(body)}


def default_requirements() -> tuple[Requirement, ...]:
    return (
        Requirement("xerus", "memory", "persistence"),
        Requirement("nifdu", "visual-verification", "render"),
        Requirement("Veyron", "transport", "transport"),
        Requirement("Lexane", "compile", "compiler"),
        Requirement("Cosmos", "integration", "health"),
    )
