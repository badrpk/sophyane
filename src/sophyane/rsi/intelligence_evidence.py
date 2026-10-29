"""Durable, conservative evidence for selecting intelligence providers."""

from __future__ import annotations

import json
import math
from pathlib import Path


class ProviderEvidenceStore:
    def __init__(self, path: Path, *, minimum_samples: int = 5):
        self.path = Path(path)
        self.minimum_samples = max(1, int(minimum_samples))

    def _load(self) -> dict[str, dict[str, int]] | None:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            providers = payload["providers"]
            if payload.get("version") != 1 or not isinstance(providers, dict):
                raise ValueError("unsupported evidence state")
            result = {}
            for name, entry in providers.items():
                attempts = int(entry["attempts"])
                successes = int(entry["successes"])
                if attempts < 0 or successes < 0 or successes > attempts:
                    raise ValueError("invalid provider evidence")
                result[str(name)] = {"attempts": attempts, "successes": successes}
            return result
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return None

    def _save(self, providers: dict[str, dict[str, int]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 1, "providers": providers}, sort_keys=True) + "\n", encoding="utf-8")

    def record(self, provider: str, success: bool) -> None:
        providers = self._load()
        if providers is None:
            raise ValueError("provider evidence state is unreadable")
        entry = providers.setdefault(str(provider), {"attempts": 0, "successes": 0})
        entry["attempts"] += 1
        if success:
            entry["successes"] += 1
        self._save(providers)

    def _score(self, entry: dict[str, int]) -> float:
        attempts = entry["attempts"]
        if attempts < self.minimum_samples:
            return -1.0
        successes = entry["successes"]
        z = 1.96
        proportion = successes / attempts
        denominator = 1 + z * z / attempts
        center = proportion + z * z / (2 * attempts)
        spread = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * attempts)) / attempts)
        return (center - spread) / denominator

    def rank(self, providers: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        ordered = tuple(str(provider) for provider in providers)
        evidence = self._load()
        if evidence is None:
            return ordered
        scored = [(provider, self._score(evidence.get(provider, {"attempts": 0, "successes": 0}))) for provider in ordered]
        if all(score < 0 for _, score in scored):
            return ordered
        return tuple(provider for provider, _ in sorted(scored, key=lambda item: (-item[1], item[0])))
