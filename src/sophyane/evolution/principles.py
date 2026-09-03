"""Persistent, reusable knowledge learned from harness executions.

This store intentionally separates:

- successful execution principles;
- recurring failure principles;
- task-specific evidence;
- patch eligibility.

A single failure may be recorded, but it cannot authorize a code patch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any


def _normalise(value: str) -> str:
    return " ".join(
        str(value or "")
        .casefold()
        .split()
    )


def principle_id(
    component: str,
    principle: str,
) -> str:
    material = (
        _normalise(component)
        + "\n"
        + _normalise(principle)
    )

    return hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:20]


class PrincipleStore:
    """Store general lessons without promoting raw execution traces."""

    def __init__(
        self,
        repo: Path,
    ) -> None:
        self.root = (
            Path(repo)
            / ".sophyane-evolution"
        )
        self.path = (
            self.root
            / "principles.json"
        )

        # Always create an observable principle store, even before the
        # first valid hindsight principle has been learned.
        if not self.path.is_file():
            self._save(
                {
                    "version": 1,
                    "principles": {},
                    "success_patterns": {},
                }
            )

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "version": 1,
                "principles": {},
                "success_patterns": {},
            }

        try:
            data = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            data = {}

        data.setdefault("version", 1)
        data.setdefault("principles", {})
        data.setdefault(
            "success_patterns",
            {},
        )

        return data

    def _save(
        self,
        data: dict[str, Any],
    ) -> None:
        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.path.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        try:
            os.chmod(
                self.path,
                0o600,
            )
        except OSError:
            pass

    @staticmethod
    def _safe_principle(
        value: str,
    ) -> str:
        """Reject obvious task-specific or unsafe lessons."""
        principle = " ".join(
            str(value or "").split()
        ).strip()

        if len(principle) < 20:
            return ""

        if len(principle) > 800:
            principle = principle[:800]

        forbidden = (
            "hardcode",
            "exact prompt",
            "always answer",
            "bypass validator",
            "disable security",
            "skip tests",
            "/etc/shadow",
            "api key",
            "password",
        )

        lowered = principle.casefold()

        if any(
            term in lowered
            for term in forbidden
        ):
            return ""

        # Reject principles containing suspiciously long literal tokens.
        if re.search(
            r"[A-Za-z0-9._~-]{40,}",
            principle,
        ):
            return ""

        return principle

    def record_failure_principle(
        self,
        *,
        component: str,
        capability: str,
        principle: str,
        task_id: str,
        confidence: float,
        evidence: list[str],
    ) -> dict[str, Any] | None:
        principle = self._safe_principle(
            principle
        )

        if not principle:
            return None

        component = (
            str(component or "")
            .strip()
            .casefold()
        )

        if not component:
            return None

        data = self._load()
        pid = principle_id(
            component,
            principle,
        )

        item = data["principles"].setdefault(
            pid,
            {
                "id": pid,
                "component": component,
                "capabilities": [],
                "principle": principle,
                "observations": 0,
                "distinct_tasks": [],
                "maximum_confidence": 0.0,
                "evidence_samples": [],
                "first_seen": time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "last_seen": "",
                "status": "candidate",
            },
        )

        if capability not in item[
            "capabilities"
        ]:
            item["capabilities"].append(
                capability
            )

        item["observations"] += 1

        if task_id not in item[
            "distinct_tasks"
        ]:
            item["distinct_tasks"].append(
                task_id
            )

        item["maximum_confidence"] = max(
            float(
                item.get(
                    "maximum_confidence",
                    0.0,
                )
            ),
            float(confidence),
        )

        for sample in evidence[:3]:
            cleaned = " ".join(
                str(sample or "").split()
            )[:500]

            if (
                cleaned
                and cleaned
                not in item[
                    "evidence_samples"
                ]
            ):
                item[
                    "evidence_samples"
                ].append(cleaned)

        item["evidence_samples"] = item[
            "evidence_samples"
        ][-8:]

        item["last_seen"] = time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # A reusable lesson must recur on at least two distinct tasks.
        if (
            len(item["distinct_tasks"]) >= 2
            and item[
                "maximum_confidence"
            ]
            >= 0.65
        ):
            item["status"] = "recurrent"

        self._save(data)

        return dict(item)

    def record_success(
        self,
        *,
        capability: str,
        task_id: str,
        checks: dict[str, bool],
    ) -> None:
        data = self._load()

        item = data[
            "success_patterns"
        ].setdefault(
            capability,
            {
                "passes": 0,
                "tasks": [],
                "stable_checks": {},
                "last_seen": "",
            },
        )

        item["passes"] += 1

        if task_id not in item["tasks"]:
            item["tasks"].append(task_id)

        item["tasks"] = item[
            "tasks"
        ][-100:]

        for name, passed in checks.items():
            if passed:
                item[
                    "stable_checks"
                ][name] = (
                    int(
                        item[
                            "stable_checks"
                        ].get(name, 0)
                    )
                    + 1
                )

        item["last_seen"] = time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        self._save(data)

    def record_verified_success_principle(
        self,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Synthesize deterministic scoped principles from trusted events.

        This is analysis-only.  Callers must already have applied the
        canonical verified-history admission gate.  A principle requires two
        distinct event identities in one compatible capability/repository
        scope; it never grants candidate or mutation authority.
        """
        groups: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for record in records or []:
            capability = str(record.get("capability_class") or "").strip().casefold()
            repository = str(record.get("repository_identity") or "").strip().casefold()
            identity = str(record.get("event_key") or record.get("trace_id") or "").strip()
            if not capability or not identity:
                continue
            groups.setdefault((capability, repository), {})[identity] = record

        data = self._load()
        synthesized: list[dict[str, Any]] = []
        for (capability, repository), events in sorted(groups.items()):
            if len(events) < 2:
                continue
            scope = repository or "repository-independent"
            principle = (
                f"Verified execution pattern for capability {capability} "
                f"within {scope}: deterministic verification succeeded "
                "across distinct objectives."
            )
            principle = self._safe_principle(principle)
            if not principle:
                continue
            pid = principle_id(capability, principle)
            item = data["principles"].setdefault(pid, {
                "id": pid, "component": capability, "capabilities": [capability],
                "principle": principle, "observations": 0, "distinct_tasks": [],
                "maximum_confidence": 0.80, "evidence_samples": [],
                "first_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_seen": "", "status": "candidate",
                "origin": "verified_execution",
                "repository_identity": repository or None,
                "supporting_event_keys": [],
            })
            item["origin"] = "verified_execution"
            item["repository_identity"] = repository or None
            item.setdefault("supporting_event_keys", [])
            for identity, event in sorted(events.items()):
                if identity in item["supporting_event_keys"]:
                    continue
                item["supporting_event_keys"].append(identity)
                objective = str(event.get("objective_hash") or identity).strip()
                if objective and objective not in item["distinct_tasks"]:
                    item["distinct_tasks"].append(objective)
                item["observations"] = int(item.get("observations", 0)) + 1
            item["supporting_event_keys"] = item["supporting_event_keys"][-100:]
            item["distinct_tasks"] = item["distinct_tasks"][-100:]
            item["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if len(item["distinct_tasks"]) >= 2 and float(item.get("maximum_confidence", 0.0)) >= 0.65:
                item["status"] = "recurrent"
            synthesized.append(dict(item))

        if synthesized:
            self._save(data)
        return synthesized

    def patch_eligible(
        self,
        *,
        component: str,
        principle: str,
    ) -> bool:
        principle = self._safe_principle(
            principle
        )

        if not principle:
            return False

        item = (
            self._load()
            .get("principles", {})
            .get(
                principle_id(
                    component,
                    principle,
                )
            )
        )

        if not isinstance(item, dict):
            return False

        return (
            item.get("status")
            == "recurrent"
            and len(
                item.get(
                    "distinct_tasks",
                    [],
                )
            )
            >= 2
            and float(
                item.get(
                    "maximum_confidence",
                    0.0,
                )
            )
            >= 0.65
        )

    @classmethod
    def read_recurrent_principles(
        cls,
        repo: Path,
        *,
        limit: int = 32,
    ) -> list[dict[str, Any]]:
        """Read recurrent principles without initializing or mutating a store."""
        path = Path(repo).expanduser().resolve() / ".sophyane-evolution" / "principles.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []
        rows = data.get("principles", {}) if isinstance(data, dict) else {}
        if not isinstance(rows, dict):
            return []
        result = [
            dict(item)
            for item in rows.values()
            if isinstance(item, dict) and item.get("status") == "recurrent"
        ]
        return result[: max(1, min(int(limit), 32))]

    def recurrent_principles(
        self,
        *,
        component: str = "",
    ) -> list[dict[str, Any]]:
        items = []

        for item in (
            self._load()
            .get("principles", {})
            .values()
        ):
            if (
                item.get("status")
                != "recurrent"
            ):
                continue

            if (
                component
                and item.get("component")
                != component
            ):
                continue

            items.append(dict(item))

        return sorted(
            items,
            key=lambda item: (
                len(
                    item.get(
                        "distinct_tasks",
                        [],
                    )
                ),
                float(
                    item.get(
                        "maximum_confidence",
                        0.0,
                    )
                ),
            ),
            reverse=True,
        )
