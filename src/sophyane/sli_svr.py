"""Evidence-trained self-verification controller for Sophyane SLI.

This module adds an online learned verdict-confidence layer around SLI.

It intentionally does NOT modify language-model weights and is therefore not
the exact GRPO training algorithm from the SVR paper.

Instead it implements the deployment-side principle:

    candidate
      -> self/evidence features
      -> correctness probability
      -> CORRECT / INCORRECT verdict
      -> retain / refine / escalate
      -> objective outcome when available
      -> online calibration update

The policy learns only from grounded outcomes supplied by validators,
execution, tests, or equivalent objective evidence.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()


def _sigmoid(value: float) -> float:
    value = max(-30.0, min(30.0, float(value)))
    return 1.0 / (1.0 + math.exp(-value))


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


@dataclass(frozen=True)
class SVRFeatures:
    defect_ratio: float
    defect_streak: float
    repeated: float
    repair_turn: float
    latency: float
    local_provider: float
    recurrent_risk: float

    def vector(self) -> list[float]:
        return [
            1.0,
            self.defect_ratio,
            self.defect_streak,
            self.repeated,
            self.repair_turn,
            self.latency,
            self.local_provider,
            self.recurrent_risk,
        ]


@dataclass(frozen=True)
class SVRVerdict:
    verdict: str
    confidence: float
    p_correct: float
    action: str
    reason: str
    learned: bool
    samples: int
    threshold: float
    features: dict[str, float]


class EvidenceTrainedSVR:
    """Small online logistic policy trained from objective correctness."""

    def __init__(
        self,
        state_path: str | Path | None = None,
    ) -> None:
        root = Path(
            os.environ.get(
                "SOPHYANE_HOME",
                Path.home() / ".local/share/sophyane",
            )
        ).expanduser()

        self.state_path = Path(
            state_path or root / "sli-svr-state.json"
        ).expanduser()

        self.events_path = self.state_path.with_name(
            "sli-svr-events.jsonl"
        )

        # Initial priors:
        # defects/streak/repetition/risk reduce correctness probability.
        self.weights = [
            1.20,   # bias
            -2.20,  # defect ratio
            -1.20,  # defect streak
            -1.40,  # repeated response
            -0.25,  # already repairing
            -0.15,  # latency
            -0.10,  # local provider
            -1.75,  # recurrent risk
        ]

        self.samples = 0
        self.positive = 0
        self.negative = 0

        self.learning_rate = 0.08
        self.l2 = 0.001

        self.accept_threshold = float(
            os.environ.get(
                "SOPHYANE_SVR_ACCEPT_THRESHOLD",
                "0.78",
            )
        )

        self.escalate_threshold = float(
            os.environ.get(
                "SOPHYANE_SVR_ESCALATE_THRESHOLD",
                "0.28",
            )
        )

        self.min_learned_samples = int(
            os.environ.get(
                "SOPHYANE_SVR_MIN_SAMPLES",
                "8",
            )
        )

        self.last_features: SVRFeatures | None = None
        self.last_probability = 0.5
        self.last_action = ""
        self.last_verdict = ""

        self._load()

    def predict(
        self,
        features: SVRFeatures,
    ) -> float:
        vector = features.vector()

        score = sum(
            weight * feature
            for weight, feature in zip(
                self.weights,
                vector,
            )
        )

        return _clip(
            _sigmoid(score),
            0.001,
            0.999,
        )

    def decide(
        self,
        *,
        features: SVRFeatures,
        base_action: str,
        defects: list[str],
        local_provider: bool,
    ) -> SVRVerdict:
        with _LOCK:
            probability = self.predict(features)

            learned = (
                self.samples >= self.min_learned_samples
            )

            # During warm-up preserve the mature SLI policy while collecting
            # evidence. Confidence still starts becoming calibrated.
            if not learned:
                if base_action == "accept":
                    action = "accept"
                    verdict = "CORRECT"
                else:
                    action = base_action
                    verdict = "INCORRECT"

                confidence = (
                    probability
                    if verdict == "CORRECT"
                    else 1.0 - probability
                )

                reason = (
                    "SVR warm-up: preserving existing SLI action while "
                    "collecting objective calibration evidence"
                )

            else:
                if (
                    not defects
                    and probability >= self.accept_threshold
                ):
                    verdict = "CORRECT"
                    action = "accept"
                    reason = (
                        "learned correctness probability exceeds "
                        "adaptive retention threshold"
                    )

                else:
                    verdict = "INCORRECT"

                    if (
                        local_provider
                        and probability
                        <= self.escalate_threshold
                    ):
                        action = "escalate_cloud"
                        reason = (
                            "learned correctness probability is below "
                            "escalation threshold"
                        )
                    else:
                        action = "targeted_repair"
                        reason = (
                            "confidence is insufficient for retention; "
                            "allocate another bounded refinement turn"
                        )

                confidence = (
                    probability
                    if verdict == "CORRECT"
                    else 1.0 - probability
                )

            self.last_features = features
            self.last_probability = probability
            self.last_action = action
            self.last_verdict = verdict

            result = SVRVerdict(
                verdict=verdict,
                confidence=round(
                    _clip(confidence, 0.0, 1.0),
                    4,
                ),
                p_correct=round(probability, 4),
                action=action,
                reason=reason,
                learned=learned,
                samples=self.samples,
                threshold=self.accept_threshold,
                features=asdict(features),
            )

            self._event(
                "decision",
                asdict(result),
            )

            return result

    def learn(
        self,
        *,
        correct: bool,
        source: str = "validator",
        reward: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One online policy/calibration update from objective evidence."""

        with _LOCK:
            if self.last_features is None:
                return {
                    "updated": False,
                    "reason": "no pending SVR decision",
                }

            vector = self.last_features.vector()
            prediction_before = self.predict(
                self.last_features
            )

            target = 1.0 if correct else 0.0

            # Optional reward influences step magnitude but never reverses
            # grounded correctness.
            if reward is None:
                reward_scale = 1.0
            else:
                reward_scale = 0.5 + 0.5 * abs(
                    _clip(reward, -1.0, 1.0)
                )

            error = target - prediction_before

            for index in range(len(self.weights)):
                gradient = (
                    error * vector[index]
                    - self.l2 * self.weights[index]
                )

                self.weights[index] += (
                    self.learning_rate
                    * reward_scale
                    * gradient
                )

                self.weights[index] = _clip(
                    self.weights[index],
                    -8.0,
                    8.0,
                )

            self.samples += 1

            if correct:
                self.positive += 1
            else:
                self.negative += 1

            prediction_after = self.predict(
                self.last_features
            )

            payload = {
                "updated": True,
                "source": str(source),
                "correct": bool(correct),
                "reward": reward,
                "samples": self.samples,
                "prediction_before": round(
                    prediction_before,
                    5,
                ),
                "prediction_after": round(
                    prediction_after,
                    5,
                ),
                "error": round(error, 5),
                "action": self.last_action,
                "verdict": self.last_verdict,
                "weights": [
                    round(item, 6)
                    for item in self.weights
                ],
                "metadata": metadata or {},
            }

            self._save()
            self._event(
                "objective_update",
                payload,
            )

            try:
                from sophyane.durable_memory import (
                    remember_event,
                )

                remember_event(
                    "svr.objective_update",
                    payload,
                    namespace="svr",
                )

            except Exception:
                pass

            return payload

    def stats(self) -> dict[str, Any]:
        with _LOCK:
            total = max(1, self.samples)

            return {
                "samples": self.samples,
                "positive": self.positive,
                "negative": self.negative,
                "observed_accuracy": round(
                    self.positive / total,
                    4,
                ),
                "learned_policy_active": (
                    self.samples
                    >= self.min_learned_samples
                ),
                "minimum_samples": self.min_learned_samples,
                "accept_threshold": self.accept_threshold,
                "escalate_threshold": self.escalate_threshold,
                "last_probability": round(
                    self.last_probability,
                    4,
                ),
                "last_action": self.last_action,
                "last_verdict": self.last_verdict,
                "weights": [
                    round(item, 6)
                    for item in self.weights
                ],
                "state_path": str(self.state_path),
            }

    def _load(self) -> None:
        try:
            data = json.loads(
                self.state_path.read_text(
                    encoding="utf-8"
                )
            )

            weights = data.get("weights")

            if (
                isinstance(weights, list)
                and len(weights) == len(self.weights)
            ):
                self.weights = [
                    float(item)
                    for item in weights
                ]

            self.samples = int(
                data.get("samples", 0)
            )
            self.positive = int(
                data.get("positive", 0)
            )
            self.negative = int(
                data.get("negative", 0)
            )

        except Exception:
            pass

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            payload = {
                "schema": 1,
                "updated_at": time.time(),
                "weights": self.weights,
                "samples": self.samples,
                "positive": self.positive,
                "negative": self.negative,
                "accept_threshold": self.accept_threshold,
                "escalate_threshold": self.escalate_threshold,
                "minimum_samples": self.min_learned_samples,
            }

            self.state_path.write_text(
                json.dumps(
                    payload,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        except Exception:
            pass

    def _event(
        self,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            self.events_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            record = {
                "ts": time.time(),
                "event": event,
                **payload,
            }

            with self.events_path.open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        except Exception:
            pass


_SVR: EvidenceTrainedSVR | None = None


def get_svr_controller() -> EvidenceTrainedSVR:
    global _SVR

    with _LOCK:
        if _SVR is None:
            _SVR = EvidenceTrainedSVR()

        return _SVR


def record_objective_outcome(
    correct: bool,
    *,
    source: str = "validator",
    reward: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return get_svr_controller().learn(
        correct=correct,
        source=source,
        reward=reward,
        metadata=metadata,
    )


def svr_stats() -> dict[str, Any]:
    return get_svr_controller().stats()
