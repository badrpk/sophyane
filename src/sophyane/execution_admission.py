"""Pure pre-execution admission classification for the unified kernel.

This module does not execute capabilities, mutate the workspace, contact a
provider, or grant authority. It only describes the policy capability class
that a request would require if an existing deterministic handler claims it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sophyane.local_coding_capability import (
    recognizes_coding_request,
)
from sophyane.capability_executors import (
    _is_judge_validation_request,
    _is_shell_exit_probe_request,
    _parse_exact_file_write,
)
from sophyane.runtime_filesystem_capabilities_v20 import classify_request
from sophyane.task_compiler import should_compile


@dataclass(frozen=True)
class ExecutionAdmission:
    runtime_family: str
    policy_capabilities: tuple[str, ...]
    read_only: bool
    side_effects: frozenset[str]


_FILESYSTEM_READ_TYPES = frozenset(
    {
        "filesystem.duplicate_files",
        "filesystem.empty_directories",
        "filesystem.modified_today",
        "filesystem.largest_file_parent",
        "filesystem.top_largest_files",
        "filesystem.largest_file",
        "filesystem.oldest_file",
        "filesystem.list_files",
        "filesystem.list_folders",
        "filesystem.folder_count",
        "filesystem.file_count",
        "filesystem.directory_size",
    }
)

def _coding_admission(request: str) -> ExecutionAdmission | None:
    if not recognizes_coding_request(request):
        return None

    return ExecutionAdmission(
        runtime_family="development.local_coding",
        policy_capabilities=(
            "local_reasoning",
            "local_filesystem",
            "local_process_execution",
        ),
        read_only=False,
        side_effects=frozenset(
            {
                "filesystem_write",
                "process_execution",
            }
        ),
    )


def classify_execution_admission(
    request: str,
    *,
    workspace: str | Path | None = None,
) -> ExecutionAdmission | None:
    """Describe required policy capabilities without executing the request."""

    del workspace

    text = " ".join(str(request or "").strip().split())
    if not text:
        return None

    # Highest-priority deterministic harness branches. These predicates are
    # shared with execute_deterministic_capability(), so admission cannot drift
    # from the actual execution recognition frontier.
    if (
        _is_shell_exit_probe_request(text)
        or _is_judge_validation_request(text)
    ):
        return ExecutionAdmission(
            runtime_family="legacy.deterministic_capabilities",
            policy_capabilities=(
                "local_reasoning",
                "local_filesystem",
                "local_process_execution",
            ),
            read_only=False,
            side_effects=frozenset(
                {
                    "filesystem_write",
                    "process_execution",
                }
            ),
        )

    # Registry priority 10: development.local_coding.
    coding = _coding_admission(text)
    if coding is not None:
        return coding

    # Registry priority 11: deterministic capabilities.
    if _parse_exact_file_write(text) is not None:
        return ExecutionAdmission(
            runtime_family="legacy.deterministic_capabilities",
            policy_capabilities=(
                "local_reasoning",
                "local_filesystem",
            ),
            read_only=False,
            side_effects=frozenset(
                {
                    "filesystem_write",
                }
            ),
        )

    classified = classify_request(text)
    capability_type = ""

    if isinstance(classified, str):
        capability_type = classified
    elif isinstance(classified, dict):
        capability_type = str(
            classified.get("type")
            or classified.get("capability")
            or classified.get("capability_id")
            or classified.get("action")
            or ""
        )
    elif classified:
        capability_type = str(
            getattr(classified, "type", "")
            or getattr(classified, "capability", "")
            or getattr(classified, "capability_id", "")
            or getattr(classified, "action", "")
        )

    if capability_type in _FILESYSTEM_READ_TYPES:
        return ExecutionAdmission(
            runtime_family="legacy.deterministic_capabilities",
            policy_capabilities=(
                "local_reasoning",
                "local_filesystem_read",
            ),
            read_only=True,
            side_effects=frozenset(),
        )

    # Registry priority 12 is reasoning.direct_local. It is intentionally not
    # claimed here: admission must not guess whether that handler will accept
    # arbitrary natural language.

    # Registry priority 15: reasoning.task_compiler. should_compile() is pure.
    if should_compile(text):
        return ExecutionAdmission(
            runtime_family="reasoning.task_compiler",
            policy_capabilities=(
                "local_reasoning",
            ),
            read_only=True,
            side_effects=frozenset(),
        )

    return None


__all__ = [
    "ExecutionAdmission",
    "classify_execution_admission",
]
