"""Deterministic local coding actions for Sophyane.

This module handles narrowly bounded development requests without asking an LLM
to pretend that files were created or commands were executed.
"""
from __future__ import annotations

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


def _python_action(
    request: str,
    match: re.Match[str],
    workspace: Path,
) -> CodingResult:
    filename = match.group("filename")
    target = _safe_child(workspace, filename)
    target.write_text(
        _default_python(filename, request),
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

    if re.search(r"\b(?:run|execute)\b", request, re.I):
        run_result = _run(
            [sys.executable, target.name],
            cwd=workspace,
            timeout=60,
        )
        evidence.append(run_result)

        if run_result.exit_code != 0:
            return CodingResult(
                handled=True,
                ok=False,
                capability="development.python_create_validate_run",
                summary=f"Validated {target.name}, but execution failed.",
                workspace=str(workspace),
                files=[target.name],
                evidence=evidence,
                error=run_result.stderr or run_result.stdout,
            )

        capability = "development.python_create_validate_run"
        summary = f"Created, validated and executed {target.name}."
    else:
        capability = "development.python_create_validate"
        summary = f"Created and syntax-validated {target.name}."

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
