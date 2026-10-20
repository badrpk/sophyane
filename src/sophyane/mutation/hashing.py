"""Canonical hashes for analyzed source trees and changed semantic paths."""

from __future__ import annotations

import hashlib
from typing import Iterable, Mapping

from .adapters import AnalysisResult


def _update_fields(digest, *fields: str) -> None:
    for field in fields:
        encoded = field.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)


def semantic_tree_hash(results: Iterable[AnalysisResult]) -> str:
    entries = list(results)
    if any(not item.ok or item.semantic_digest is None for item in entries):
        raise ValueError("cannot hash failed analysis")
    digest = hashlib.sha256()
    for item in sorted(entries, key=lambda result: (result.path, result.language)):
        assert item.semantic_digest is not None
        _update_fields(digest, item.path, item.language, item.semantic_digest)
    return digest.hexdigest()


def semantic_diff_hash(baseline: Mapping[str, str], candidate: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(baseline.keys() | candidate.keys()):
        before = baseline.get(path)
        after = candidate.get(path)
        if before == after:
            continue
        if before is not None and after is not None:
            _update_fields(digest, path, "changed", before, after)
        elif before is None and after is not None:
            _update_fields(digest, path, "added", after)
        elif before is not None:
            _update_fields(digest, path, "removed", before)
    return digest.hexdigest()
