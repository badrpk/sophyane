"""Deterministic SLI composer for grounded Python harness contracts.

This module is separate from browser composition. It supports a bounded set
of explicit harness-engineering contracts, writes exactly one Python module,
compiles it, imports it and executes a contract smoke test.

It does not call an LLM, network, browser, subprocess or shell.
"""
from __future__ import annotations

import importlib.util
import py_compile
import re
import shutil
import sys
import tempfile
import textwrap

from pathlib import Path
from typing import Callable


Progress = Callable[[str], None]


SUPPORTED_CONTRACTS = {
    "provider_policy",
    "retry_controller",
    "sandbox_guard",
    "audit_chain",
    "capability_solver",
}


DEFAULT_FILENAMES = {
    "provider_policy": "policy_engine.py",
    "retry_controller": "retry_controller.py",
    "sandbox_guard": "sandbox_guard.py",
    "audit_chain": "audit_chain.py",
    "capability_solver": "capability_solver.py",
}


REQUIRED_SYMBOLS = {
    "provider_policy": {"decide_route"},
    "retry_controller": {"execute_with_validation"},
    "sandbox_guard": {"resolve_safe"},
    "audit_chain": {"append_event", "verify_chain"},
    "capability_solver": {"solve"},
}


def _normalise(message: str) -> str:
    return " ".join(str(message or "").lower().split())


def detect_python_harness_request(message: str) -> bool:
    """Return True only for explicit Python harness-engineering requests."""

    text = _normalise(message)

    exact_markers = (
        "policy_engine.py",
        "retry_controller.py",
        "sandbox_guard.py",
        "audit_chain.py",
        "capability_solver.py",
        "decide_route",
        "execute_with_validation",
        "resolve_safe",
        "append_event",
        "verify_chain",
    )

    conceptual_markers = (
        "provider policy",
        "validator failures",
        "retry controller",
        "path traversal",
        "symlink escape",
        "tamper-evident",
        "audit chain",
        "dependency closure",
        "capability solver",
    )

    explicit_python = (
        "python file" in text
        or "python module" in text
        or bool(
            re.search(
                r"\b[a-z_][a-z0-9_]*\.py\b",
                text,
            )
        )
    )

    return (
        any(marker in text for marker in exact_markers)
        or any(marker in text for marker in conceptual_markers)
        or (
            explicit_python
            and any(
                marker in text
                for marker in (
                    "provider",
                    "retry",
                    "validator",
                    "sandbox",
                    "audit",
                    "dependency",
                    "capability",
                )
            )
        )
    )


def classify_python_harness_request(message: str) -> str | None:
    text = _normalise(message)

    if (
        "decide_route" in text
        or "policy_engine.py" in text
        or "provider policy" in text
        or (
            "validator_failures" in text
            and "cloud_budget_remaining" in text
        )
    ):
        return "provider_policy"

    if (
        "execute_with_validation" in text
        or "retry_controller.py" in text
        or "retry controller" in text
        or (
            "local_runner" in text
            and "cloud_runner" in text
        )
    ):
        return "retry_controller"

    if (
        "resolve_safe" in text
        or "sandbox_guard.py" in text
        or "path traversal" in text
        or "symlink escape" in text
    ):
        return "sandbox_guard"

    if (
        "append_event" in text
        or "verify_chain" in text
        or "audit_chain.py" in text
        or "audit chain" in text
        or "tamper-evident" in text
    ):
        return "audit_chain"

    if (
        "capability_solver.py" in text
        or "capability solver" in text
        or "dependency closure" in text
        or (
            "solve(" in text
            and "provides" in text
            and "requires" in text
        )
    ):
        return "capability_solver"

    return None


def extract_requested_filename(message: str, contract: str) -> str:
    patterns = (
        r"\bnamed\s+([a-zA-Z_][a-zA-Z0-9_]*\.py)\b",
        r"\bfile\s+([a-zA-Z_][a-zA-Z0-9_]*\.py)\b",
        r"\b([a-zA-Z_][a-zA-Z0-9_]*\.py)\b",
    )

    for pattern in patterns:
        match = re.search(pattern, message, flags=re.I)

        if match:
            return Path(match.group(1)).name

    return DEFAULT_FILENAMES[contract]


SOURCES = {
    "provider_policy": r'''
"""Deterministic provider-routing policy."""
from __future__ import annotations

from typing import Any, Mapping


def decide_route(metrics: Mapping[str, Any]) -> str:
    """Return ``local``, ``cloud`` or ``fail``."""

    local_available = bool(metrics.get("local_available", False))
    cloud_available = bool(metrics.get("cloud_available", False))
    security_sensitive = bool(metrics.get("security_sensitive", False))

    try:
        failures = int(metrics.get("validator_failures", 0))
    except (TypeError, ValueError):
        failures = 0

    try:
        cloud_budget = float(metrics.get("cloud_budget_remaining", 0))
    except (TypeError, ValueError):
        cloud_budget = 0.0

    if security_sensitive:
        return "local" if local_available else "fail"

    if local_available and failures < 2:
        return "local"

    if failures >= 2 and cloud_available and cloud_budget > 0:
        return "cloud"

    return "fail"
''',

    "retry_controller": r'''
"""Validator-driven local retry with bounded cloud escalation."""
from __future__ import annotations

from typing import Any, Callable, TypeVar


T = TypeVar("T")


def execute_with_validation(
    task: Any,
    local_runner: Callable[[Any], T],
    cloud_runner: Callable[[Any], T],
    validator: Callable[[T], bool],
    max_local_attempts: int = 2,
) -> T:
    """Try local first, then call cloud at most once."""

    try:
        attempts = max(0, int(max_local_attempts))
    except (TypeError, ValueError):
        attempts = 0

    failures: list[str] = []

    for attempt in range(attempts):
        result = local_runner(task)

        try:
            valid = bool(validator(result))
        except Exception as error:
            valid = False
            failures.append(
                f"local attempt {attempt + 1} validator error: {error}"
            )

        if valid:
            return result

        failures.append(
            f"local attempt {attempt + 1} failed validation"
        )

    cloud_result = cloud_runner(task)

    try:
        cloud_valid = bool(validator(cloud_result))
    except Exception as error:
        cloud_valid = False
        failures.append(f"cloud validator error: {error}")

    if cloud_valid:
        return cloud_result

    failures.append("cloud result failed validation")

    raise RuntimeError(
        "All execution attempts failed validation: "
        + "; ".join(failures)
    )
''',

    "sandbox_guard": r'''
"""Canonical path-containment guard."""
from __future__ import annotations

from pathlib import Path
from typing import Union


PathLike = Union[str, Path]


def resolve_safe(root: PathLike, candidate: PathLike) -> Path:
    """Resolve candidate and require it to remain inside root."""

    root_path = Path(root).expanduser().resolve(strict=False)
    candidate_path = Path(candidate).expanduser()

    if ".." in candidate_path.parts:
        raise PermissionError(
            "Parent-directory traversal is not allowed"
        )

    combined = (
        candidate_path
        if candidate_path.is_absolute()
        else root_path / candidate_path
    )

    resolved = combined.resolve(strict=False)

    try:
        resolved.relative_to(root_path)
    except ValueError as error:
        raise PermissionError(
            f"Path escapes sandbox root: {candidate}"
        ) from error

    return resolved
''',

    "audit_chain": r'''
"""Tamper-evident append-only JSON Lines audit chain."""
from __future__ import annotations

import hashlib
import json

from pathlib import Path
from typing import Any, Mapping


GENESIS_HASH = "0" * 64


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash(event: Mapping[str, Any], previous_hash: str) -> str:
    payload = {
        "event": dict(event),
        "previous_hash": previous_hash,
    }

    return hashlib.sha256(
        _canonical(payload).encode("utf-8")
    ).hexdigest()


def verify_chain(path: str | Path) -> bool:
    chain_path = Path(path)

    if not chain_path.exists():
        return True

    previous = GENESIS_HASH

    try:
        with chain_path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                if not raw.strip():
                    return False

                record = json.loads(raw)

                if not isinstance(record, dict):
                    return False

                event = record.get("event")
                recorded_previous = record.get("previous_hash")
                recorded_hash = record.get("hash")

                if not isinstance(event, dict):
                    return False

                if recorded_previous != previous:
                    return False

                expected = _hash(event, previous)

                if recorded_hash != expected:
                    return False

                previous = recorded_hash

    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return False

    return True


def append_event(
    path: str | Path,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one valid record to the chain."""

    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")

    chain_path = Path(path)
    chain_path.parent.mkdir(parents=True, exist_ok=True)

    if chain_path.exists() and not verify_chain(chain_path):
        raise ValueError("Cannot append to an invalid audit chain")

    previous = GENESIS_HASH

    if chain_path.exists():
        lines = [
            line
            for line in chain_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        ]

        if lines:
            previous = str(json.loads(lines[-1])["hash"])

    event_copy = dict(event)

    record = {
        "event": event_copy,
        "previous_hash": previous,
        "hash": _hash(event_copy, previous),
    }

    with chain_path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical(record) + "\n")

    return record
''',

    "capability_solver": r'''
"""Deterministic minimal capability-dependency solver."""
from __future__ import annotations

from itertools import combinations
from typing import Any, Iterable, Mapping, Sequence


def _normalise(
    components: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for component in components:
        component_id = str(component.get("id", "")).strip()

        if not component_id or component_id in seen:
            continue

        seen.add(component_id)

        result.append(
            {
                "id": component_id,
                "provides": {
                    str(value)
                    for value in component.get("provides", [])
                    if str(value)
                },
                "requires": {
                    str(value)
                    for value in component.get("requires", [])
                    if str(value)
                },
            }
        )

    result.sort(key=lambda item: item["id"])
    return result


def _order(
    subset: Sequence[dict[str, Any]],
) -> list[str] | None:
    remaining = {
        item["id"]: item
        for item in subset
    }

    available: set[str] = set()
    ordered: list[str] = []

    while remaining:
        ready = sorted(
            (
                item
                for item in remaining.values()
                if item["requires"] <= available
            ),
            key=lambda item: item["id"],
        )

        if not ready:
            return None

        for item in ready:
            ordered.append(item["id"])
            available.update(item["provides"])
            remaining.pop(item["id"])

    return ordered


def solve(
    required: Iterable[str],
    components: Iterable[Mapping[str, Any]],
) -> dict[str, list[str]]:
    """Return a minimal dependency-safe component closure."""

    requested = {
        str(value)
        for value in required
        if str(value)
    }

    available_components = _normalise(components)

    if not requested:
        return {
            "selected": [],
            "unresolved": [],
        }

    all_provided = (
        set().union(
            *(item["provides"] for item in available_components)
        )
        if available_components
        else set()
    )

    initially_missing = sorted(requested - all_provided)

    if initially_missing:
        return {
            "selected": [],
            "unresolved": initially_missing,
        }

    for size in range(1, len(available_components) + 1):
        subsets = sorted(
            combinations(available_components, size),
            key=lambda subset: tuple(
                item["id"] for item in subset
            ),
        )

        for subset in subsets:
            provided = set().union(
                *(item["provides"] for item in subset)
            )

            dependencies = set().union(
                *(item["requires"] for item in subset)
            )

            if not requested <= provided:
                continue

            if not dependencies <= provided:
                continue

            ordered = _order(subset)

            if ordered is None:
                continue

            return {
                "selected": ordered,
                "unresolved": [],
            }

    return {
        "selected": [],
        "unresolved": sorted(requested),
    }
''',
}


def _load_module(path: Path):
    module_name = (
        "_sophyane_python_harness_"
        + path.stem
        + "_"
        + str(abs(hash(path.read_bytes())))
    )

    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import generated module: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


def _validate_provider_policy(module) -> None:
    cases = [
        (
            {
                "local_available": True,
                "cloud_available": True,
                "validator_failures": 0,
                "cloud_budget_remaining": 10,
                "security_sensitive": False,
            },
            "local",
        ),
        (
            {
                "local_available": True,
                "cloud_available": True,
                "validator_failures": 2,
                "cloud_budget_remaining": 10,
                "security_sensitive": False,
            },
            "cloud",
        ),
        (
            {
                "local_available": True,
                "cloud_available": True,
                "validator_failures": 5,
                "cloud_budget_remaining": 0,
                "security_sensitive": False,
            },
            "fail",
        ),
        (
            {
                "local_available": True,
                "cloud_available": True,
                "validator_failures": 5,
                "cloud_budget_remaining": 10,
                "security_sensitive": True,
            },
            "local",
        ),
    ]

    for metrics, expected in cases:
        assert module.decide_route(metrics) == expected


def _validate_retry_controller(module) -> None:
    calls: list[str] = []

    def local_runner(_task):
        calls.append("local")
        return calls.count("local")

    def cloud_runner(_task):
        calls.append("cloud")
        return 99

    result = module.execute_with_validation(
        "task",
        local_runner,
        cloud_runner,
        lambda value: value == 2,
        max_local_attempts=2,
    )

    assert result == 2
    assert calls == ["local", "local"]


def _validate_sandbox_guard(module) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "root"
        root.mkdir()

        inside = root / "inside.txt"
        inside.write_text("safe", encoding="utf-8")

        assert module.resolve_safe(
            root,
            "inside.txt",
        ) == inside.resolve()

        try:
            module.resolve_safe(root, "../outside.txt")
        except (ValueError, PermissionError):
            pass
        else:
            raise AssertionError("Traversal was not rejected")


def _validate_audit_chain(module) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "audit.jsonl"

        module.append_event(
            path,
            {"action": "plan", "ok": True},
        )
        module.append_event(
            path,
            {"action": "execute", "ok": True},
        )

        assert module.verify_chain(path) is True

        lines = path.read_text(
            encoding="utf-8"
        ).splitlines()

        record = lines[0].replace(
            '"plan"',
            '"tampered"',
        )
        lines[0] = record

        path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

        assert module.verify_chain(path) is False


def _validate_capability_solver(module) -> None:
    components = [
        {
            "id": "shell",
            "provides": ["document"],
            "requires": [],
        },
        {
            "id": "state",
            "provides": ["state"],
            "requires": [],
        },
        {
            "id": "renderer",
            "provides": ["render"],
            "requires": ["document", "state"],
        },
        {
            "id": "input",
            "provides": ["input"],
            "requires": ["state"],
        },
        {
            "id": "controller",
            "provides": ["application"],
            "requires": ["render", "input"],
        },
    ]

    result = module.solve(
        ["application"],
        components,
    )

    assert set(result["selected"]) == {
        "shell",
        "state",
        "renderer",
        "input",
        "controller",
    }

    assert result["unresolved"] == []


VALIDATORS = {
    "provider_policy": _validate_provider_policy,
    "retry_controller": _validate_retry_controller,
    "sandbox_guard": _validate_sandbox_guard,
    "audit_chain": _validate_audit_chain,
    "capability_solver": _validate_capability_solver,
}


def compose_python_harness_request(
    message: str,
    workspace: Path,
    *,
    progress: Progress | None = None,
) -> str:
    """Build and validate one supported Python harness artifact."""

    progress = progress or (lambda _message: None)
    workspace = Path(workspace)

    contract = classify_python_harness_request(message)

    if contract not in SUPPORTED_CONTRACTS:
        return (
            "SLI Python-harness family recognized, but no grounded "
            "contract implementation matches this request.\n"
            "Supported contracts: "
            + ", ".join(sorted(SUPPORTED_CONTRACTS))
            + "\nNo browser was opened.\n"
            "No LLM fallback was used."
        )

    filename = extract_requested_filename(message, contract)

    if (
        Path(filename).name != filename
        or not filename.endswith(".py")
    ):
        return (
            "SLI Python-harness request rejected: unsafe output filename "
            f"{filename!r}.\n"
            "No browser was opened.\n"
            "No LLM fallback was used."
        )

    workspace.mkdir(parents=True, exist_ok=True)

    for child in workspace.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)

    output = workspace / filename

    output.write_text(
        textwrap.dedent(SOURCES[contract]).lstrip(),
        encoding="utf-8",
    )

    progress(
        f"SLI Python harness: wrote {filename}"
    )

    try:
        py_compile.compile(str(output), doraise=True)
        module = _load_module(output)

        for symbol in REQUIRED_SYMBOLS[contract]:
            if not callable(getattr(module, symbol, None)):
                raise AssertionError(
                    f"Missing required callable: {symbol}"
                )

        VALIDATORS[contract](module)

    except Exception as error:
        output.unlink(missing_ok=True)

        return (
            "SLI Python-harness composition rejected.\n"
            f"Contract: {contract}\n"
            f"Validation error: {type(error).__name__}: {error}\n"
            "No browser was opened.\n"
            "No LLM fallback was used."
        )

    return "\n".join(
        [
            "Sophyane grounded Python-harness composer",
            f"Contract: {contract}",
            f"Request: {message}",
            f"Files: {filename}",
            "Python compilation: passed",
            "Required symbols: passed",
            "Grounded contract smoke test: passed",
            "Browser preview: forbidden",
            "Success: True",
            (
                "Inference: deterministic SLI contract components only; "
                "no local/cloud LLM"
            ),
        ]
    )


__all__ = [
    "SUPPORTED_CONTRACTS",
    "classify_python_harness_request",
    "compose_python_harness_request",
    "detect_python_harness_request",
    "extract_requested_filename",
]

# SOPHYANE_NO_BYTECODE_WORKSPACE_V1
# Wrap the grounded composer so contract imports never leave .pyc files in
# the requested artifact workspace.

_SLI_GROUNDED_COMPOSE_BASE = compose_python_harness_request


def _sli_remove_bytecode(workspace) -> None:
    from pathlib import Path as _Path
    import shutil as _shutil

    root = _Path(workspace)

    for cache in root.rglob("__pycache__"):
        _shutil.rmtree(
            cache,
            ignore_errors=True,
        )

    for bytecode in root.rglob("*.pyc"):
        bytecode.unlink(
            missing_ok=True,
        )


def compose_python_harness_request(
    message: str,
    workspace,
    *,
    progress=None,
):
    import sys as _sys

    previous = bool(
        getattr(
            _sys,
            "dont_write_bytecode",
            False,
        )
    )

    _sys.dont_write_bytecode = True

    try:
        result = _SLI_GROUNDED_COMPOSE_BASE(
            message,
            workspace,
            progress=progress,
        )
    finally:
        _sys.dont_write_bytecode = previous
        _sli_remove_bytecode(workspace)

    return result
