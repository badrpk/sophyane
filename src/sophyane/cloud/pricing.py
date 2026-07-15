"""Ultra-low token pricing for Sophyane public API.

Philosophy: keep cloud inference nearly free so developers adopt Sophyane;
encourage users to contribute their own hardware (mesh / continual train)
for the heavy additional compute — those cycles are free on their devices.
"""

from __future__ import annotations

from typing import Any

# Prices in USD — intentionally far below typical frontier API rates.
PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "name": "Free Explorer",
        "price_usd_month": 0.0,
        "included_tokens": 500_000,
        "overage_per_1m": 0.05,  # $0.05 / 1M tokens
        "rpm": 30,
        "description": "Start free. Perfect for demos and personal agents.",
    },
    "builder": {
        "name": "Builder",
        "price_usd_month": 1.0,  # $1 / month
        "included_tokens": 10_000_000,
        "overage_per_1m": 0.03,
        "rpm": 120,
        "description": "Indie builders and startups — almost free at scale.",
    },
    "scale": {
        "name": "Scale",
        "price_usd_month": 9.0,
        "included_tokens": 200_000_000,
        "overage_per_1m": 0.015,
        "rpm": 600,
        "description": "Production agents. Still a fraction of OpenAI/Anthropic rates.",
    },
    "hybrid": {
        "name": "Hybrid Edge",
        "price_usd_month": 0.0,
        "included_tokens": 2_000_000,
        "overage_per_1m": 0.02,
        "rpm": 60,
        "description": (
            "Cloud tokens for orchestration; heavy inference runs on YOUR hardware "
            "via Sophyane mesh / local GGUF — free additional compute you already own."
        ),
        "edge_bonus": True,
    },
}

# Marketing comparison (illustrative)
COMPETITOR_HINT = {
    "typical_frontier_per_1m_input": 0.50,  # rough ballpark marketing figure
    "sophyane_builder_per_1m": 0.03,
    "savings_note": "Often 10–30× cheaper than frontier APIs for agent workloads.",
}


def list_plans() -> list[dict[str, Any]]:
    return [{"id": k, **v} for k, v in PLANS.items()]


def estimate_cost(tokens: int, plan_id: str = "builder") -> dict[str, Any]:
    plan = PLANS.get(plan_id) or PLANS["builder"]
    included = int(plan["included_tokens"])
    over = max(0, tokens - included)
    overage = (over / 1_000_000.0) * float(plan["overage_per_1m"])
    return {
        "plan": plan_id,
        "tokens": tokens,
        "included": included,
        "overage_tokens": over,
        "estimated_usd": round(float(plan["price_usd_month"]) + overage, 6),
        "overage_per_1m": plan["overage_per_1m"],
    }
