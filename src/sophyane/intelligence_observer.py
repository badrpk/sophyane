"""Sanitized observation of Sophyane intelligence attempts.

This module records operational observations only.

An observation is NOT verified execution evidence, mutation authority,
or permission to promote an RSI candidate.  Prompt and response bodies
are deliberately excluded from durable records.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


_MAX_DIAGNOSTIC = 1000
_DEFAULT_LIMIT = 20
STATE_DIR = Path.home() / ".local/state/sophyane/intelligence"


class IntelligenceObserver:
    """Append-only, JSONL intelligence-attempt observer."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "intelligence-attempts.jsonl"

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _diagnostic(value: Any) -> str:
        return str(value or "").strip()[:_MAX_DIAGNOSTIC]

    def record_attempt(
        self,
        *,
        provider: str,
        transport: str,
        model: str = "",
        operation: str = "",
        outcome: str,
        latency_seconds: float | None = None,
        failure_category: str = "",
        diagnostic: str = "",
        **_sensitive_or_future_fields: Any,
    ) -> dict[str, Any]:
        """Record sanitized metadata for one intelligence attempt.

        Extra fields are intentionally ignored.  In particular this prevents
        callers from accidentally persisting prompt/response bodies.
        """

        now = time.time()

        row: dict[str, Any] = {
            "event_key": uuid.uuid4().hex,
            "created_at": now,
            "provider": self._text(provider),
            "transport": self._text(transport),
            "model": self._text(model),
            "operation": self._text(operation),
            "outcome": self._text(outcome),
        }

        if latency_seconds is not None:
            row["latency_seconds"] = max(
                0.0,
                float(latency_seconds),
            )

        failure = self._text(failure_category)
        if failure:
            row["failure_category"] = failure

        bounded_diagnostic = self._diagnostic(diagnostic)
        if bounded_diagnostic:
            row["diagnostic"] = bounded_diagnostic

        # Deliberately absent:
        #   accepted=True
        #   verification_state="verified"
        #   verification_evidence
        #
        # Operational observation must never manufacture verification.

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

        return dict(row)

    def read_recent(
        self,
        *,
        limit: int = _DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """Return at most the newest ``limit`` valid observations."""

        count = max(0, int(limit))

        if count == 0 or not self.path.exists():
            return []

        rows: list[dict[str, Any]] = []

        for line in self.path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():
            try:
                value = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

            if isinstance(value, dict):
                rows.append(value)

        return rows[-count:]


def default_intelligence_observer() -> IntelligenceObserver | None:
    """Return the durable sanitized observer, failing open on storage errors."""
    try:
        return IntelligenceObserver(STATE_DIR)
    except Exception:
        return None
