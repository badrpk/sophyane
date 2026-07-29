from sophyane.observability.tracing import start_trace, span, list_traces
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


# Back-compat aliases used by older tests
def start_run(name: str = "run", **kwargs):
    """Alias for start_trace context manager."""
    from sophyane.observability.tracing import start_trace
    return start_trace(name, tags=kwargs.get("tags"))

def end_run(trace=None):
    """No-op closer; start_trace already saves on context exit."""
    if trace is not None and hasattr(trace, "save"):
        try:
            trace.save()
        except Exception:
            pass
    return None
