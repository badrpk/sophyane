"""Sophyane continual federated training (C++ core + thin Python orchestration).

Base GGUF / local LLM weights stay on device. Parameter-efficient adapter
deltas are trained in pure C++ and federated across opted-in mesh peers so
millions of installs can improve the shared Sophyane model over time.
"""

from sophyane.continual.engine import (
    contribute_round,
    ensure_train_core,
    federated_aggregate,
    record_experience,
    run_local_train_step,
    train_opt_in,
    train_status,
)

__all__ = [
    "contribute_round",
    "ensure_train_core",
    "federated_aggregate",
    "record_experience",
    "run_local_train_step",
    "train_opt_in",
    "train_status",
]
