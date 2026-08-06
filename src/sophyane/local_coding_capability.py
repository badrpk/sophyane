"""Deterministic local coding actions for Sophyane.

This module handles narrowly bounded development requests without asking an LLM
to pretend that files were created or commands were executed.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_CPP_REQUEST = re.compile(
    r"\b(?:create|write|make|generate)\s+"
    r"(?P<filename>[A-Za-z0-9_.-]+\.cpp)\b"
    r"(?P<rest>.*)",
    re.I | re.S,
)

_PY_REQUEST = re.compile(
    r"\b(?:create|write|make|generate)\s+"
    r"(?P<filename>[A-Za-z0-9_.-]+\.py)\b"
    r"(?P<rest>.*)",
    re.I | re.S,
)

_BUILD_CUES = re.compile(
    r"\b(?:compile|build|run|execute|test)\b",
    re.I,
)

_TDD_CUES = re.compile(
    r"\b(?:pytest|tests?|test suite)\b",
    re.I,
)

_REPAIR_CUES = re.compile(
    r"\b(?:repair|fix|rerun|re-run|until all tests pass|"
    r"finish only after all tests pass)\b",
    re.I,
)


_EXPLANATION_CUES = re.compile(
    r"^\s*(?:what\s+is|explain|how\s+does|why\s+does|tell\s+me\s+about)\b",
    re.I,
)


@dataclass(frozen=True)
class CommandEvidence:
    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool


@dataclass(frozen=True)
class CodingResult:
    handled: bool
    ok: bool
    capability: str
    summary: str
    workspace: str
    files: list[str]
    evidence: list[CommandEvidence]
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_text(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _workspace(path: str | Path | None) -> Path:
    root = Path(path or Path.cwd()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_child(root: Path, name: str) -> Path:
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError("Only a plain filename inside the workspace is allowed.")

    target = (root / name).resolve()
    if target.parent != root:
        raise ValueError("Target must remain inside the active workspace.")

    return target


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 120,
) -> CommandEvidence:
    started = time.perf_counter()

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=_clean_environment(),
        )
        return CommandEvidence(
            command=command,
            cwd=str(cwd),
            exit_code=int(completed.returncode),
            stdout=(completed.stdout or "")[-16_000:],
            stderr=(completed.stderr or "")[-16_000:],
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            timed_out=False,
        )
    except subprocess.TimeoutExpired as error:
        return CommandEvidence(
            command=command,
            cwd=str(cwd),
            exit_code=124,
            stdout=_decode_timeout_stream(error.stdout)[-16_000:],
            stderr=(
                _decode_timeout_stream(error.stderr)
                or f"Timed out after {timeout} seconds."
            )[-16_000:],
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            timed_out=True,
        )
    except OSError as error:
        return CommandEvidence(
            command=command,
            cwd=str(cwd),
            exit_code=127,
            stdout="",
            stderr=f"{type(error).__name__}: {error}",
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            timed_out=False,
        )


def _decode_timeout_stream(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _clean_environment() -> dict[str, str]:
    env = os.environ.copy()

    for key in list(env):
        upper = key.upper()
        if any(
            marker in upper
            for marker in (
                "API_KEY",
                "ACCESS_TOKEN",
                "AUTH_TOKEN",
                "PASSWORD",
                "CLIENT_SECRET",
            )
        ):
            env.pop(key, None)

    return env


def _compiler() -> str | None:
    for candidate in ("clang++", "g++", "c++"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _default_cpp(filename: str, request: str) -> str:
    lowered = request.lower()

    if "calculator" in lowered:
        return """#include <iostream>

int main() {
    double a = 0.0;
    double b = 0.0;
    char operation = '+';

    if (!(std::cin >> a >> operation >> b)) {
        std::cerr << "Usage: <number> <operator> <number>\\n";
        return 1;
    }

    switch (operation) {
        case '+': std::cout << a + b << '\\n'; break;
        case '-': std::cout << a - b << '\\n'; break;
        case '*': std::cout << a * b << '\\n'; break;
        case '/':
            if (b == 0.0) {
                std::cerr << "Division by zero\\n";
                return 2;
            }
            std::cout << a / b << '\\n';
            break;
        default:
            std::cerr << "Unsupported operator\\n";
            return 3;
    }

    return 0;
}
"""

    message = "Hello, World!"
    quoted = re.search(r'["“](.{1,200}?)[”"]', request)
    if quoted:
        message = quoted.group(1).replace("\\", "\\\\").replace('"', '\\"')

    return f"""#include <iostream>

int main() {{
    std::cout << "{message}" << std::endl;
    return 0;
}}
"""


def _default_python(filename: str, request: str) -> str:
    lowered = request.lower()

    if "calculator" in lowered:
        return """from __future__ import annotations

import operator

OPERATIONS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
}


def calculate(a: float, operation: str, b: float) -> float:
    if operation not in OPERATIONS:
        raise ValueError(f"Unsupported operation: {operation}")
    if operation == "/" and b == 0:
        raise ZeroDivisionError("division by zero")
    return float(OPERATIONS[operation](a, b))


if __name__ == "__main__":
    print(calculate(2, "+", 3))
"""

    print_call = re.search(
        r"""print\(\s*(['"])(.*?)\1\s*\)""",
        request,
        re.S,
    )

    if print_call:
        message = print_call.group(2)
    else:
        message = "Hello, World!"
        quoted = re.search(
            r"""["“'](.{1,200}?)[”"']""",
            request,
            re.S,
        )
        if quoted:
            message = quoted.group(1)

    return f"""def main() -> None:
    print({message!r})


if __name__ == "__main__":
    main()
"""


def _cpp_action(
    request: str,
    match: re.Match[str],
    workspace: Path,
) -> CodingResult:
    filename = match.group("filename")
    target = _safe_child(workspace, filename)
    executable = _safe_child(workspace, Path(filename).stem)

    target.write_text(
        _default_cpp(filename, request),
        encoding="utf-8",
    )

    evidence: list[CommandEvidence] = []
    should_build = bool(_BUILD_CUES.search(match.group("rest") or request))

    if not should_build:
        return CodingResult(
            handled=True,
            ok=True,
            capability="development.cpp_create",
            summary=f"Created {target.name}.",
            workspace=str(workspace),
            files=[target.name],
            evidence=evidence,
        )

    compiler = _compiler()
    if not compiler:
        return CodingResult(
            handled=True,
            ok=False,
            capability="development.cpp_create_compile",
            summary=f"Created {target.name}, but no C++ compiler was found.",
            workspace=str(workspace),
            files=[target.name],
            evidence=evidence,
            error="Install clang or g++ and retry.",
        )

    compile_result = _run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            target.name,
            "-o",
            executable.name,
        ],
        cwd=workspace,
        timeout=180,
    )
    evidence.append(compile_result)

    if compile_result.exit_code != 0:
        return CodingResult(
            handled=True,
            ok=False,
            capability="development.cpp_create_compile",
            summary=f"Created {target.name}, but compilation failed.",
            workspace=str(workspace),
            files=[target.name],
            evidence=evidence,
            error=compile_result.stderr or compile_result.stdout,
        )

    files = [target.name, executable.name]

    if re.search(r"\b(?:run|execute)\b", request, re.I):
        run_result = _run(
            [str(executable)],
            cwd=workspace,
            timeout=30,
        )
        evidence.append(run_result)

        if run_result.exit_code != 0:
            return CodingResult(
                handled=True,
                ok=False,
                capability="development.cpp_create_compile_run",
                summary=f"Built {executable.name}, but execution failed.",
                workspace=str(workspace),
                files=files,
                evidence=evidence,
                error=run_result.stderr or run_result.stdout,
            )

        capability = "development.cpp_create_compile_run"
        summary = (
            f"Created {target.name}, compiled {executable.name}, "
            "and executed it successfully."
        )
    else:
        capability = "development.cpp_create_compile"
        summary = f"Created {target.name} and compiled {executable.name}."

    return CodingResult(
        handled=True,
        ok=True,
        capability=capability,
        summary=summary,
        workspace=str(workspace),
        files=files,
        evidence=evidence,
    )


def _python_tdd_action(
    request: str,
    match: re.Match[str],
    workspace: Path,
) -> CodingResult:
    """Run a deterministic pytest red-green repair workflow."""
    filename = match.group("filename")
    target = _safe_child(workspace, filename)
    module_name = Path(filename).stem
    test_target = _safe_child(
        workspace,
        f"test_{module_name}.py",
    )

    lowered = request.casefold()

    supported = (
        re.search(
            r"\badd\s*\(\s*a\s*,\s*b\s*\)",
            request,
            re.I,
        )
        or "addition" in lowered
    )

    if not supported:
        return CodingResult(
            handled=False,
            ok=False,
            capability="",
            summary="",
            workspace=str(workspace),
            files=[],
            evidence=[],
            error="Unsupported deterministic TDD task.",
        )

    broken_source = """from __future__ import annotations


def add(a: int | float, b: int | float) -> int | float:
    return a - b
"""

    repaired_source = """from __future__ import annotations


def add(a: int | float, b: int | float) -> int | float:
    return a + b
"""

    tests_source = f"""from {module_name} import add


def test_addition() -> None:
    assert add(2, 3) == 5


def test_negative_numbers() -> None:
    assert add(-4, -3) == -7
"""

    target.write_text(broken_source, encoding="utf-8")
    test_target.write_text(tests_source, encoding="utf-8")

    evidence: list[CommandEvidence] = []

    red = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            test_target.name,
        ],
        cwd=workspace,
        timeout=120,
    )
    evidence.append(red)

    if red.exit_code == 0:
        return CodingResult(
            handled=True,
            ok=False,
            capability="development.python_pytest_red_green",
            summary="The deliberately broken implementation unexpectedly passed.",
            workspace=str(workspace),
            files=[target.name, test_target.name],
            evidence=evidence,
            error="Expected the initial pytest run to fail.",
        )

    target.write_text(repaired_source, encoding="utf-8")

    # The red and green implementations can have the same byte length and
    # may be written within the same filesystem timestamp interval. Remove
    # stale bytecode so the second pytest process imports the repaired source.
    pycache = workspace / "__pycache__"
    if pycache.is_dir():
        shutil.rmtree(pycache, ignore_errors=True)

    green = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            test_target.name,
        ],
        cwd=workspace,
        timeout=120,
    )
    evidence.append(green)

    if green.exit_code != 0:
        return CodingResult(
            handled=True,
            ok=False,
            capability="development.python_pytest_red_green",
            summary="The repaired implementation still failed pytest.",
            workspace=str(workspace),
            files=[target.name, test_target.name],
            evidence=evidence,
            error=green.stderr or green.stdout,
        )

    return CodingResult(
        handled=True,
        ok=True,
        capability="development.python_pytest_red_green",
        summary=(
            f"Created {target.name} and {test_target.name}; "
            "confirmed the failing red phase, repaired the implementation, "
            "and confirmed the passing green phase."
        ),
        workspace=str(workspace),
        files=[target.name, test_target.name],
        evidence=evidence,
    )


_ADAPTIVE_TDD_CAPABILITY = (
    "development."
    "python_adaptive_pytest_red_green"
)


_BLOCKED_ADAPTIVE_IMPORTS = {
    "ctypes",
    "http",
    "multiprocessing",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "urllib",
}


_BLOCKED_ADAPTIVE_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "input",
    "open",
}


def _requested_python_function(
    request: str,
) -> tuple[str, list[str]] | None:
    """Extract one explicitly requested function signature."""
    match = re.search(
        r"\bwith\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
        r"\s*\("
        r"(?P<parameters>[^()\n]{1,200})"
        r"\)",
        str(request or ""),
        flags=re.I,
    )

    if not match:
        return None

    function_name = match.group(
        "name"
    )

    parameters: list[str] = []

    for raw in match.group(
        "parameters"
    ).split(","):
        raw = raw.strip()

        if not raw:
            continue

        name = re.split(
            r"[:=]",
            raw,
            maxsplit=1,
        )[0].strip()

        if not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*",
            name,
        ):
            return None

        parameters.append(
            name
        )

    if not parameters:
        return None

    return (
        function_name,
        parameters,
    )


def _coding_json_object(
    value: str,
) -> dict[str, Any]:
    """Recover one JSON object from bounded worker output."""
    raw = str(
        value or ""
    ).strip()

    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        raw,
        flags=re.I | re.S,
    )

    if fenced:
        raw = fenced.group(
            1
        ).strip()

    start = raw.find("{")
    end = raw.rfind("}")

    if start < 0 or end <= start:
        raise ValueError(
            "Adaptive coding worker returned no JSON object"
        )

    try:
        payload = json.loads(
            raw[start:end + 1]
        )
    except json.JSONDecodeError as error:
        raise ValueError(
            "Adaptive coding worker returned invalid JSON"
        ) from error

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "Adaptive worker response must be a JSON object"
        )

    return payload


def _adaptive_source_field(
    payload: dict[str, Any],
    key: str,
) -> str:
    """Normalize weak-model source fields without trusting their shape."""
    value = payload.get(
        key
    )

    if isinstance(
        value,
        str,
    ):
        return value

    # Weak models sometimes return multiple source fragments even when
    # explicitly asked for one string. The harness safely normalizes them.
    if isinstance(
        value,
        list,
    ):
        pieces: list[str] = []

        for item in value:
            if isinstance(
                item,
                str,
            ):
                pieces.append(
                    item
                )

            elif isinstance(
                item,
                dict,
            ):
                for candidate_key in (
                    "test_code",
                    "source",
                    "code",
                ):
                    candidate = item.get(
                        candidate_key
                    )

                    if isinstance(
                        candidate,
                        str,
                    ):
                        pieces.append(
                            candidate
                        )
                        break

        if pieces:
            return "\n\n".join(
                pieces
            )

    raise ValueError(
        f"Adaptive worker field {key!r} is not usable source text"
    )


def _validate_generated_python(
    source: str,
    *,
    function_name: str,
    is_test: bool,
    module_name: str,
) -> None:
    """Statically constrain generated Python before execution."""
    value = str(
        source or ""
    )

    if not value.strip():
        raise ValueError(
            "Generated Python source is empty"
        )

    if len(value) > (
        7000
        if is_test
        else 5000
    ):
        raise ValueError(
            "Generated Python exceeds bounded size"
        )

    try:
        tree = ast.parse(
            value
        )
    except SyntaxError as error:
        raise ValueError(
            "Generated Python is syntactically invalid"
        ) from error

    blocked_attributes = {
        "Popen",
        "call",
        "connect",
        "delete",
        "get",
        "kill",
        "open",
        "post",
        "put",
        "remove",
        "rename",
        "replace",
        "rmdir",
        "run",
        "system",
        "unlink",
        "write_bytes",
        "write_text",
    }

    imported_requested_function = False
    imported_requested_module = False

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                root = alias.name.split(
                    ".",
                    1,
                )[0]

                if root in _BLOCKED_ADAPTIVE_IMPORTS:
                    raise ValueError(
                        "Generated Python imports a blocked module"
                    )

                if root == module_name:
                    imported_requested_module = True

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            root = str(
                node.module
                or ""
            ).split(
                ".",
                1,
            )[0]

            if root in _BLOCKED_ADAPTIVE_IMPORTS:
                raise ValueError(
                    "Generated Python imports a blocked module"
                )

            if root == module_name:
                imported_requested_module = True

                if any(
                    alias.name == function_name
                    for alias in node.names
                ):
                    imported_requested_function = True

        elif isinstance(
            node,
            ast.Call,
        ):
            if (
                isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                in _BLOCKED_ADAPTIVE_CALLS
            ):
                raise ValueError(
                    "Generated Python calls a blocked builtin"
                )

            if (
                isinstance(
                    node.func,
                    ast.Attribute,
                )
                and node.func.attr
                in blocked_attributes
            ):
                raise ValueError(
                    "Generated Python uses a blocked side-effect call"
                )

    if not is_test:
        functions = {
            node.name
            for node in tree.body
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
        }

        if function_name not in functions:
            raise ValueError(
                "Generated implementation does not define "
                "the requested function"
            )

        return

    tests = [
        node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name.startswith(
            "test_"
        )
    ]

    if len(tests) < 2:
        raise ValueError(
            "Adaptive TDD requires at least two pytest tests"
        )

    if not (
        imported_requested_function
        or imported_requested_module
    ):
        raise ValueError(
            "Generated tests do not import the requested module/function"
        )

    names = {
        node.id
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            ast.Name,
        )
    }

    attribute_names = {
        node.attr
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            ast.Attribute,
        )
    }

    if (
        function_name not in names
        and function_name not in attribute_names
    ):
        raise ValueError(
            "Generated tests do not exercise "
            "the requested function"
        )


def _ask_local_coding_model(
    prompt: str,
) -> str:
    """Call the dedicated Qwen2.5-Coder-7B specialist on localhost:8767."""
    import urllib.error
    import urllib.request

    endpoint = (
        os.environ.get(
            "SOPHYANE_ADAPTIVE_CODING_ENDPOINT",
            "http://127.0.0.1:8767",
        )
        .rstrip("/")
    )

    model = os.environ.get(
        "SOPHYANE_ADAPTIVE_CODING_MODEL",
        "local-evolution",
    )

    payload = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 700,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the bounded coding worker inside Sophyane. "
                    "The harness owns execution, validation, tests, retries "
                    "and success. Return only the requested JSON object. "
                    "Never claim that commands ran."
                ),
            },
            {
                "role": "user",
                "content": str(
                    prompt
                )[:6500],
            },
        ],
    }

    request = urllib.request.Request(
        (
            endpoint
            + "/v1/chat/completions"
        ),
        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),
        headers={
            "Content-Type": (
                "application/json"
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=180,
        ) as response:
            body = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise RuntimeError(
            "Adaptive Qwen2.5-Coder-7B worker unavailable: "
            f"{error}"
        ) from error

    choices = body.get(
        "choices"
    ) or []

    if not choices:
        raise RuntimeError(
            "Adaptive coding endpoint returned no choices"
        )

    text = str(
        (
            choices[0].get(
                "message"
            )
            or {}
        ).get(
            "content"
        )
        or ""
    ).strip()

    if not text:
        raise RuntimeError(
            "Adaptive coding endpoint returned empty content"
        )

    return text


def _adaptive_generation(
    *,
    request: str,
    filename: str,
    function_name: str,
    parameters: list[str],
) -> tuple[str, str]:
    """Generate one bounded RED implementation and immutable tests."""
    module_name = Path(
        filename
    ).stem

    last_error = ""

    for _attempt in range(
        3
    ):
        prompt = f"""
Create the RED phase for this Python TDD request:

{request}

Target module: {module_name}
Target function: {function_name}
Parameters: {parameters}

Return exactly ONE JSON object containing exactly two fields:

"broken_source": one Python source-code STRING
"test_source": one Python pytest source-code STRING

Hard requirements:
- both fields MUST be JSON strings, never arrays or objects;
- broken_source must define {function_name};
- broken_source must be deliberately behaviorally incorrect;
- prefer a wrong returned value rather than deliberate syntax/runtime crashes;
- test_source must import {function_name} from {module_name}, or import {module_name};
- test_source must contain at least TWO test_ functions;
- tests express the CORRECT intended behavior;
- include a meaningful edge case when appropriate;
- tests must be reusable and must not encode harness behavior;
- no filesystem, subprocess, shell, network, environment or process access;
- no Markdown;
- no explanation outside JSON;
- never claim tests were executed.

Previous rejected response reason:
{last_error[:800]}
"""

        try:
            payload = _coding_json_object(
                _ask_local_coding_model(
                    prompt
                )
            )

            broken_source = (
                _adaptive_source_field(
                    payload,
                    "broken_source",
                )
            )

            test_source = (
                _adaptive_source_field(
                    payload,
                    "test_source",
                )
            )

            _validate_generated_python(
                broken_source,
                function_name=function_name,
                is_test=False,
                module_name=module_name,
            )

            _validate_generated_python(
                test_source,
                function_name=function_name,
                is_test=True,
                module_name=module_name,
            )

            return (
                broken_source,
                test_source,
            )

        except (
            ValueError,
            RuntimeError,
        ) as error:
            last_error = str(
                error
            )

    raise ValueError(
        "Adaptive TDD worker could not produce "
        "a bounded red-phase artifact: "
        + last_error
    )


def _adaptive_repair_source(
    *,
    request: str,
    filename: str,
    function_name: str,
    current_source: str,
    test_source: str,
    failure_output: str,
    prior_error: str = "",
) -> tuple[str, str]:
    """Repair production source using real pytest failure evidence."""
    module_name = Path(
        filename
    ).stem

    prompt = f"""
Diagnose and repair ONLY the production module.

Original request:
{request}

Target module:
{module_name}

Target function:
{function_name}

CURRENT PRODUCTION SOURCE:
--- SOURCE ---
{current_source[:3500]}
--- END SOURCE ---

IMMUTABLE TEST CONTRACT:
--- TESTS ---
{test_source[:3500]}
--- END TESTS ---

OBJECTIVE PYTEST FAILURE:
--- PYTEST ---
{failure_output[-3000:]}
--- END PYTEST ---

Previous repair rejection:
{prior_error[:800]}

Return exactly ONE JSON object with exactly these STRING fields:

"diagnosis"
"source"

Requirements:
- diagnosis briefly identifies the actual defect shown by evidence;
- source is the complete repaired production module;
- do not change or weaken the tests;
- solve the general function behavior;
- preserve function name {function_name};
- no filesystem, subprocess, shell, network or environment access;
- no Markdown;
- never claim success; Sophyane will rerun pytest.
"""

    payload = _coding_json_object(
        _ask_local_coding_model(
            prompt
        )
    )

    diagnosis = str(
        payload.get(
            "diagnosis"
        )
        or ""
    ).strip()

    repaired_source = (
        _adaptive_source_field(
            payload,
            "source",
        )
    )

    if not diagnosis:
        raise ValueError(
            "Adaptive repair omitted diagnosis"
        )

    _validate_generated_python(
        repaired_source,
        function_name=function_name,
        is_test=False,
        module_name=module_name,
    )

    return (
        diagnosis,
        repaired_source,
    )


def _python_adaptive_tdd_action(
    request: str,
    match: re.Match[str],
    workspace: Path,
) -> CodingResult:
    """Evidence-driven RED -> diagnose -> repair -> GREEN loop."""
    filename = match.group(
        "filename"
    )

    requested = (
        _requested_python_function(
            request
        )
    )

    if requested is None:
        return CodingResult(
            handled=True,
            ok=False,
            capability=_ADAPTIVE_TDD_CAPABILITY,
            summary=(
                "Adaptive TDD requires an explicit "
                "requested function signature."
            ),
            workspace=str(
                workspace
            ),
            files=[],
            evidence=[],
            error=(
                "Could not extract requested function signature."
            ),
        )

    function_name, parameters = requested

    target = _safe_child(
        workspace,
        filename,
    )

    module_name = Path(
        filename
    ).stem

    test_target = _safe_child(
        workspace,
        f"test_{module_name}.py",
    )

    evidence: list[
        CommandEvidence
    ] = []

    try:
        broken_source, test_source = (
            _adaptive_generation(
                request=request,
                filename=filename,
                function_name=function_name,
                parameters=parameters,
            )
        )

    except Exception as error:
        return CodingResult(
            handled=True,
            ok=False,
            capability=_ADAPTIVE_TDD_CAPABILITY,
            summary=(
                "Adaptive TDD generation failed before execution."
            ),
            workspace=str(
                workspace
            ),
            files=[],
            evidence=evidence,
            error=str(
                error
            ),
        )

    target.write_text(
        broken_source,
        encoding="utf-8",
    )

    test_target.write_text(
        test_source,
        encoding="utf-8",
    )

    immutable_tests = (
        test_target.read_bytes()
    )

    red = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            test_target.name,
        ],
        cwd=workspace,
        timeout=120,
    )

    evidence.append(
        red
    )

    if red.exit_code == 0:
        return CodingResult(
            handled=True,
            ok=False,
            capability=_ADAPTIVE_TDD_CAPABILITY,
            summary=(
                "Adaptive TDD rejected a false RED phase."
            ),
            workspace=str(
                workspace
            ),
            files=[
                target.name,
                test_target.name,
            ],
            evidence=evidence,
            error=(
                "Deliberately defective implementation "
                "unexpectedly passed immutable tests."
            ),
        )

    failure_output = (
        red.stdout
        + "\n"
        + red.stderr
    )

    current_source = (
        broken_source
    )

    last_error = ""
    last_diagnosis = ""

    for _attempt in range(
        3
    ):
        if (
            test_target.read_bytes()
            != immutable_tests
        ):
            return CodingResult(
                handled=True,
                ok=False,
                capability=_ADAPTIVE_TDD_CAPABILITY,
                summary=(
                    "Adaptive TDD stopped because "
                    "the immutable test contract changed."
                ),
                workspace=str(
                    workspace
                ),
                files=[
                    target.name,
                    test_target.name,
                ],
                evidence=evidence,
                error=(
                    "Immutable pytest file changed."
                ),
            )

        try:
            diagnosis, repaired_source = (
                _adaptive_repair_source(
                    request=request,
                    filename=filename,
                    function_name=function_name,
                    current_source=current_source,
                    test_source=test_source,
                    failure_output=failure_output,
                    prior_error=last_error,
                )
            )

            before_ast = ast.dump(
                ast.parse(
                    current_source
                ),
                include_attributes=False,
            )

            after_ast = ast.dump(
                ast.parse(
                    repaired_source
                ),
                include_attributes=False,
            )

            if before_ast == after_ast:
                raise ValueError(
                    "Repair produced no semantic source change"
                )

            target.write_text(
                repaired_source,
                encoding="utf-8",
            )

            if (
                test_target.read_bytes()
                != immutable_tests
            ):
                raise ValueError(
                    "Immutable tests changed during repair"
                )

            pycache = (
                workspace
                / "__pycache__"
            )

            if pycache.is_dir():
                shutil.rmtree(
                    pycache,
                    ignore_errors=True,
                )

            green = _run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    test_target.name,
                ],
                cwd=workspace,
                timeout=120,
            )

            evidence.append(
                green
            )

            last_diagnosis = (
                diagnosis
            )

            if green.exit_code == 0:
                if (
                    test_target.read_bytes()
                    != immutable_tests
                ):
                    raise ValueError(
                        "Tests changed before GREEN acceptance"
                    )

                return CodingResult(
                    handled=True,
                    ok=True,
                    capability=_ADAPTIVE_TDD_CAPABILITY,
                    summary=(
                        f"Created {target.name} and "
                        f"{test_target.name}; objectively observed "
                        "RED, supplied pytest evidence to the "
                        "Qwen2.5-Coder-7B repair worker, preserved "
                        "tests unchanged, and objectively observed "
                        "GREEN. Diagnosis: "
                        f"{last_diagnosis[:300]}"
                    ),
                    workspace=str(
                        workspace
                    ),
                    files=[
                        target.name,
                        test_target.name,
                    ],
                    evidence=evidence,
                )

            current_source = (
                repaired_source
            )

            failure_output = (
                green.stdout
                + "\n"
                + green.stderr
            )

            last_error = (
                "Previous repaired source still failed pytest."
            )

        except Exception as error:
            last_error = str(
                error
            )

    return CodingResult(
        handled=True,
        ok=False,
        capability=_ADAPTIVE_TDD_CAPABILITY,
        summary=(
            "Adaptive TDD exhausted its bounded repair attempts "
            "without reaching GREEN."
        ),
        workspace=str(
            workspace
        ),
        files=[
            target.name,
            test_target.name,
        ],
        evidence=evidence,
        error=(
            last_error
            or failure_output[-2000:]
        ),
    )


def _python_function_pytest_spec(
    *,
    filename: str,
    request: str,
) -> dict[str, str] | None:
    """Extract one bounded arithmetic function plus its requested pytest."""
    function_match = re.search(
        r"\bwith\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
        r"\s*\(\s*"
        r"(?P<first>[A-Za-z_][A-Za-z0-9_]*)"
        r"\s*,\s*"
        r"(?P<second>[A-Za-z_][A-Za-z0-9_]*)"
        r"\s*\)",
        request,
        flags=re.I,
    )

    if not function_match:
        return None

    function_name = function_match.group("name")
    first_parameter = function_match.group("first")
    second_parameter = function_match.group("second")

    escaped_name = re.escape(
        function_name
    )

    assertion_match = re.search(
        rf"\b{escaped_name}\s*\(\s*"
        r"(?P<first>-?\d+(?:\.\d+)?)"
        r"\s*,\s*"
        r"(?P<second>-?\d+(?:\.\d+)?)"
        r"\s*\)\s*"
        r"(?:equals|equal\s+to|==)\s*"
        r"(?P<expected>-?\d+(?:\.\d+)?)",
        request,
        flags=re.I,
    )

    if not assertion_match:
        return None

    operators = {
        "add": "+",
        "sum": "+",
        "multiply": "*",
        "product": "*",
        "subtract": "-",
        "difference": "-",
        "divide": "/",
        "quotient": "/",
    }

    operation = operators.get(
        function_name.casefold()
    )

    if operation is None:
        return None

    module_name = Path(
        filename
    ).stem

    test_filename = (
        f"test_{module_name}.py"
    )

    implementation = (
        "from __future__ import annotations\n"
        "\n"
        "\n"
        f"def {function_name}("
        f"{first_parameter}: int | float, "
        f"{second_parameter}: int | float"
        ") -> int | float:\n"
        f"    return {first_parameter} "
        f"{operation} {second_parameter}\n"
    )

    test_source = (
        f"from {module_name} import {function_name}\n"
        "\n"
        "\n"
        f"def test_{function_name}() -> None:\n"
        f"    assert {function_name}("
        f"{assertion_match.group('first')}, "
        f"{assertion_match.group('second')}"
        f") == {assertion_match.group('expected')}\n"
    )

    return {
        "function_name": function_name,
        "implementation": implementation,
        "test_filename": test_filename,
        "test_source": test_source,
    }


def _python_action(
    request: str,
    match: re.Match[str],
    workspace: Path,
) -> CodingResult:
    filename = match.group("filename")
    target = _safe_child(workspace, filename)

    pytest_spec = (
        _python_function_pytest_spec(
            filename=filename,
            request=request,
        )
        if _TDD_CUES.search(request)
        else None
    )

    test_target: Path | None = None

    if pytest_spec is not None:
        target.write_text(
            pytest_spec["implementation"],
            encoding="utf-8",
        )

        test_target = _safe_child(
            workspace,
            pytest_spec[
                "test_filename"
            ],
        )

        test_target.write_text(
            pytest_spec["test_source"],
            encoding="utf-8",
        )

    else:
        target.write_text(
            _default_python(
                filename,
                request,
            ),
            encoding="utf-8",
        )

    evidence: list[CommandEvidence] = []

    syntax_result = _run(
        [sys.executable, "-m", "py_compile", target.name],
        cwd=workspace,
        timeout=60,
    )
    evidence.append(syntax_result)

    if syntax_result.exit_code != 0:
        return CodingResult(
            handled=True,
            ok=False,
            capability="development.python_create_validate",
            summary=f"Created {target.name}, but syntax validation failed.",
            workspace=str(workspace),
            files=[target.name],
            evidence=evidence,
            error=syntax_result.stderr or syntax_result.stdout,
        )

    if test_target is not None:
        pytest_result = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                test_target.name,
            ],
            cwd=workspace,
            timeout=120,
        )
        evidence.append(
            pytest_result
        )

        files = [
            target.name,
            test_target.name,
        ]

        if pytest_result.exit_code != 0:
            return CodingResult(
                handled=True,
                ok=False,
                capability=(
                    "development."
                    "python_create_validate_pytest"
                ),
                summary=(
                    f"Created {target.name} and "
                    f"{test_target.name}, but pytest failed."
                ),
                workspace=str(workspace),
                files=files,
                evidence=evidence,
                error=(
                    pytest_result.stderr
                    or pytest_result.stdout
                ),
            )

        return CodingResult(
            handled=True,
            ok=True,
            capability=(
                "development."
                "python_create_validate_pytest"
            ),
            summary=(
                f"Created {target.name} and "
                f"{test_target.name}; pytest passed."
            ),
            workspace=str(workspace),
            files=files,
            evidence=evidence,
        )

    if re.search(
        r"\b(?:run|execute)\b",
        request,
        re.I,
    ):
        run_result = _run(
            [
                sys.executable,
                target.name,
            ],
            cwd=workspace,
            timeout=60,
        )
        evidence.append(
            run_result
        )

        if run_result.exit_code != 0:
            return CodingResult(
                handled=True,
                ok=False,
                capability=(
                    "development."
                    "python_create_validate_run"
                ),
                summary=(
                    f"Validated {target.name}, "
                    "but execution failed."
                ),
                workspace=str(workspace),
                files=[target.name],
                evidence=evidence,
                error=(
                    run_result.stderr
                    or run_result.stdout
                ),
            )

        capability = (
            "development."
            "python_create_validate_run"
        )
        summary = (
            f"Created, validated and executed "
            f"{target.name}."
        )

    else:
        capability = (
            "development."
            "python_create_validate"
        )
        summary = (
            f"Created and syntax-validated "
            f"{target.name}."
        )

    return CodingResult(
        handled=True,
        ok=True,
        capability=capability,
        summary=summary,
        workspace=str(workspace),
        files=[target.name],
        evidence=evidence,
    )


def try_coding_request(
    request: str,
    *,
    workspace: str | Path | None = None,
) -> CodingResult | None:
    text = " ".join(str(request or "").strip().split())

    if not text or _EXPLANATION_CUES.search(text):
        return None

    root = _workspace(workspace)

    cpp = _CPP_REQUEST.search(text)
    if cpp:
        return _cpp_action(text, cpp, root)

    python = _PY_REQUEST.search(text)
    if python:
        if (
            _TDD_CUES.search(text)
            and _REPAIR_CUES.search(text)
        ):
            result = _python_tdd_action(
                text,
                python,
                root,
            )

            if result.handled:
                return result

            # Do not degrade an explicit red/green repair contract into
            # generic create/compile/run success. The adaptive harness owns
            # failure observation, repair and final evidence.
            return _python_adaptive_tdd_action(
                text,
                python,
                root,
            )

        return _python_action(
            text,
            python,
            root,
        )

    return None


__all__ = [
    "CodingResult",
    "CommandEvidence",
    "try_coding_request",
]
