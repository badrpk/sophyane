"""Compatibility adapter for Sophyane's deterministic Python harness.

The repository has had several Python-harness entry-point names. This adapter
discovers a compatible callable from the installed module, maps arguments by
signature and verifies that the invocation produced a Python artifact.

No local or cloud LLM is used.
"""
from __future__ import annotations

import inspect
import py_compile

from pathlib import Path
from typing import Any, Callable


Progress = Callable[[str], None]


EXPLICIT_CANDIDATES = (
    "compose_python_harness",
    "compose_python_request",
    "compose_python_contract",
    "compose_harness_request",
    "build_python_harness",
    "generate_python_harness",
    "try_python_harness",
    "write_python_harness",
    "compose_request",
)


REQUEST_NAMES = {
    "request",
    "message",
    "instruction",
    "prompt",
    "task",
    "text",
}


WORKSPACE_NAMES = {
    "workspace",
    "root",
    "directory",
    "output_dir",
    "output_directory",
    "target_dir",
    "path",
}


PROGRESS_NAMES = {
    "progress",
    "progress_callback",
    "callback",
    "logger",
    "log",
}


def _progress(
    callback: Progress | None,
) -> Progress:
    return callback or (
        lambda _message: None
    )


def _defined_in_module(
    value: object,
    module_name: str,
) -> bool:
    return (
        inspect.isfunction(value)
        and getattr(
            value,
            "__module__",
            "",
        )
        == module_name
    )


def _candidate_score(
    name: str,
    value: object,
    module_name: str,
) -> int:
    if not callable(value):
        return -10_000

    if not _defined_in_module(
        value,
        module_name,
    ):
        return -10_000

    low = name.lower()
    score = 0

    if name in EXPLICIT_CANDIDATES:
        score += (
            1_000
            - EXPLICIT_CANDIDATES.index(name)
        )

    if "compose" in low:
        score += 120

    if "python" in low:
        score += 100

    if "harness" in low:
        score += 100

    if any(
        word in low
        for word in (
            "test",
            "smoke",
            "validate",
            "compile",
            "main",
            "cli",
        )
    ):
        score -= 200

    try:
        signature = inspect.signature(
            value
        )
    except (TypeError, ValueError):
        return score - 100

    names = {
        parameter.name
        for parameter in signature.parameters.values()
    }

    if names & REQUEST_NAMES:
        score += 100

    if names & WORKSPACE_NAMES:
        score += 100

    return score


def discover_python_harness_callable():
    import sophyane.code_memory.python_harness_compose as module

    candidates = []

    for name in dir(module):
        if name.startswith("_"):
            continue

        value = getattr(
            module,
            name,
        )

        score = _candidate_score(
            name,
            value,
            module.__name__,
        )

        if score > 0:
            candidates.append(
                (
                    score,
                    name,
                    value,
                )
            )

    candidates.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    if not candidates:
        available = []

        for name in sorted(
            dir(module)
        ):
            if name.startswith("_"):
                continue

            value = getattr(
                module,
                name,
            )

            if callable(value):
                try:
                    signature = inspect.signature(
                        value
                    )
                except (TypeError, ValueError):
                    signature = "(unknown)"

                available.append(
                    f"{name}{signature}"
                )

        raise ImportError(
            "No compatible Python-harness callable was found. "
            "Available callables: "
            + ", ".join(
                available
            )
        )

    _score, name, function = candidates[0]

    return name, function


def _invoke(
    function,
    *,
    request: str,
    workspace: Path,
    progress: Progress,
):
    signature = inspect.signature(
        function
    )

    positional = []
    keyword: dict[str, Any] = {}

    unresolved_required = []

    for parameter in signature.parameters.values():
        name = parameter.name

        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue

        if name in REQUEST_NAMES:
            value = request
        elif name in WORKSPACE_NAMES:
            value = workspace
        elif name in PROGRESS_NAMES:
            value = progress
        elif name in {
            "open_browser",
            "preview",
            "auto_open",
        }:
            value = False
        elif parameter.default is not inspect.Parameter.empty:
            continue
        else:
            unresolved_required.append(
                name
            )
            continue

        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            positional.append(
                value
            )
        else:
            keyword[
                name
            ] = value

    if unresolved_required:
        # A final bounded positional fallback supports older functions like:
        #     compose(request, workspace, progress=None)
        parameters = list(
            signature.parameters.values()
        )

        if (
            len(parameters) >= 2
            and parameters[0].default
                is inspect.Parameter.empty
            and parameters[1].default
                is inspect.Parameter.empty
        ):
            positional = [
                request,
                workspace,
            ]

            keyword = {}

            if len(parameters) >= 3:
                third = parameters[2]

                if (
                    third.name in PROGRESS_NAMES
                    or third.default
                        is not inspect.Parameter.empty
                ):
                    keyword[
                        third.name
                    ] = progress
        else:
            raise TypeError(
                "Cannot map required parameters "
                + str(
                    unresolved_required
                )
                + " for "
                + str(signature)
            )

    return function(
        *positional,
        **keyword,
    )


def _normalise_result(
    result,
) -> tuple[str, list[str]]:
    report = ""
    used: list[str] = []

    if isinstance(
        result,
        tuple,
    ):
        if result:
            report = str(
                result[0]
            )

        if (
            len(result) > 1
            and isinstance(
                result[1],
                (list, tuple, set),
            )
        ):
            used = [
                str(value)
                for value in result[1]
            ]

    elif isinstance(
        result,
        dict,
    ):
        report = str(
            result.get("report")
            or result.get("message")
            or result.get("result")
            or ""
        )

        raw_used = (
            result.get("used")
            or result.get("used_chunks")
            or []
        )

        if isinstance(
            raw_used,
            (list, tuple, set),
        ):
            used = [
                str(value)
                for value in raw_used
            ]

    else:
        report = str(
            result or ""
        )

    return report, used


def compose_python_harness(
    request: str,
    workspace: Path,
    *,
    progress: Progress | None = None,
) -> tuple[str, list[str]]:
    """Run the repository's real deterministic Python-harness composer."""

    callback = _progress(
        progress
    )

    workspace = Path(
        workspace
    ).expanduser().resolve()

    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )

    name, function = (
        discover_python_harness_callable()
    )

    callback(
        "SLI Python-harness adapter selected: "
        + name
        + str(
            inspect.signature(
                function
            )
        )
    )

    result = _invoke(
        function,
        request=request,
        workspace=workspace,
        progress=callback,
    )

    report, used = _normalise_result(
        result
    )

    python_files = sorted(
        path
        for path in workspace.rglob(
            "*.py"
        )
        if "__pycache__" not in path.parts
    )

    if not python_files:
        return (
            (
                "SLI Python-harness adapter failed.\n"
                f"Selected entry point: {name}\n"
                "No Python artifact was produced.\n"
                "Success: False\n"
                "No LLM fallback was used."
            ),
            used,
        )

    compile_failures = []

    for path in python_files:
        try:
            py_compile.compile(
                str(path),
                doraise=True,
            )
        except py_compile.PyCompileError as error:
            compile_failures.append(
                f"{path.name}: {error}"
            )

    if compile_failures:
        for path in python_files:
            path.unlink(
                missing_ok=True
            )

        return (
            (
                "SLI Python-harness adapter failed.\n"
                f"Selected entry point: {name}\n"
                "Python compilation failed:\n"
                + "\n".join(
                    "  - " + failure
                    for failure in compile_failures
                )
                + "\nSuccess: False\n"
                + "No LLM fallback was used."
            ),
            used,
        )

    low = report.lower()

    if (
        "success: false" in low
        or "traceback" in low
        or "failed" in low
        and "failed: 0" not in low
    ):
        return (
            report,
            used,
        )

    if "success: true" not in low:
        report = (
            report.rstrip()
            + "\n"
            + f"Python-harness entry point: {name}\n"
            + "Python compilation: passed\n"
            + "Files: "
            + ", ".join(
                path.name
                for path in python_files
            )
            + "\nSuccess: True\n"
            + "Inference: deterministic SLI Python harness; "
              "no local/cloud LLM"
        )

    return report, used


__all__ = [
    "compose_python_harness",
    "discover_python_harness_callable",
]
