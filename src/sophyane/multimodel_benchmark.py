"""Bounded, redacted provider benchmarks with independent RSI evidence."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import math
import re
import threading
import time
from typing import Any, Callable

from sophyane.intelligence_authority import current_intelligence_authority
from sophyane.multimodel_registry import build_race_model_routes, verify_math_answer


ARITHMETIC_PROMPT = "Calculate 3 * 3 - 3. Reply with only the number."
_NUMERIC_OUTPUT = re.compile(r"^-?\d+(?:\.\d+)?$")
_TRAILING_NUMBER = re.compile(r"(?:^|[^\d])(-?\d+(?:\.\d+)?)\s*[.!?\s]*$")


def _safe_observed_output(output: str) -> str:
    value = str(output or "").strip()
    if _NUMERIC_OUTPUT.fullmatch(value):
        return value
    trailing = _TRAILING_NUMBER.search(value)
    if trailing:
        return f"numeric: {trailing.group(1)}"
    return f"non-numeric response ({len(value)} characters)"


def _capability_class(provider_id: str) -> str:
    return {
        "local_gguf": "local_gguf",
        "nifdu_browser": "external_browser",
        "codex_cli": "external_harness",
    }.get(provider_id, "external_api")


def _failure_class(error: BaseException) -> str:
    """Return a bounded, redaction-safe failure category for route evidence."""
    message = str(error).casefold()
    if isinstance(error, TimeoutError) or "timed out" in message or "timeout" in message:
        return "timeout"
    if any(value in message for value in ("credential", "authentication", "signed out", "login")):
        return "authentication"
    if any(value in message for value in ("captcha", "challenge", "not allowed", "restricted")):
        return "provider_restriction"
    if any(value in message for value in ("cdp", "browser bootstrap", "browser not ready", "no chatgpt chromium tab")):
        return "browser_readiness"
    if any(value in message for value in ("navigation", "navigate", "page load")):
        return "navigation"
    if any(value in message for value in ("selector", "prompt box", "composer", "textbox")):
        return "selector_readiness"
    if any(value in message for value in ("extract", "empty response", "no response", "response was")):
        return "response_extraction"
    if any(value in message for value in ("connection", "transport", "websocket", "connection refused")):
        return "transport"
    return "provider_error"


def _rsi_record(event: dict[str, Any]) -> Any:
    from sophyane.sli_learner import learn_execution

    return learn_execution(
        trace_id=str(event["trace_id"]),
        request=ARITHMETIC_PROMPT,
        workspace_before={},
        workspace_after={},
        status=str(event["status"]),
        reward=float(event["reward"]),
        result=str(event["result"]),
        elapsed_seconds=float(event["elapsed_seconds"]),
        error=str(event.get("error") or ""),
        provenance=event,
    )


def _rsi_event(outcome: dict[str, Any], *, elapsed_seconds: float) -> dict[str, Any]:
    completed = outcome["status"] == "completed"
    correct = bool(outcome.get("correct"))
    status = "succeeded" if correct else "failed"
    objective_hash = hashlib.sha256(ARITHMETIC_PROMPT.encode("utf-8")).hexdigest()
    identity = str(outcome["model_id"])
    result = "deterministic arithmetic benchmark passed" if correct else "deterministic arithmetic benchmark failed"
    trace_id = "model-benchmark-" + hashlib.sha256(
        f"{objective_hash}|{identity}|{status}|{outcome.get('actual_output')}".encode("utf-8")
    ).hexdigest()[:32]
    return {
        "trace_id": trace_id,
        "objective_hash": objective_hash,
        "original_objective": ARITHMETIC_PROMPT,
        "status": status,
        "verification_state": "verified" if completed else "unverified",
        "verification_evidence": [
            {
                "verifier": "fixed-arithmetic-evaluator",
                "ok": correct,
                "expected": "6",
                "observed": outcome.get("actual_output"),
            }
        ] if completed else [],
        "accepted": correct,
        "workspace": "",
        "changed_paths": [],
        "artifact_paths": [],
        "repository_identity": None,
        "provider_identity": identity,
        "capability_class": _capability_class(str(outcome["provider_id"])),
        "model_identity": identity,
        "benchmark_category": "mathematics",
        "result": result,
        "reward": 1.0 if correct else 0.0,
        "elapsed_seconds": float(elapsed_seconds),
        "error": outcome.get("error_type"),
        "created_at": time.time(),
    }


def run_arithmetic_benchmark(
    model_ids: list[str] | tuple[str, ...],
    *,
    config: dict[str, Any] | None = None,
    catalog: list[dict[str, Any]] | None = None,
    provider_factory: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    rsi_recorder: Callable[[dict[str, Any]], Any] | None = None,
    on_result: Callable[[dict[str, Any]], Any] | None = None,
    route_timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Run one fixed math task on explicit models and record every result."""
    if current_intelligence_authority().session_mode != "race":
        raise PermissionError("Multi-model benchmarks require an explicit Race Mode session")
    selected_config = dict(config or {})
    selected_config["race_models"] = list(model_ids)
    route_timeout = max(1, int(route_timeout_seconds or selected_config.get("route_timeout_seconds") or 20))
    routes = build_race_model_routes(selected_config, catalog=catalog)
    maximum_parallel = min(4, max(1, int(selected_config.get("max_parallel_models") or 2)))
    if provider_factory is None:
        from sophyane.race_orchestrator import _single_provider

        def provider_factory(route: dict[str, Any], route_config: dict[str, Any]):
            return _single_provider(
                provider_id=str(route["provider_id"]),
                config=route_config,
            )

    if rsi_recorder is None:
        rsi_recorder = _rsi_record

    def execute(route: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        provider_id = str(route["provider_id"])
        model_id = str(route["id"])
        outcome: dict[str, Any] = {
            "model_id": model_id,
            "provider_id": provider_id,
            "model": str(route.get("model") or ""),
            "status": "failed",
            "actual_output": "unavailable",
            "correct": False,
            "latency_seconds": None,
            "completion_tokens": None,
            "tokens_per_second": None,
            "exit_status": None,
            "error_type": None,
        }
        try:
            if not route.get("available"):
                raise RuntimeError("provider unavailable")
            route_config = dict(selected_config)
            route_config.update(
                {
                    "race_model_id": model_id,
                    "provider": provider_id,
                    "model": route.get("model") or "",
                    "provider_fallback_order": (),
                    "timeout": route_timeout,
                }
            )
            if provider_id == "local_gguf":
                route_config.update(
                    {
                        "gguf_path": route["gguf_path"],
                        "cli_path": route["cli_path"],
                        "timeout": min(route_timeout, int(route["timeout"])),
                        "max_tokens": route["max_tokens"],
                        "reasoning": route["reasoning"],
                        "temperature": 0.0,
                    }
                )
            from sophyane.race_orchestrator import _generate_provider_for_race

            provider = provider_factory(route, route_config)
            raw = str(
                _generate_provider_for_race(
                    provider=provider,
                    provider_id=provider_id,
                    prompt=ARITHMETIC_PROMPT,
                    system_prompt="Reply with the final answer only. Disable optional reasoning when supported.",
                )
                or ""
            ).strip()
            metrics = getattr(provider, "last_metrics", {})
            metrics = metrics if isinstance(metrics, dict) else {}
            outcome.update(
                {
                    "status": "completed",
                    "actual_output": _safe_observed_output(raw),
                    "correct": verify_math_answer(ARITHMETIC_PROMPT, raw),
                    "completion_tokens": metrics.get("completion_tokens"),
                    "tokens_per_second": metrics.get("tokens_per_second"),
                    "exit_status": metrics.get("exit_status"),
                }
            )
        except Exception as error:  # noqa: BLE001
            outcome["error_type"] = type(error).__name__
            outcome["failure_class"] = _failure_class(error)
        elapsed = max(0.0, time.monotonic() - started)
        outcome["latency_seconds"] = elapsed
        for key in ("completion_tokens", "tokens_per_second"):
            value = outcome.get(key)
            if isinstance(value, float) and not math.isfinite(value):
                outcome[key] = None
        outcome.setdefault("failure_class", None)
        event = _rsi_event(outcome, elapsed_seconds=elapsed)
        try:
            rsi_recorder(event)
            outcome["rsi_recorded"] = True
        except Exception as error:  # noqa: BLE001
            outcome["rsi_recorded"] = False
            outcome["rsi_error_type"] = type(error).__name__
        return outcome

    outcomes: dict[str, dict[str, Any]] = {}
    callback_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=maximum_parallel, thread_name_prefix="sophyane-benchmark") as executor:
        future_ids = {executor.submit(execute, route): route["id"] for route in routes}
        for future in as_completed(future_ids):
            model_id = str(future_ids[future])
            try:
                outcomes[model_id] = future.result()
            except Exception as error:  # noqa: BLE001
                outcomes[model_id] = {
                    "model_id": model_id,
                    "provider_id": "unknown",
                    "model": "",
                    "status": "failed",
                    "actual_output": "unavailable",
                    "correct": False,
                    "latency_seconds": None,
                    "completion_tokens": None,
                    "tokens_per_second": None,
                    "exit_status": None,
                    "error_type": type(error).__name__,
                    "failure_class": _failure_class(error),
                    "rsi_recorded": False,
                }
            if on_result is not None:
                with callback_lock:
                    on_result(dict(outcomes[model_id]))
    ordered = [outcomes[str(route["id"])] for route in routes]
    return {
        "schema_version": "sophyane.multimodel-benchmark.v1",
        "task": {
            "category": "mathematics",
            "prompt": ARITHMETIC_PROMPT,
            "expected": "6",
            "verification": "deterministic exact-answer evaluator; provider agreement is not used",
        },
        "models": ordered,
        "summary": {
            "requested": len(routes),
            "completed": sum(item["status"] == "completed" for item in ordered),
            "correct": sum(bool(item["correct"]) for item in ordered),
            "failed": sum(item["status"] != "completed" for item in ordered),
        },
    }

