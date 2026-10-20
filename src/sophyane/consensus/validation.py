"""Strict, deterministic validation for worker consensus responses."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .models import InvalidVote, ValidatedVote

_FIELDS = frozenset({"worker_id", "decision", "ast", "git_head"})
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class _DuplicateKey(ValueError):
    pass


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate key: {key}")
        result[key] = value
    return result


def canonical_decision(value: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("decision must be an object")
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _invalid(boundary: str, error: Exception | str, *, worker_id: str | None = None, git_head: str | None = None) -> InvalidVote:
    return InvalidVote(worker_id, None, None, git_head, boundary, str(error))


def validate_worker_response(raw: object, *, base_commit: str) -> ValidatedVote | InvalidVote:
    worker_id: str | None = None
    git_head: str | None = None
    try:
        if isinstance(raw, (str, bytes, bytearray)):
            payload = json.loads(raw, object_pairs_hook=_reject_duplicates)
        elif isinstance(raw, Mapping):
            payload = dict(raw)
        else:
            return _invalid("json_schema", "response must be JSON text or an object")
    except (json.JSONDecodeError, UnicodeDecodeError, _DuplicateKey, TypeError, ValueError) as exc:
        return _invalid("json_schema", exc)

    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        return _invalid("json_schema", "payload fields must be exactly worker_id, decision, ast, git_head")
    worker_id = payload["worker_id"] if isinstance(payload["worker_id"], str) else None
    git_head = payload["git_head"] if isinstance(payload["git_head"], str) else None
    if not worker_id:
        return _invalid("json_schema", "worker_id must be non-empty text", worker_id=worker_id, git_head=git_head)
    try:
        decision = payload["decision"]
        _, digest = canonical_decision(decision)
    except (TypeError, ValueError) as exc:
        return _invalid("json_schema", exc, worker_id=worker_id, git_head=git_head)

    ast_source = payload["ast"]
    if not isinstance(ast_source, str):
        return _invalid("ast_contract", "ast must be source text", worker_id=worker_id, git_head=git_head)
    try:
        tree = ast.parse(ast_source, mode="exec")
    except (SyntaxError, ValueError, TypeError) as exc:
        return _invalid("ast_contract", exc, worker_id=worker_id, git_head=git_head)
    if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "score" for node in tree.body):
        return _invalid("ast_contract", "AST must define score", worker_id=worker_id, git_head=git_head)

    if not isinstance(base_commit, str) or not _COMMIT_RE.fullmatch(base_commit):
        return _invalid("git_head", "base_commit is not a full Git hash", worker_id=worker_id, git_head=git_head)
    if not isinstance(git_head, str) or not _COMMIT_RE.fullmatch(git_head) or git_head.lower() != base_commit.lower():
        return _invalid("git_head", "worker Git head diverges from round base", worker_id=worker_id, git_head=git_head)
    return ValidatedVote(worker_id, dict(decision), digest, git_head, None)

