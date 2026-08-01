from sophyane.observability.tracing import start_trace, span, list_traces as _native_list_traces
from sophyane.observability.accounting import record_usage, summarize
from sophyane.observability.datasets import (
    Dataset, Example, save_prompt_version, load_prompt,
    run_experiment, exact_match, compare_experiments,
)

__all__ = [
    "start_trace", "span", "list_traces",
    "record_usage", "summarize",
    "Dataset", "Example", "save_prompt_version", "load_prompt",
    "run_experiment", "exact_match", "compare_experiments",
]


def _list_native_traces(limit: int = 20):
    """Return traces using the historical mapping-shaped API.

    The newer tracing layer may return a bare list. Older callers expect a
    dictionary containing ``traces`` and ``count``.
    """
    result = _native_list_traces(limit=limit)

    if isinstance(result, dict):
        traces = result.get("traces", [])
        normalized = dict(result)
        normalized.setdefault("ok", True)
        normalized["traces"] = traces
        normalized["count"] = int(
            normalized.get("count", len(traces))
        )
        return normalized

    traces = list(result or [])
    return {
        "ok": True,
        "traces": traces,
        "count": len(traces),
    }

# SOPHYANE_DURABLE_RUN_COMPAT_V1
import json as _compat_json
import time as _compat_time
import uuid as _compat_uuid
from pathlib import Path as _CompatPath

_COMPAT_TRACE_DIR = (
    _CompatPath.home()
    / ".local"
    / "state"
    / "sophyane"
    / "traces"
)


def _compat_append(run_id: str, event: dict) -> None:
    _COMPAT_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    target = _COMPAT_TRACE_DIR / f"{run_id}.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(
            _compat_json.dumps(event, ensure_ascii=False) + "\n"
        )


def start_run(
    name: str = "run",
    *,
    meta: dict | None = None,
    tags: dict | None = None,
    **fields,
) -> str:
    run_id = _compat_uuid.uuid4().hex[:16]
    _compat_append(
        run_id,
        {
            "type": "run_start",
            "run_id": run_id,
            "name": name,
            "meta": meta or {},
            "tags": tags or {},
            "fields": fields,
            "ts": _compat_time.time(),
        },
    )
    return run_id


def end_run(
    trace=None,
    *,
    ok: bool = True,
    summary: str = "",
    **fields,
) -> None:
    if isinstance(trace, str) and trace:
        _compat_append(
            trace,
            {
                "type": "run_end",
                "run_id": trace,
                "ok": bool(ok),
                "summary": summary,
                "fields": fields,
                "ts": _compat_time.time(),
            },
        )
    elif trace is not None and hasattr(trace, "save"):
        try:
            trace.save()
        except Exception:
            pass


def _list_compat_traces(limit: int = 20) -> dict:
    _COMPAT_TRACE_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(
        _COMPAT_TRACE_DIR.glob("*.jsonl"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:max(1, int(limit))]

    traces = []

    for file in files:
        item = {
            "run_id": file.stem,
            "path": str(file),
        }

        try:
            lines = file.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()

            if lines:
                item["start"] = _compat_json.loads(lines[0])
            if len(lines) > 1:
                item["end"] = _compat_json.loads(lines[-1])
        except Exception:
            pass

        traces.append(item)

    return {
        "ok": True,
        "traces": traces,
        "count": len(traces),
    }



# SOPHYANE_CONSOLIDATED_LIST_TRACES_V1
def list_traces(limit: int = 20) -> dict:
    """Return a unified, mapping-shaped trace listing.

    Native and compatibility trace stores may coexist during migration.
    Results are merged and deduplicated while preserving newest-first order.
    """
    bounded_limit = max(1, int(limit))

    def normalize(value: object) -> list[dict]:
        if isinstance(value, dict):
            items = value.get("traces", [])
        elif isinstance(value, list):
            items = value
        else:
            items = []

        return [
            dict(item)
            for item in items
            if isinstance(item, dict)
        ]

    native_result: object

    try:
        native_result = _list_native_traces(
            limit=bounded_limit,
        )
    except Exception:
        native_result = {
            "ok": False,
            "traces": [],
            "count": 0,
        }

    try:
        compat_result: object = _list_compat_traces(
            limit=bounded_limit,
        )
    except Exception:
        compat_result = {
            "ok": False,
            "traces": [],
            "count": 0,
        }

    merged: list[dict] = []
    seen: set[str] = set()

    for item in (
        normalize(native_result)
        + normalize(compat_result)
    ):
        identity = str(
            item.get("run_id")
            or item.get("trace_id")
            or item.get("id")
            or item.get("path")
            or repr(sorted(item.items()))
        )

        if identity in seen:
            continue

        seen.add(identity)
        merged.append(item)

        if len(merged) >= bounded_limit:
            break

    return {
        "ok": True,
        "traces": merged,
        "count": len(merged),
    }
