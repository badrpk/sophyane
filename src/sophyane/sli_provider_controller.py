"""Recursive SLI controller for adaptive provider switching.

The controller uses a tiny dependency-free LSTM-style recurrent cell to retain
sequence context across generation/repair attempts. It is deliberately a
controller, not a code generator: transformer/GGUF/cloud providers still create
artifacts while SLI decides whether to continue locally, request repair, or
escalate to a configured rescue provider.
"""
from __future__ import annotations

import hashlib
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
    value = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def artifact_defects(prompt: str, text: str) -> list[str]:
    """Return objective artifact defects visible in a provider response."""
    request = str(prompt or "").lower()
    output = str(text or "")
    low = output.lower()
    defects: list[str] = []
    browser_request = any(word in request for word in ("html", "website", "web app", "game", "browser"))
    game_request = "game" in request or any(word in request for word in ("chess", "snake", "tic tac", "tetris"))
    complete_html = ("<html" in low or "<!doctype html" in low) and "</html>" in low
    interactive = any(token in low for token in ("onclick", "addeventlistener", "ontouch", "pointerdown", "keydown"))
    if browser_request or "<html" in low or "<!doctype html" in low:
        if "<html" not in low and "<!doctype html" not in low:
            defects.append("missing_html_document")
        if "</html>" not in low:
            defects.append("missing_html_close")
        if game_request and "<script" not in low:
            defects.append("missing_javascript")
        if game_request and not interactive:
            defects.append("missing_interaction")
    # Compact but structurally complete artifacts are valid. Length is only a
    # defect when the response also lacks a complete runnable artifact.
    if (
        len(output.strip()) < 160
        and any(word in request for word in ("create", "build", "make", "implement"))
        and not (complete_html and (not game_request or ("<script" in low and interactive)))
    ):
        defects.append("response_too_short")
    return defects


@dataclass
class SLIDecision:
    action: str
    risk: float
    confidence: float
    reason: str
    defects: list[str]
    attempt: int
    hidden: float
    cell: float


class SLIProviderController:
    """Online recurrent controller for provider and repair sequencing."""

    def __init__(self, state_path: str | Path | None = None) -> None:
        default = Path(os.environ.get("SOPHYANE_HOME", Path.home() / ".local/share/sophyane")) / "sli-provider-state.json"
        self.state_path = Path(state_path or default).expanduser()
        self.hidden = 0.0
        self.cell = 0.0
        self.attempt = 0
        self.defect_streak = 0
        self.last_digest = ""
        self.last_action = "continue_local"
        self._load()

    def reset_sequence(self) -> None:
        with _LOCK:
            self.hidden = 0.0
            self.cell = 0.0
            self.attempt = 0
            self.defect_streak = 0
            self.last_digest = ""
            self.last_action = "continue_local"
            self._save()

    def observe(self, *, prompt: str, response: str, latency_seconds: float = 0.0, provider: str = "") -> SLIDecision:
        defects = artifact_defects(prompt, response)
        digest = hashlib.sha256(str(response or "").encode("utf-8", errors="ignore")).hexdigest()
        repeated = bool(self.last_digest and digest == self.last_digest)
        repair_prompt = any(marker in str(prompt or "").lower() for marker in (
            "repair", "continue", "previous", "missing", "incomplete", "validator", "corrected", "truncated"
        ))
        with _LOCK:
            self.attempt += 1
            self.defect_streak = self.defect_streak + 1 if defects else 0
            x_defect = min(1.0, len(defects) / 3.0)
            x_streak = min(1.0, self.defect_streak / 3.0)
            x_repeat = 1.0 if repeated else 0.0
            x_repair = 1.0 if repair_prompt else 0.0
            x_latency = min(1.0, max(0.0, latency_seconds) / 45.0)
            local = str(provider or "").lower() in {"local_gguf", "ollama"}
            x_local = 1.0 if local else 0.0

            forget = _sigmoid(1.6 - 0.7 * x_defect - 0.5 * x_repeat)
            input_gate = _sigmoid(-0.4 + 1.8 * x_defect + 1.2 * x_streak + 0.8 * x_repair)
            candidate = math.tanh(-0.8 + 1.7 * x_defect + 1.5 * x_streak + 1.4 * x_repeat + 0.5 * x_latency + 0.4 * x_local)
            self.cell = forget * self.cell + input_gate * candidate
            output_gate = _sigmoid(-0.2 + 1.2 * x_defect + 0.8 * x_streak + 0.6 * x_repair)
            self.hidden = output_gate * math.tanh(self.cell)
            risk = max(0.0, min(1.0, 0.5 + 0.5 * self.hidden))

            severe = any(item in defects for item in ("missing_html_close", "missing_javascript", "missing_interaction"))
            if local and defects and (severe or self.defect_streak >= 2 or repeated or risk >= 0.68):
                action = "escalate_cloud"
                reason = "SLI sequence predicts low local completion probability"
            elif defects:
                action = "targeted_repair"
                reason = "artifact is incomplete but one bounded repair remains worthwhile"
            else:
                action = "accept"
                reason = "artifact passed SLI structural checks"

            confidence = max(0.5, min(0.99, 0.55 + abs(risk - 0.5)))
            self.last_digest = digest
            self.last_action = action
            decision = SLIDecision(action, round(risk, 4), round(confidence, 4), reason, defects, self.attempt, round(self.hidden, 6), round(self.cell, 6))
            self._append_event(provider, latency_seconds, decision)
            self._save()
            return decision

    def _load(self) -> None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.hidden = float(data.get("hidden", 0.0))
            self.cell = float(data.get("cell", 0.0))
            self.attempt = int(data.get("attempt", 0))
            self.defect_streak = int(data.get("defect_streak", 0))
            self.last_digest = str(data.get("last_digest", ""))
            self.last_action = str(data.get("last_action", "continue_local"))
        except Exception:
            return

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "schema": 1,
                "updated_at": time.time(),
                "hidden": self.hidden,
                "cell": self.cell,
                "attempt": self.attempt,
                "defect_streak": self.defect_streak,
                "last_digest": self.last_digest,
                "last_action": self.last_action,
            }
            self.state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _append_event(self, provider: str, latency: float, decision: SLIDecision) -> None:
        try:
            path = self.state_path.with_name("sli-provider-events.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            event: dict[str, Any] = {
                "ts": time.time(),
                "provider": provider,
                "latency_seconds": round(float(latency), 3),
                **asdict(decision),
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass


_CONTROLLER: SLIProviderController | None = None


def get_sli_provider_controller() -> SLIProviderController:
    global _CONTROLLER
    with _LOCK:
        if _CONTROLLER is None:
            _CONTROLLER = SLIProviderController()
        return _CONTROLLER
