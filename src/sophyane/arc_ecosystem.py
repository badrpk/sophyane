"""Bounded BADRPK ecosystem adapters for ARC-AGI-3.

NIFDU contributes its evidence-manifest contract, Neuron contributes temporal
change comparison, and Xerus contributes disk-first recall.  None may select or
execute an ARC action; that authority remains with the configured provider and
the ARC allowed-action validator.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_XERUS_LOCK = threading.RLock()


@dataclass(frozen=True)
class FrameEvidence:
    game_id: str
    step: int
    width: int
    height: int
    frame_sha256: str
    observation_sha256: str
    previous_frame_sha256: str
    change_distance: float
    changed: bool
    color_objects: tuple[dict[str, int], ...]
    source: str = "nifdu-evidence/neuron-change"


def _load(name: str, path: Path) -> Any | None:
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class BadrpkArcEcosystem:
    def __init__(self, state_root: Path, *, nifdu_repo: Path | None = None, neuron_repo: Path | None = None, xerus_repo: Path | None = None) -> None:
        home = Path.home()
        self.state_root = Path(state_root)
        self.nifdu_repo = Path(os.getenv("SOPHYANE_NIFDU_REPO_PATH", nifdu_repo or home / "nifdu"))
        self.neuron_repo = Path(os.getenv("SOPHYANE_NEURON_REPO_PATH", neuron_repo or home / "neuron_repo"))
        self.xerus_repo = Path(os.getenv("SOPHYANE_XERUS_REPO_PATH", xerus_repo or home / "xerus"))
        self._neuron = _load("sophyane_badrpk_neuron_screen_change", self.neuron_repo / "embodiment/perception/screen_change.py")
        self._xerus = _load("sophyane_badrpk_xerus_memory", self.xerus_repo / "src/xerus/memory.py")
        self._previous: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        nifdu_contract = self.nifdu_repo / "include/nifdu/evidence_manifest.hpp"
        return {
            "nifdu": {"available": nifdu_contract.is_file(), "role": "frame evidence manifest", "path": str(nifdu_contract)},
            "neuron": {"available": self._neuron is not None, "role": "temporal frame change", "path": str(self.neuron_repo)},
            "xerus": {"available": self._xerus is not None, "role": "disk-first transition recall", "path": str(self.xerus_repo)},
        }

    @staticmethod
    def _frame(observation: Any) -> list[list[int]]:
        raw = getattr(observation, "frame", None) or []
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        elif isinstance(raw, (list, tuple)):
            raw = [item.tolist() if hasattr(item, "tolist") else item for item in raw]
        # ARC frames are layers; use the last rendered layer for perception.
        if raw and isinstance(raw[0], (list, tuple)) and raw[0] and isinstance(raw[0][0], (list, tuple)):
            raw = raw[-1]
        return [[int(value) & 255 for value in row] for row in raw if isinstance(row, (list, tuple))]

    def evidence(self, game_id: str, step: int, observation: Any, observation_payload: dict[str, Any]) -> FrameEvidence:
        frame = self._frame(observation)
        height = len(frame)
        width = max((len(row) for row in frame), default=0)
        canonical_frame = json.dumps(frame, separators=(",", ":"), ensure_ascii=True).encode()
        frame_digest = hashlib.sha256(canonical_frame).hexdigest()
        observation_digest = hashlib.sha256(json.dumps(observation_payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        samples = tuple(value for row in frame for value in row)
        color_objects = []
        for color in sorted(set(samples)):
            points = [(x, y) for y, row in enumerate(frame) for x, value in enumerate(row) if value == color]
            if points:
                color_objects.append({
                    "color": color, "count": len(points),
                    "x_min": min(x for x, _ in points), "x_max": max(x for x, _ in points),
                    "y_min": min(y for _, y in points), "y_max": max(y for _, y in points),
                })
        previous = self._previous.get(game_id)
        if self._neuron is not None:
            current = self._neuron.ScreenFingerprint(width=width, height=height, digest=frame_digest, samples=samples)
            change = self._neuron.compare(previous, current, threshold=0.0)
            distance, changed = float(change.distance), bool(change.changed)
            self._previous[game_id] = current
        else:
            previous_digest = getattr(previous, "digest", "") if previous is not None else ""
            distance, changed = (1.0, True) if previous_digest != frame_digest else (0.0, False)
            self._previous[game_id] = type("Fingerprint", (), {"digest": frame_digest})()
        return FrameEvidence(game_id, step, width, height, frame_digest, observation_digest, getattr(previous, "digest", "") if previous else "", round(distance, 6), changed, tuple(color_objects))

    def _namespace(self, provider: str, game_id: str) -> str:
        clean = re_safe(provider) + "/" + re_safe(game_id)
        return "arc-agi-3/" + clean

    def recall(self, provider: str, game_id: str, evidence: FrameEvidence, limit: int = 4) -> list[dict[str, Any]]:
        if self._xerus is None:
            return []
        return self._xerus_call("recall", evidence.frame_sha256, namespace=self._namespace(provider, game_id), limit=limit) or []

    def remember(self, provider: str, game_id: str, before: FrameEvidence, action: str, data: dict[str, int], after: FrameEvidence, state: str) -> dict[str, Any]:
        if self._xerus is None:
            return {"ok": False, "reason": "xerus unavailable"}
        identity = json.dumps([game_id, before.frame_sha256, action, data, after.frame_sha256], sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256(identity.encode()).hexdigest()[:32]
        content = f"frame {before.frame_sha256[:12]} action {action} data {json.dumps(data, sort_keys=True)} -> frame {after.frame_sha256[:12]} state {state} distance {after.change_distance}"
        return self._xerus_call("remember", content, namespace=self._namespace(provider, game_id), memory_key=key, metadata={"before": before.frame_sha256, "after": after.frame_sha256, "action": action, "state": state}) or {"ok": False}

    def _xerus_call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        with _XERUS_LOCK:
            prior = os.environ.get("XERUS_HOME")
            os.environ["XERUS_HOME"] = str(self.state_root / "xerus")
            try:
                return getattr(self._xerus, method)(*args, **kwargs)
            finally:
                if prior is None:
                    os.environ.pop("XERUS_HOME", None)
                else:
                    os.environ["XERUS_HOME"] = prior


def re_safe(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(value))


def evidence_dict(value: FrameEvidence) -> dict[str, Any]:
    return asdict(value)
