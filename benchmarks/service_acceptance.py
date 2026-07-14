#!/usr/bin/env python3
"""Service-backed checks for persistence packages used alongside LangGraph."""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import redis
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.redis import RedisSaver


def main() -> int:
    postgres_uri = os.environ.get("POSTGRES_URI", "postgresql://postgres:postgres@127.0.0.1:5432/postgres")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

    with psycopg.connect(postgres_uri) as connection:
        value = connection.execute("SELECT 42").fetchone()[0]
    redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    redis_client.set("sophyane:integration:test", "42", ex=60)
    redis_value = redis_client.get("sophyane:integration:test")

    results = {
        "postgres": {
            "connected": value == 42,
            "checkpointer_class": PostgresSaver.__name__,
        },
        "redis": {
            "connected": redis_value == "42",
            "checkpointer_class": RedisSaver.__name__,
        },
    }
    results["passed"] = results["postgres"]["connected"] and results["redis"]["connected"]
    output = Path("benchmark-results/integrations")
    output.mkdir(parents=True, exist_ok=True)
    (output / "services.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
