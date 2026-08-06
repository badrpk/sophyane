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
