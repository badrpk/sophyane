"""Token + cost accounting."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

ACC_PATH = Path.home() / ".local/state/sophyane/token_accounting.jsonl"

# USD per 1M tokens (approximate defaults; override via record)
DEFAULT_RATES = {
    "gemini-default": {"in": 0.10, "out": 0.40},
    "openai-default": {"in": 0.50, "out": 1.50},
    "local": {"in": 0.0, "out": 0.0},
}

@dataclass
class UsageRecord:
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    ts: float = field(default_factory=time.time)
    run_id: str = ""

def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    key = "local" if provider in {"local", "local_gguf", "gguf"} else (
        "gemini-default" if "gemini" in (provider + model).lower() else "openai-default"
    )
    rates = DEFAULT_RATES[key]
    return (prompt_tokens * rates["in"] + completion_tokens * rates["out"]) / 1_000_000.0

def record_usage(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    run_id: str = "",
) -> UsageRecord:
    cost = estimate_cost(provider, model, prompt_tokens, completion_tokens)
    rec = UsageRecord(provider, model, prompt_tokens, completion_tokens, cost, run_id=run_id)
    ACC_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACC_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(rec)) + "\n")
    return rec

def summarize(limit: int = 1000) -> dict[str, float | int]:
    if not ACC_PATH.is_file():
        return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    calls = prompt = completion = 0
    cost = 0.0
    lines = ACC_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    for ln in lines:
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        calls += 1
        prompt += int(r.get("prompt_tokens", 0))
        completion += int(r.get("completion_tokens", 0))
        cost += float(r.get("cost_usd", 0))
    return {"calls": calls, "prompt_tokens": prompt, "completion_tokens": completion, "cost_usd": round(cost, 6)}
