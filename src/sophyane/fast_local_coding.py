"""Low-latency bounded coding path for small local models.

This module deliberately does not replace the autonomous coding runtime.
It handles only narrow single-Python-file tasks with existing pytest evidence:

    model candidate
        -> syntax validation
        -> isolated write
        -> targeted pytest
        -> optional one compact repair
        -> success or decline/fallback

No planner JSON or LLM verifier is used here.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


Backend = Callable[[str, str], str]


@dataclass
class FastCodingResult:
    attempted: bool
    success: bool
    path: str = ""
    model_calls: int = 0
    elapsed_seconds: float = 0.0
    passed: int = 0
    failed: int = 0
    total: int = 0
    test_output: str = ""
    reason: str = ""
    call_seconds: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "success": self.success,
            "path": self.path,
            "model_calls": self.model_calls,
            "elapsed_seconds": self.elapsed_seconds,
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "test_output": self.test_output,
            "reason": self.reason,
            "call_seconds": list(self.call_seconds),
        }


_PATH_RE = re.compile(
    r"(?<![\w./-])"
    r"((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.py)"
    r"(?![\w/-]|[.][A-Za-z0-9_-])"
)


def _explicit_python_paths(prompt: str) -> list[str]:
    result: list[str] = []

    for value in _PATH_RE.findall(prompt or ""):
        normalized = value.replace("\\", "/").strip()

        if (
            not normalized
            or normalized.startswith("/")
            or normalized.startswith("../")
            or "/../" in normalized
            or normalized in result
        ):
            continue

        result.append(normalized)

    return result



def _is_explicitly_incomplete_definition(
    node: ast.AST,
) -> bool:
    if not isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        ),
    ):
        return False

    body = list(
        getattr(
            node,
            "body",
            [],
        )
        or []
    )

    if (
        len(body) == 1
        and isinstance(
            body[0],
            ast.Pass,
        )
    ):
        return True

    for child in ast.walk(node):
        if not isinstance(
            child,
            ast.Raise,
        ):
            continue

        exc = child.exc

        if isinstance(
            exc,
            ast.Name,
        ):
            name = exc.id

        elif (
            isinstance(
                exc,
                ast.Call,
            )
            and isinstance(
                exc.func,
                ast.Name,
            )
        ):
            name = exc.func.id

        else:
            name = ""

        if name == "NotImplementedError":
            return True

    return False


def _request_symbol_names(
    request: str,
) -> set[str]:
    text = str(
        request
        or ""
    )

    names: set[str] = set()

    patterns = (
        r"\b(?:implement|fix|repair|complete|update)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\b(?:class)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)\b",
    )

    for pattern in patterns:
        for value in re.findall(
            pattern,
            text,
            flags=re.I,
        ):
            names.add(
                str(value)
            )

    return names


def _structural_stub_targets(
    root: Path,
) -> list[tuple[str, tuple[str, ...]]]:
    excluded_parts = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "build",
        "dist",
    }

    targets: list[
        tuple[
            str,
            tuple[str, ...],
        ]
    ] = []

    for candidate in sorted(
        root.rglob("*.py")
    ):
        try:
            relative = candidate.relative_to(
                root
            )
        except ValueError:
            continue

        if not candidate.is_file():
            continue

        if candidate.name.startswith(
            "test_"
        ):
            continue

        if any(
            part in excluded_parts
            or part.startswith(".")
            for part in relative.parts[:-1]
        ):
            continue

        try:
            source = candidate.read_text(
                encoding="utf-8"
            )
            tree = ast.parse(
                source,
                filename=str(
                    relative
                ),
            )
        except (
            OSError,
            UnicodeError,
            SyntaxError,
        ):
            continue

        definitions: list[str] = []

        for node in tree.body:
            if (
                isinstance(
                    node,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                        ast.ClassDef,
                    ),
                )
                and _is_explicitly_incomplete_definition(
                    node
                )
            ):
                definitions.append(
                    node.name
                )

        if definitions:
            targets.append(
                (
                    relative.as_posix(),
                    tuple(
                        definitions
                    ),
                )
            )

    return targets


def _resolve_fast_python_target(
    *,
    root: Path,
    request: str,
    explicit_paths: list[str],
) -> tuple[str | None, str]:
    existing_explicit: list[str] = []

    for relative_path in explicit_paths:
        candidate = (
            root
            / relative_path
        ).resolve()

        try:
            candidate.relative_to(
                root
            )
        except ValueError:
            continue

        if candidate.is_file():
            existing_explicit.append(
                relative_path
            )

    structural = (
        _structural_stub_targets(
            root
        )
    )

    structural_by_path = {
        path: definitions
        for path, definitions in structural
    }

    explicit_incomplete = [
        path
        for path in existing_explicit
        if path in structural_by_path
    ]

    requested_symbols = (
        _request_symbol_names(
            request
        )
    )

    symbol_matches = [
        path
        for path, definitions in structural
        if requested_symbols.intersection(
            definitions
        )
    ]

    # Multiple explicit Python paths are ambiguous unless the
    # request itself names exactly one incomplete implementation
    # symbol.  Structural incompleteness alone must not turn a
    # generic multi-file update into an implicit edit.
    if len(explicit_paths) > 1:
        explicit_symbol_matches = [
            path
            for path in symbol_matches
            if path in existing_explicit
        ]

        if len(explicit_symbol_matches) == 1:
            return (
                explicit_symbol_matches[0],
                "unique requested-symbol structural stub",
            )

        return (
            None,
            "fast path requires exactly one explicit Python target",
        )

    # With zero or one explicit path, a uniquely requested symbol
    # is strong authority for the incomplete implementation target.
    if len(symbol_matches) == 1:
        return (
            symbol_matches[0],
            "unique requested-symbol structural stub",
        )

    # A single explicitly mentioned incomplete file is also safe.
    if len(explicit_incomplete) == 1:
        return (
            explicit_incomplete[0],
            "unique explicitly mentioned structural stub",
        )

    # Preserve historical behavior for the normal one-path case.
    if len(explicit_paths) == 1:
        return (
            explicit_paths[0],
            "single explicit Python target",
        )

    # Structural-only resolution is allowed only when the request
    # actually names a callable/class symbol.  This prevents
    # unrelated requests such as "Inspect sample.py.bak" from
    # opportunistically selecting an arbitrary workspace stub.
    if (
        requested_symbols
        and len(structural) == 1
    ):
        return (
            structural[0][0],
            "unique workspace structural stub",
        )

    return (
        None,
        (
            "fast path could not resolve one safe Python target; "
            f"explicit={len(explicit_paths)} "
            f"structural={len(structural)}"
        ),
    )


def _extract_source(text: str) -> str:
    raw = str(text or "").strip()

    fence = re.search(
        r"```(?:python|py)?\s*\n(.*?)```",
        raw,
        flags=re.I | re.S,
    )

    if fence:
        raw = fence.group(1).strip()

    markers = [
        raw.find('"""'),
        raw.find("from "),
        raw.find("import "),
        raw.find("def "),
        raw.find("class "),
    ]
    markers = [item for item in markers if item >= 0]

    if markers:
        raw = raw[min(markers):].strip()

    if not raw:
        raise ValueError("local model returned empty source")

    compile(raw, "<fast-local-candidate>", "exec")

    return raw.rstrip() + "\n"


def _pytest_files(root: Path) -> list[Path]:
    files = sorted(
        item
        for item in root.rglob("test_*.py")
        if (
            item.is_file()
            and ".venv" not in item.parts
            and "__pycache__" not in item.parts
        )
    )

    # Tier-1 is deliberately bounded.
    if len(files) > 12:
        return []

    return files


def _score_pytest(
    root: Path,
    test_files: list[Path],
    *,
    timeout: int = 20,
) -> dict[str, Any]:
    relative = [
        str(item.relative_to(root))
        for item in test_files
    ]

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *relative,
        ],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )

    output = proc.stdout or ""

    passed = 0
    failed = 0

    match = re.search(
        r"(\d+)\s+passed",
        output,
    )
    if match:
        passed = int(match.group(1))

    match = re.search(
        r"(\d+)\s+failed",
        output,
    )
    if match:
        failed = int(match.group(1))

    total = passed + failed

    return {
        "returncode": proc.returncode,
        "passed": passed,
        "failed": failed,
        "total": total,
        "output": output[-5000:],
    }


def _candidate_prompt(
    request: str,
    relative_path: str,
    current_source: str,
    tests_text: str,
) -> str:
    return f"""You are the bounded coding worker inside Sophyane.

Implement the requested change directly.

USER REQUEST:
{request}

TARGET FILE:
{relative_path}

CURRENT COMPLETE FILE:
{current_source}

RELEVANT TESTS:
{tests_text}

Before returning source, perform a literal contract audit.

CONTRACT AUDIT RULES:
- Every explicit USER REQUEST requirement is mandatory.
- Treat phrases such as "convert", "accept any iterable", "only when",
  "must propagate", "exactly one", "raise", "preserve order", and
  "do not" as behavioral invariants, not suggestions.
- Check every bullet independently against the source you are returning.
- Do not replace a requested conversion with an isinstance restriction.
- Do not swallow an exception when the request says conversion/errors
  must propagate.
- Do not use len(), indexing, or slicing on an input that the request
  says may be any iterable unless you first materialize it exactly once.
- Do not recurse when the request explicitly bounds behavior to exactly
  one nesting level.
- A passing subset of tests does not override an unmet request clause.
- Prefer the smallest implementation that satisfies all stated clauses.

Return ONLY the complete final contents of {relative_path}.
No JSON.
No markdown.
No diff.
No explanation.
Do not modify tests.
"""


def _repair_prompt(
    request: str,
    relative_path: str,
    current_source: str,
    failure: str,
) -> str:
    return f"""You are repairing one already-tested Python file.

USER REQUEST:
{request}

TARGET FILE:
{relative_path}

CURRENT COMPLETE FILE:
{current_source}

OBJECTIVE PYTEST FAILURE EVIDENCE:
{failure[-3200:]}

Repair the CURRENT file directly.

Use the pytest evidence literally, but repair against the USER REQUEST
rather than merely editing around the observed example.

MANDATORY REPAIR PROCEDURE:
1. Identify the exact failed behavior from pytest.
   Compare each reported actual value with the expected value.
2. Identify which explicit USER REQUEST clause governs that behavior.
3. Compare the CURRENT source against that clause.
4. Change the source so the clause itself is satisfied generally.
5. Re-audit every other explicit request clause before returning.

Contract rules:
- Every explicit requirement is mandatory.
- Preserve behavior for tests that already pass.
- Preserve that behavior only when it is also consistent with the user
  request.
- A conversion requirement means perform that conversion; do not replace
  it with a type restriction.
- If errors are required to propagate, do not catch and convert them to
  a fallback result.
- If an argument may be any iterable, do not assume len(), indexing,
  slicing, truthiness, or repeatable iteration unless the implementation
  safely materializes it once.
- If behavior is explicitly limited to one level, do not recurse.
- If a negative or otherwise invalid value must raise, implement that
  condition explicitly rather than relying on unrelated validation.
- Do not special-case test names or literal test inputs.
- Do not special-case expected values.
- Include every import required by the returned source.
- Return the smallest complete implementation satisfying the whole contract.

Return ONLY the complete corrected contents of {relative_path}.
No JSON.
No markdown.
No diff.
No explanation.
Do not modify tests.
"""


_SYSTEM = """You are Sophyane's bounded local coding worker.
Return only complete Python source for the requested file.
The harness owns writes, execution, tests, retries, and success.
Never claim commands were executed.
"""


def _normalized_request_text(request: str) -> str:
    return " ".join(
        str(request or "").casefold().split()
    )


def _contains_any_marker(
    text: str,
    markers: tuple[str, ...],
) -> bool:
    return any(
        marker in text
        for marker in markers
    )


def _request_requires_arbitrary_string_conversion(
    request: str,
) -> bool:
    request_text = _normalized_request_text(
        request
    )

    arbitrary_markers = (
        "accept any value",
        "accept arbitrary",
        "any value",
        "non-string",
        "non string",
    )

    conversion_markers = (
        "convert it to string",
        "convert to string",
        "convert it with str(",
        "using str(",
        "str(value)",
    )

    return (
        _contains_any_marker(
            request_text,
            arbitrary_markers,
        )
        and _contains_any_marker(
            request_text,
            conversion_markers,
        )
    )


def _failure_proves_anonymous_contradiction(
    failure: str,
) -> bool:
    failure_text = str(
        failure or ""
    ).casefold()

    return (
        "assert 'anonymous' =="
        in failure_text
    )


def _first_top_level_function(
    tree: ast.Module,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            return node

    return None


def _is_name(
    node: ast.AST,
    value: str,
) -> bool:
    return (
        isinstance(node, ast.Name)
        and node.id == value
    )


def _is_anonymous_return(
    statement: ast.stmt,
) -> bool:
    return (
        isinstance(statement, ast.Return)
        and isinstance(
            statement.value,
            ast.Constant,
        )
        and statement.value.value
        == "anonymous"
    )


def _is_nonstring_anonymous_guard(
    statement: ast.stmt,
    *,
    arg_name: str,
) -> bool:
    if not isinstance(
        statement,
        ast.If,
    ):
        return False

    if statement.orelse:
        return False

    if len(statement.body) != 1:
        return False

    if not _is_anonymous_return(
        statement.body[0]
    ):
        return False

    test = statement.test

    if not (
        isinstance(test, ast.UnaryOp)
        and isinstance(
            test.op,
            ast.Not,
        )
    ):
        return False

    call = test.operand

    if not (
        isinstance(call, ast.Call)
        and _is_name(
            call.func,
            "isinstance",
        )
        and len(call.args) == 2
    ):
        return False

    return (
        _is_name(
            call.args[0],
            arg_name,
        )
        and _is_name(
            call.args[1],
            "str",
        )
    )


def _find_nonstring_anonymous_guard(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    arg_name: str,
) -> ast.If | None:
    for statement in function.body[:4]:
        if _is_nonstring_anonymous_guard(
            statement,
            arg_name=arg_name,
        ):
            return statement

    return None


def _delete_statement(
    source: str,
    statement: ast.stmt,
) -> str:
    lines = source.splitlines()

    del lines[
        statement.lineno - 1:
        statement.end_lineno
    ]

    return (
        "\n".join(lines).rstrip()
        + "\n"
    )


def _parse_module(
    source: str,
) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _function_calls_str_on_argument(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    arg_name: str,
) -> bool:
    for node in ast.walk(function):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if not _is_name(
            node.func,
            "str",
        ):
            continue

        if len(node.args) != 1:
            continue

        if _is_name(
            node.args[0],
            arg_name,
        ):
            return True

    return False


def _function_docstring_end_line(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> int | None:
    if not function.body:
        return None

    first = function.body[0]

    if not isinstance(
        first,
        ast.Expr,
    ):
        return None

    if not isinstance(
        first.value,
        ast.Constant,
    ):
        return None

    if not isinstance(
        first.value.value,
        str,
    ):
        return None

    return first.end_lineno


def _insert_string_conversion(
    source: str,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    arg_name: str,
) -> str:
    lines = source.splitlines()

    docstring_end = (
        _function_docstring_end_line(
            function
        )
    )

    if docstring_end is not None:
        insert_at = docstring_end
    elif function.body:
        insert_at = (
            function.body[0].lineno
            - 1
        )
    else:
        insert_at = function.lineno

    indent = " " * (
        function.col_offset + 4
    )

    lines.insert(
        insert_at,
        (
            f"{indent}"
            f"{arg_name} = str({arg_name})"
        ),
    )

    return (
        "\n".join(lines).rstrip()
        + "\n"
    )


def _ensure_argument_string_conversion(
    source: str,
    *,
    arg_name: str,
) -> str | None:
    tree = _parse_module(source)

    if tree is None:
        return None

    function = _first_top_level_function(
        tree
    )

    if function is None:
        return None

    if _function_calls_str_on_argument(
        function,
        arg_name=arg_name,
    ):
        return source

    candidate = _insert_string_conversion(
        source,
        function,
        arg_name=arg_name,
    )

    if _parse_module(candidate) is None:
        return None

    return candidate


def _repair_explicit_string_conversion_contradiction(
    *,
    request: str,
    source: str,
    failure: str,
) -> str | None:
    """Repair one mechanically proven string-conversion contradiction."""

    if not _request_requires_arbitrary_string_conversion(
        request
    ):
        return None

    if not _failure_proves_anonymous_contradiction(
        failure
    ):
        return None

    tree = _parse_module(source)

    if tree is None:
        return None

    function = _first_top_level_function(
        tree
    )

    if (
        function is None
        or not function.args.args
    ):
        return None

    arg_name = (
        function.args.args[0].arg
    )

    guard = _find_nonstring_anonymous_guard(
        function,
        arg_name=arg_name,
    )

    if guard is None:
        return None

    candidate = _delete_statement(
        source,
        guard,
    )

    candidate = (
        _ensure_argument_string_conversion(
            candidate,
            arg_name=arg_name,
        )
    )

    if candidate is None:
        return None

    try:
        compile(
            candidate,
            "<fast-local-deterministic-repair>",
            "exec",
        )
    except SyntaxError:
        return None

    return candidate



def _request_requires_normal_equality_for_unhashables(
    request: str,
) -> bool:
    text = _normalized_request_text(
        request
    )

    equality_markers = (
        "normal python equality",
        "python equality",
        "equality semantics",
        "normal equality",
    )

    unhashable_markers = (
        "unhashable",
        "hashable and unhashable",
        "both hashable and unhashable",
    )

    return (
        _contains_any_marker(
            text,
            equality_markers,
        )
        and _contains_any_marker(
            text,
            unhashable_markers,
        )
    )


def _failure_proves_unhashable_set_conflict(
    failure: str,
) -> bool:
    text = str(
        failure or ""
    ).casefold()

    return (
        "typeerror"
        in text
        and "unhashable type"
        in text
    )


def _function_uses_set_membership(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    has_set_constructor = False
    has_membership = False

    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and _is_name(
                node.func,
                "set",
            )
        ):
            has_set_constructor = True

        if (
            isinstance(node, ast.Compare)
            and any(
                isinstance(
                    operator,
                    (
                        ast.In,
                        ast.NotIn,
                    ),
                )
                for operator in node.ops
            )
        ):
            has_membership = True

    return (
        has_set_constructor
        and has_membership
    )


def _single_name_assignment(
    statement: ast.stmt,
) -> tuple[str, ast.expr] | None:
    if not isinstance(
        statement,
        ast.Assign,
    ):
        return None

    if len(statement.targets) != 1:
        return None

    target = statement.targets[0]

    if not isinstance(
        target,
        ast.Name,
    ):
        return None

    return (
        target.id,
        statement.value,
    )


def _empty_set_assignment_name(
    statement: ast.stmt,
) -> str | None:
    parsed = _single_name_assignment(
        statement
    )

    if parsed is None:
        return None

    name, value = parsed

    if not isinstance(
        value,
        ast.Call,
    ):
        return None

    if not _is_name(
        value.func,
        "set",
    ):
        return None

    if value.args or value.keywords:
        return None

    return name


def _empty_list_assignment_name(
    statement: ast.stmt,
) -> str | None:
    parsed = _single_name_assignment(
        statement
    )

    if parsed is None:
        return None

    name, value = parsed

    if not isinstance(
        value,
        ast.List,
    ):
        return None

    if value.elts:
        return None

    return name


def _returned_name(
    statement: ast.stmt,
) -> str | None:
    if not isinstance(
        statement,
        ast.Return,
    ):
        return None

    if not isinstance(
        statement.value,
        ast.Name,
    ):
        return None

    return statement.value.id


def _for_loop_item_name(
    statement: ast.stmt,
) -> str | None:
    if not isinstance(
        statement,
        ast.For,
    ):
        return None

    if not isinstance(
        statement.target,
        ast.Name,
    ):
        return None

    return statement.target.id


def _single_if_in_loop(
    loop: ast.For,
) -> ast.If | None:
    if len(loop.body) != 1:
        return None

    statement = loop.body[0]

    if not isinstance(
        statement,
        ast.If,
    ):
        return None

    if statement.orelse:
        return None

    return statement


def _is_not_in_compare(
    node: ast.AST,
    *,
    left_name: str,
    container_name: str,
) -> bool:
    if not isinstance(
        node,
        ast.Compare,
    ):
        return False

    if len(node.ops) != 1:
        return False

    if not isinstance(
        node.ops[0],
        ast.NotIn,
    ):
        return False

    if len(node.comparators) != 1:
        return False

    return (
        _is_name(
            node.left,
            left_name,
        )
        and _is_name(
            node.comparators[0],
            container_name,
        )
    )


def _expression_call(
    statement: ast.stmt,
) -> ast.Call | None:
    if not isinstance(
        statement,
        ast.Expr,
    ):
        return None

    if not isinstance(
        statement.value,
        ast.Call,
    ):
        return None

    return statement.value


def _is_method_call_with_name_arg(
    call: ast.Call,
    *,
    object_name: str,
    method_name: str,
    argument_name: str,
) -> bool:
    function = call.func

    if not isinstance(
        function,
        ast.Attribute,
    ):
        return False

    if function.attr != method_name:
        return False

    if not _is_name(
        function.value,
        object_name,
    ):
        return False

    if len(call.args) != 1:
        return False

    if call.keywords:
        return False

    return _is_name(
        call.args[0],
        argument_name,
    )


def _unique_condition_has_expected_actions(
    condition: ast.If,
    *,
    seen_name: str,
    result_name: str,
    item_name: str,
) -> bool:
    if len(condition.body) != 2:
        return False

    calls = [
        _expression_call(
            statement
        )
        for statement in condition.body
    ]

    if any(
        call is None
        for call in calls
    ):
        return False

    concrete_calls = [
        call
        for call in calls
        if call is not None
    ]

    has_seen_add = any(
        _is_method_call_with_name_arg(
            call,
            object_name=seen_name,
            method_name="add",
            argument_name=item_name,
        )
        for call in concrete_calls
    )

    has_result_append = any(
        _is_method_call_with_name_arg(
            call,
            object_name=result_name,
            method_name="append",
            argument_name=item_name,
        )
        for call in concrete_calls
    )

    return (
        has_seen_add
        and has_result_append
    )


def _collect_unique_loop_parts(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[
    str | None,
    str | None,
    ast.For | None,
    str | None,
]:
    seen_name = None
    result_name = None
    loop = None
    returned_name = None

    for statement in function.body:
        value = _empty_set_assignment_name(
            statement
        )

        if value is not None:
            seen_name = value
            continue

        value = _empty_list_assignment_name(
            statement
        )

        if value is not None:
            result_name = value
            continue

        if isinstance(
            statement,
            ast.For,
        ):
            loop = statement
            continue

        value = _returned_name(
            statement
        )

        if value is not None:
            returned_name = value

    return (
        seen_name,
        result_name,
        loop,
        returned_name,
    )


def _simple_unique_loop_shape(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, str] | None:
    """Recognize a narrow order-preserving set-backed dedupe loop."""

    (
        seen_name,
        result_name,
        loop,
        returned_name,
    ) = _collect_unique_loop_parts(
        function
    )

    if (
        seen_name is None
        or result_name is None
        or loop is None
        or returned_name != result_name
    ):
        return None

    item_name = _for_loop_item_name(
        loop
    )

    if item_name is None:
        return None

    condition = _single_if_in_loop(
        loop
    )

    if condition is None:
        return None

    if not _is_not_in_compare(
        condition.test,
        left_name=item_name,
        container_name=seen_name,
    ):
        return None

    if not _unique_condition_has_expected_actions(
        condition,
        seen_name=seen_name,
        result_name=result_name,
        item_name=item_name,
    ):
        return None

    return (
        item_name,
        result_name,
    )


def _rewrite_set_dedupe_to_equality_scan(
    source: str,
) -> str | None:
    tree = _parse_module(
        source
    )

    if tree is None:
        return None

    function = _first_top_level_function(
        tree
    )

    if function is None:
        return None

    if not _function_uses_set_membership(
        function
    ):
        return None

    names = _simple_unique_loop_shape(
        function
    )

    if names is None:
        return None

    item_name, result_name = names

    if not function.args.args:
        return None

    values_name = (
        function.args.args[0].arg
    )

    indent = " " * (
        function.col_offset + 4
    )

    replacement = [
        (
            f"{indent}"
            f"{result_name} = []"
        ),
        (
            f"{indent}"
            f"for {item_name} in {values_name}:"
        ),
        (
            f"{indent}    "
            f"if not any("
            f"{item_name} == existing "
            f"for existing in {result_name}"
            f"):"
        ),
        (
            f"{indent}        "
            f"{result_name}.append({item_name})"
        ),
        (
            f"{indent}"
            f"return {result_name}"
        ),
    ]

    lines = source.splitlines()

    start = (
        function.body[0].lineno
        - 1
    )

    end = (
        function.body[-1].end_lineno
    )

    lines[
        start:end
    ] = replacement

    candidate = (
        "\n".join(lines).rstrip()
        + "\n"
    )

    if _parse_module(
        candidate
    ) is None:
        return None

    return candidate


def _repair_unhashable_equality_contradiction(
    *,
    request: str,
    source: str,
    failure: str,
) -> str | None:
    """Repair a mechanically proven set-vs-equality contradiction."""

    if not _request_requires_normal_equality_for_unhashables(
        request
    ):
        return None

    if not _failure_proves_unhashable_set_conflict(
        failure
    ):
        return None

    return _rewrite_set_dedupe_to_equality_scan(
        source
    )


def _request_requires_any_iterable(
    request: str,
) -> bool:
    text = _normalized_request_text(
        request
    )

    return _contains_any_marker(
        text,
        (
            "accept any iterable",
            "any iterable",
            "arbitrary iterable",
            "iterable input",
        ),
    )


def _failure_proves_iterable_shape_conflict(
    failure: str,
) -> bool:
    text = str(
        failure or ""
    ).casefold()

    if "typeerror" not in text:
        return False

    iterable_markers = (
        "generator",
        "iterator",
        "iterable",
    )

    shape_markers = (
        "has no len()",
        "has no len",
        "not subscriptable",
        "does not support indexing",
    )

    return (
        _contains_any_marker(
            text,
            iterable_markers,
        )
        and _contains_any_marker(
            text,
            shape_markers,
        )
    )


def _function_calls_constructor_on_name(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    constructor: str,
    name: str,
) -> bool:
    for node in ast.walk(
        function
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if not _is_name(
            node.func,
            constructor,
        ):
            continue

        if (
            len(node.args) == 1
            and not node.keywords
            and _is_name(
                node.args[0],
                name,
            )
        ):
            return True

    return False


def _function_requires_sequence_shape(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
) -> bool:
    for node in ast.walk(
        function
    ):
        if (
            isinstance(
                node,
                ast.Call,
            )
            and _is_name(
                node.func,
                "len",
            )
            and len(node.args) == 1
            and _is_name(
                node.args[0],
                name,
            )
        ):
            return True

        if (
            isinstance(
                node,
                ast.Subscript,
            )
            and _is_name(
                node.value,
                name,
            )
        ):
            return True

    return False


def _insert_function_prefix_statement(
    source: str,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    statement: str,
) -> str:
    lines = source.splitlines()

    docstring_end = (
        _function_docstring_end_line(
            function
        )
    )

    if docstring_end is not None:
        insert_at = docstring_end
    elif function.body:
        insert_at = (
            function.body[0].lineno
            - 1
        )
    else:
        insert_at = function.lineno

    indent = " " * (
        function.col_offset + 4
    )

    lines.insert(
        insert_at,
        indent + statement,
    )

    return (
        "\n".join(lines).rstrip()
        + "\n"
    )


def _repair_any_iterable_materialization(
    *,
    request: str,
    source: str,
    failure: str,
) -> str | None:
    if not _request_requires_any_iterable(
        request
    ):
        return None

    if not _failure_proves_iterable_shape_conflict(
        failure
    ):
        return None

    tree = _parse_module(
        source
    )

    if tree is None:
        return None

    function = _first_top_level_function(
        tree
    )

    if (
        function is None
        or not function.args.args
    ):
        return None

    argument = (
        function.args.args[0].arg
    )

    if _function_calls_constructor_on_name(
        function,
        constructor="list",
        name=argument,
    ):
        return None

    if not _function_requires_sequence_shape(
        function,
        name=argument,
    ):
        return None

    candidate = (
        _insert_function_prefix_statement(
            source,
            function,
            f"{argument} = list({argument})",
        )
    )

    if _parse_module(
        candidate
    ) is None:
        return None

    return candidate


def _requested_int_contract_names(
    request: str,
) -> tuple[str, ...]:
    names: list[str] = []

    patterns = (
        r"\bconvert\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"\s+to\s+int\b",
        r"\bconvert\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"\s+with\s+int\b",
    )

    for pattern in patterns:
        for value in re.findall(
            pattern,
            str(request or ""),
            flags=re.I,
        ):
            normalized = str(
                value
            )

            if normalized not in names:
                names.append(
                    normalized
                )

    return tuple(
        names
    )


def _function_bound_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    result = {
        argument.arg
        for argument in (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
        )
    }

    if function.args.vararg is not None:
        result.add(
            function.args.vararg.arg
        )

    if function.args.kwarg is not None:
        result.add(
            function.args.kwarg.arg
        )

    for node in ast.walk(
        function
    ):
        if (
            isinstance(
                node,
                ast.Name,
            )
            and isinstance(
                node.ctx,
                ast.Store,
            )
        ):
            result.add(
                node.id
            )

    return result


def _resolve_contract_local_name(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    contract_name: str,
) -> str | None:
    names = _function_bound_names(
        function
    )

    if contract_name in names:
        return contract_name

    folded = contract_name.casefold()

    matches = [
        name
        for name in names
        if folded
        in {
            part.casefold()
            for part in name.split("_")
        }
    ]

    if len(matches) == 1:
        return matches[0]

    suffix_matches = [
        name
        for name in names
        if (
            name.casefold().endswith(
                "_" + folded
            )
            or name.casefold().startswith(
                folded + "_"
            )
        )
    ]

    if len(suffix_matches) == 1:
        return suffix_matches[0]

    return None


def _statement_binds_name(
    statement: ast.stmt,
    *,
    name: str,
) -> bool:
    return any(
        isinstance(
            node,
            ast.Name,
        )
        and node.id == name
        and isinstance(
            node.ctx,
            ast.Store,
        )
        for node in ast.walk(
            statement
        )
    )


def _is_valueerror_raise(
    statement: ast.stmt,
) -> bool:
    if not isinstance(
        statement,
        ast.Raise,
    ):
        return False

    exc = statement.exc

    if _is_name(
        exc,
        "ValueError",
    ):
        return True

    return (
        isinstance(
            exc,
            ast.Call,
        )
        and _is_name(
            exc.func,
            "ValueError",
        )
    )


def _if_only_raises_valueerror(
    statement: ast.stmt,
) -> bool:
    return (
        isinstance(
            statement,
            ast.If,
        )
        and not statement.orelse
        and len(statement.body) == 1
        and _is_valueerror_raise(
            statement.body[0]
        )
    )


def _is_not_isinstance_int_guard(
    statement: ast.stmt,
    *,
    name: str,
) -> bool:
    if not _if_only_raises_valueerror(
        statement
    ):
        return False

    test = statement.test

    if not (
        isinstance(
            test,
            ast.UnaryOp,
        )
        and isinstance(
            test.op,
            ast.Not,
        )
    ):
        return False

    call = test.operand

    return (
        isinstance(
            call,
            ast.Call,
        )
        and _is_name(
            call.func,
            "isinstance",
        )
        and len(call.args) == 2
        and not call.keywords
        and _is_name(
            call.args[0],
            name,
        )
        and _is_name(
            call.args[1],
            "int",
        )
    )


def _remove_simple_int_type_guard(
    source: str,
    *,
    name: str,
) -> str:
    tree = _parse_module(
        source
    )

    if tree is None:
        return source

    function = _first_top_level_function(
        tree
    )

    if function is None:
        return source

    guards = [
        statement
        for statement in function.body
        if _is_not_isinstance_int_guard(
            statement,
            name=name,
        )
    ]

    if len(guards) != 1:
        return source

    return _delete_statement(
        source,
        guards[0],
    )


def _function_calls_int_on_name(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
) -> bool:
    # Direct conversion of the local itself.
    if _function_calls_constructor_on_name(
        function,
        constructor="int",
        name=name,
    ):
        return True

    # Also treat a direct binding such as:
    #
    #     amount = int(order[1])
    #
    # as an existing explicit conversion of ``amount``.
    # The previous implementation recognized only
    # ``amount = int(amount)``-shaped usage indirectly,
    # which caused duplicate conversions to be inserted.
    for statement in function.body:
        parsed = _single_name_assignment(
            statement
        )

        if parsed is None:
            continue

        target_name, value = parsed

        if target_name != name:
            continue

        if not isinstance(
            value,
            ast.Call,
        ):
            continue

        if not _is_name(
            value.func,
            "int",
        ):
            continue

        if (
            len(value.args) == 1
            and not value.keywords
        ):
            return True

    return False


def _binding_insertion_line(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
) -> int | None:
    argument_names = {
        argument.arg
        for argument in (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
        )
    }

    if name in argument_names:
        docstring_end = (
            _function_docstring_end_line(
                function
            )
        )

        if docstring_end is not None:
            return docstring_end

        if function.body:
            return (
                function.body[0].lineno
                - 1
            )

        return function.lineno

    matches = [
        statement
        for statement in function.body
        if _statement_binds_name(
            statement,
            name=name,
        )
    ]

    if len(matches) != 1:
        return None

    return matches[0].end_lineno


def _insert_after_source_line(
    source: str,
    *,
    line: int,
    indent: int,
    statements: list[str],
) -> str:
    lines = source.splitlines()

    prefix = " " * indent

    rendered = [
        prefix + item
        for item in statements
    ]

    lines[
        line:line
    ] = rendered

    return (
        "\n".join(lines).rstrip()
        + "\n"
    )


def _function_has_negative_valueerror_guard(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
) -> bool:
    for statement in function.body:
        if not _if_only_raises_valueerror(
            statement
        ):
            continue

        test = statement.test

        if not isinstance(
            test,
            ast.Compare,
        ):
            continue

        if (
            len(test.ops) != 1
            or len(test.comparators) != 1
        ):
            continue

        operator = test.ops[0]
        comparator = test.comparators[0]

        if (
            isinstance(
                operator,
                ast.Lt,
            )
            and _is_name(
                test.left,
                name,
            )
            and isinstance(
                comparator,
                ast.Constant,
            )
            and comparator.value == 0
        ):
            return True

        if (
            isinstance(
                operator,
                ast.Gt,
            )
            and isinstance(
                test.left,
                ast.Constant,
            )
            and test.left.value == 0
            and _is_name(
                comparator,
                name,
            )
        ):
            return True

    return False


def _request_requires_negative_valueerror(
    request: str,
) -> bool:
    text = _normalized_request_text(
        request
    )

    return (
        "negative"
        in text
        and "raise"
        in text
        and "valueerror"
        in text
    )


def _find_int_assignment_end_line(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
) -> int | None:
    for statement in function.body:
        parsed = _single_name_assignment(
            statement
        )

        if parsed is None:
            continue

        target_name, value = parsed

        if target_name != name:
            continue

        if not isinstance(
            value,
            ast.Call,
        ):
            continue

        if not _is_name(
            value.func,
            "int",
        ):
            continue

        if (
            len(value.args) == 1
            and not value.keywords
            and _is_name(
                value.args[0],
                name,
            )
        ):
            return statement.end_lineno

    return None


def _repair_explicit_int_contract(
    *,
    request: str,
    source: str,
    failure: str,
) -> str | None:
    del failure

    contract_names = (
        _requested_int_contract_names(
            request
        )
    )

    if not contract_names:
        return None

    current = source
    changed = False

    for contract_name in contract_names:
        tree = _parse_module(
            current
        )

        if tree is None:
            return None

        function = _first_top_level_function(
            tree
        )

        if function is None:
            return None

        local_name = (
            _resolve_contract_local_name(
                function,
                contract_name=contract_name,
            )
        )

        if local_name is None:
            continue

        without_guard = (
            _remove_simple_int_type_guard(
                current,
                name=local_name,
            )
        )

        if without_guard != current:
            current = without_guard
            changed = True

        tree = _parse_module(
            current
        )

        if tree is None:
            return None

        function = _first_top_level_function(
            tree
        )

        if function is None:
            return None

        if not _function_calls_int_on_name(
            function,
            name=local_name,
        ):
            line = _binding_insertion_line(
                function,
                name=local_name,
            )

            if line is None:
                continue

            current = _insert_after_source_line(
                current,
                line=line,
                indent=function.col_offset + 4,
                statements=[
                    (
                        f"{local_name} = "
                        f"int({local_name})"
                    ),
                ],
            )

            changed = True

        if _request_requires_negative_valueerror(
            request
        ):
            tree = _parse_module(
                current
            )

            if tree is None:
                return None

            function = _first_top_level_function(
                tree
            )

            if function is None:
                return None

            if not _function_has_negative_valueerror_guard(
                function,
                name=local_name,
            ):
                line = (
                    _find_int_assignment_end_line(
                        function,
                        name=local_name,
                    )
                )

                if line is None:
                    line = _binding_insertion_line(
                        function,
                        name=local_name,
                    )

                if line is None:
                    continue

                current = _insert_after_source_line(
                    current,
                    line=line,
                    indent=function.col_offset + 4,
                    statements=[
                        f"if {local_name} < 0:",
                        (
                            "    raise ValueError("
                            "\"negative value is not allowed\""
                            ")"
                        ),
                    ],
                )

                changed = True

    if not changed:
        return None

    if _parse_module(
        current
    ) is None:
        return None

    return current


def _request_requires_exactly_one_level(
    request: str,
) -> bool:
    text = _normalized_request_text(
        request
    )

    return _contains_any_marker(
        text,
        (
            "flatten exactly one nesting level",
            "exactly one nesting level",
            "exactly one level",
            "one nesting level",
        ),
    )


def _function_calls_itself(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return any(
        isinstance(
            node,
            ast.Call,
        )
        and _is_name(
            node.func,
            function.name,
        )
        for node in ast.walk(
            function
        )
    )


class _OneLevelExtendTransformer(
    ast.NodeTransformer
):
    def __init__(
        self,
        function_name: str,
    ) -> None:
        self.function_name = (
            function_name
        )
        self.changed = False

    def visit_Call(
        self,
        node: ast.Call,
    ) -> ast.AST:
        node = self.generic_visit(
            node
        )

        if not isinstance(
            node,
            ast.Call,
        ):
            return node

        if not isinstance(
            node.func,
            ast.Attribute,
        ):
            return node

        if node.func.attr != "extend":
            return node

        if (
            len(node.args) != 1
            or node.keywords
        ):
            return node

        inner = node.args[0]

        if not isinstance(
            inner,
            ast.Call,
        ):
            return node

        if not _is_name(
            inner.func,
            self.function_name,
        ):
            return node

        if (
            len(inner.args) != 1
            or inner.keywords
        ):
            return node

        node.args[0] = inner.args[0]

        self.changed = True

        return node


def _repair_bounded_one_level_recursion(
    *,
    request: str,
    source: str,
    failure: str,
) -> str | None:
    del failure

    if not _request_requires_exactly_one_level(
        request
    ):
        return None

    tree = _parse_module(
        source
    )

    if tree is None:
        return None

    function = _first_top_level_function(
        tree
    )

    if function is None:
        return None

    if not _function_calls_itself(
        function
    ):
        return None

    transformer = (
        _OneLevelExtendTransformer(
            function.name
        )
    )

    updated = transformer.visit(
        tree
    )

    if not transformer.changed:
        return None

    ast.fix_missing_locations(
        updated
    )

    candidate = (
        ast.unparse(
            updated
        ).rstrip()
        + "\n"
    )

    if _parse_module(
        candidate
    ) is None:
        return None

    return candidate


def _requested_pair_contract(
    request: str,
) -> tuple[
    str,
    str,
    str,
] | None:
    text = str(
        request or ""
    )

    match = re.search(
        (
            r"\b"
            r"([A-Za-z_][A-Za-z0-9_]*)"
            r"\s+is\s+a\s*"
            r"\(\s*"
            r"([A-Za-z_][A-Za-z0-9_]*)"
            r"\s*,\s*"
            r"([A-Za-z_][A-Za-z0-9_]*)"
            r"\s*\)\s*pair\b"
        ),
        text,
        flags=re.I,
    )

    if match is None:
        return None

    return (
        match.group(1),
        match.group(2),
        match.group(3),
    )


def _request_requires_missing_as_zero(
    request: str,
) -> bool:
    text = _normalized_request_text(
        request
    )

    return (
        "missing"
        in text
        and _contains_any_marker(
            text,
            (
                "count as zero",
                "counts as zero",
                "count as 0",
                "counts as 0",
                "default to zero",
                "default to 0",
            ),
        )
    )


def _request_requires_available_ge_requested(
    request: str,
) -> bool:
    text = _normalized_request_text(
        request
    )

    return (
        _contains_any_marker(
            text,
            (
                "return true only when",
                "return true when",
                "true only when",
            ),
        )
        and _contains_any_marker(
            text,
            (
                "available stock",
                "available",
            ),
        )
        and _contains_any_marker(
            text,
            (
                ">=",
                "greater than or equal",
                "at least",
            ),
        )
        and _contains_any_marker(
            text,
            (
                "requested quantity",
                "requested amount",
            ),
        )
    )


def _pair_argument_contradiction_proven(
    *,
    source: str,
    failure: str,
    pair_argument: str,
) -> bool:
    tree = _parse_module(
        source
    )

    if tree is None:
        return False

    function = _first_top_level_function(
        tree
    )

    if function is None:
        return False

    failure_text = str(
        failure or ""
    ).casefold()

    tuple_failure = (
        "valueerror"
        in failure_text
        and "tuple"
        in failure_text
    )

    list_guard = False

    for node in ast.walk(
        function
    ):
        if not isinstance(
            node,
            ast.If,
        ):
            continue

        test = node.test

        if not (
            isinstance(
                test,
                ast.UnaryOp,
            )
            and isinstance(
                test.op,
                ast.Not,
            )
        ):
            continue

        call = test.operand

        if not (
            isinstance(
                call,
                ast.Call,
            )
            and _is_name(
                call.func,
                "isinstance",
            )
            and len(call.args) == 2
            and not call.keywords
            and _is_name(
                call.args[0],
                pair_argument,
            )
            and _is_name(
                call.args[1],
                "list",
            )
        ):
            continue

        list_guard = True
        break

    iterates_pair = any(
        isinstance(
            node,
            (
                ast.For,
                ast.comprehension,
            ),
        )
        and _is_name(
            node.iter,
            pair_argument,
        )
        for node in ast.walk(
            function
        )
    )

    return (
        tuple_failure
        or list_guard
        or iterates_pair
    )


def _function_positional_argument_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    return [
        argument.arg
        for argument in (
            list(
                function.args.posonlyargs
            )
            + list(
                function.args.args
            )
        )
    ]


def _repair_explicit_pair_availability_contract(
    *,
    request: str,
    source: str,
    failure: str,
) -> str | None:
    contract = (
        _requested_pair_contract(
            request
        )
    )

    if contract is None:
        return None

    (
        pair_contract_name,
        key_name,
        quantity_name,
    ) = contract

    requested_int_names = set(
        _requested_int_contract_names(
            request
        )
    )

    if quantity_name not in requested_int_names:
        return None

    if not _request_requires_negative_valueerror(
        request
    ):
        return None

    if not _request_requires_missing_as_zero(
        request
    ):
        return None

    if not _request_requires_available_ge_requested(
        request
    ):
        return None

    tree = _parse_module(
        source
    )

    if tree is None:
        return None

    function = _first_top_level_function(
        tree
    )

    if function is None:
        return None

    arguments = (
        _function_positional_argument_names(
            function
        )
    )

    if len(arguments) != 2:
        return None

    pair_argument = (
        _resolve_contract_local_name(
            function,
            contract_name=pair_contract_name,
        )
    )

    if (
        pair_argument is None
        or pair_argument not in arguments
    ):
        return None

    mapping_candidates = [
        name
        for name in arguments
        if name != pair_argument
    ]

    if len(mapping_candidates) != 1:
        return None

    mapping_argument = (
        mapping_candidates[0]
    )

    if not _pair_argument_contradiction_proven(
        source=source,
        failure=failure,
        pair_argument=pair_argument,
    ):
        return None

    new_body: list[ast.stmt] = [
        ast.Assign(
            targets=[
                ast.Tuple(
                    elts=[
                        ast.Name(
                            id=key_name,
                            ctx=ast.Store(),
                        ),
                        ast.Name(
                            id=quantity_name,
                            ctx=ast.Store(),
                        ),
                    ],
                    ctx=ast.Store(),
                )
            ],
            value=ast.Name(
                id=pair_argument,
                ctx=ast.Load(),
            ),
        ),
        ast.Assign(
            targets=[
                ast.Name(
                    id=quantity_name,
                    ctx=ast.Store(),
                )
            ],
            value=ast.Call(
                func=ast.Name(
                    id="int",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Name(
                        id=quantity_name,
                        ctx=ast.Load(),
                    )
                ],
                keywords=[],
            ),
        ),
        ast.If(
            test=ast.Compare(
                left=ast.Name(
                    id=quantity_name,
                    ctx=ast.Load(),
                ),
                ops=[
                    ast.Lt()
                ],
                comparators=[
                    ast.Constant(
                        value=0
                    )
                ],
            ),
            body=[
                ast.Raise(
                    exc=ast.Call(
                        func=ast.Name(
                            id="ValueError",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Constant(
                                value=(
                                    "negative value "
                                    "is not allowed"
                                )
                            )
                        ],
                        keywords=[],
                    ),
                    cause=None,
                )
            ],
            orelse=[],
        ),
        ast.Return(
            value=ast.Compare(
                left=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(
                            id=mapping_argument,
                            ctx=ast.Load(),
                        ),
                        attr="get",
                        ctx=ast.Load(),
                    ),
                    args=[
                        ast.Name(
                            id=key_name,
                            ctx=ast.Load(),
                        ),
                        ast.Constant(
                            value=0
                        ),
                    ],
                    keywords=[],
                ),
                ops=[
                    ast.GtE()
                ],
                comparators=[
                    ast.Name(
                        id=quantity_name,
                        ctx=ast.Load(),
                    )
                ],
            )
        ),
    ]

    function.body = new_body

    ast.fix_missing_locations(
        tree
    )

    candidate = (
        ast.unparse(
            tree
        ).rstrip()
        + "\n"
    )

    try:
        compile(
            candidate,
            "<fast-local-pair-contract>",
            "exec",
        )
    except SyntaxError:
        return None

    return candidate


def _is_constant_zero(
    node: ast.AST,
) -> bool:
    return (
        isinstance(
            node,
            ast.Constant,
        )
        and node.value == 0
    )


def _is_pair_field_subscript(
    node: ast.AST,
    *,
    pair_name: str,
    index: int,
) -> bool:
    if not isinstance(
        node,
        ast.Subscript,
    ):
        return False

    if not _is_name(
        node.value,
        pair_name,
    ):
        return False

    slice_node = node.slice

    return (
        isinstance(
            slice_node,
            ast.Constant,
        )
        and slice_node.value == index
    )


def _negative_pair_field_guard(
    statement: ast.stmt,
    *,
    pair_name: str,
    index: int,
) -> bool:
    if not _if_only_raises_valueerror(
        statement
    ):
        return False

    test = statement.test

    if not isinstance(
        test,
        ast.Compare,
    ):
        return False

    if (
        len(test.ops) != 1
        or len(test.comparators) != 1
    ):
        return False

    operator = test.ops[0]
    right = test.comparators[0]

    if (
        isinstance(
            operator,
            ast.Lt,
        )
        and _is_pair_field_subscript(
            test.left,
            pair_name=pair_name,
            index=index,
        )
        and _is_constant_zero(
            right
        )
    ):
        return True

    if (
        isinstance(
            operator,
            ast.Gt,
        )
        and _is_constant_zero(
            test.left
        )
        and _is_pair_field_subscript(
            right,
            pair_name=pair_name,
            index=index,
        )
    ):
        return True

    return False


def _int_pair_field_assignment(
    statement: ast.stmt,
    *,
    local_name: str,
    pair_name: str,
    index: int,
) -> bool:
    parsed = _single_name_assignment(
        statement
    )

    if parsed is None:
        return False

    target_name, value = parsed

    if target_name != local_name:
        return False

    if not isinstance(
        value,
        ast.Call,
    ):
        return False

    if not _is_name(
        value.func,
        "int",
    ):
        return False

    if (
        len(value.args) != 1
        or value.keywords
    ):
        return False

    return _is_pair_field_subscript(
        value.args[0],
        pair_name=pair_name,
        index=index,
    )


def _rewrite_negative_guard_to_local(
    statement: ast.If,
    *,
    local_name: str,
) -> None:
    test = statement.test

    if not isinstance(
        test,
        ast.Compare,
    ):
        return

    operator = test.ops[0]

    if isinstance(
        operator,
        ast.Lt,
    ):
        test.left = ast.Name(
            id=local_name,
            ctx=ast.Load(),
        )

    elif isinstance(
        operator,
        ast.Gt,
    ):
        test.comparators[0] = ast.Name(
            id=local_name,
            ctx=ast.Load(),
        )


def _failure_proves_preconversion_numeric_compare(
    failure: str,
) -> bool:
    text = str(
        failure or ""
    ).casefold()

    return (
        "typeerror"
        in text
        and "not supported"
        in text
        and "str"
        in text
        and "int"
        in text
    )


def _repair_pair_field_int_conversion_order(
    *,
    request: str,
    source: str,
    failure: str,
) -> str | None:
    contract = (
        _requested_pair_contract(
            request
        )
    )

    if contract is None:
        return None

    (
        pair_contract_name,
        _key_contract_name,
        quantity_contract_name,
    ) = contract

    if quantity_contract_name not in set(
        _requested_int_contract_names(
            request
        )
    ):
        return None

    if not _request_requires_negative_valueerror(
        request
    ):
        return None

    if not _failure_proves_preconversion_numeric_compare(
        failure
    ):
        return None

    tree = _parse_module(
        source
    )

    if tree is None:
        return None

    function = _first_top_level_function(
        tree
    )

    if function is None:
        return None

    pair_local = (
        _resolve_contract_local_name(
            function,
            contract_name=pair_contract_name,
        )
    )

    quantity_local = (
        _resolve_contract_local_name(
            function,
            contract_name=quantity_contract_name,
        )
    )

    if (
        pair_local is None
        or quantity_local is None
    ):
        return None

    positional = (
        _function_positional_argument_names(
            function
        )
    )

    if pair_local not in positional:
        return None

    guard_matches: list[
        tuple[
            int,
            ast.If,
        ]
    ] = []

    conversion_matches: list[
        tuple[
            int,
            ast.stmt,
        ]
    ] = []

    for position, statement in enumerate(
        function.body
    ):
        if (
            isinstance(
                statement,
                ast.If,
            )
            and _negative_pair_field_guard(
                statement,
                pair_name=pair_local,
                index=1,
            )
        ):
            guard_matches.append(
                (
                    position,
                    statement,
                )
            )

        if _int_pair_field_assignment(
            statement,
            local_name=quantity_local,
            pair_name=pair_local,
            index=1,
        ):
            conversion_matches.append(
                (
                    position,
                    statement,
                )
            )

    if (
        len(guard_matches) != 1
        or len(conversion_matches) != 1
    ):
        return None

    (
        guard_position,
        guard,
    ) = guard_matches[0]

    (
        conversion_position,
        conversion,
    ) = conversion_matches[0]

    # The only authority for this repair is conversion occurring
    # after a negative numeric use of the same pair field.
    if conversion_position <= guard_position:
        return None

    # Move the existing conversion; do not synthesize a second one.
    function.body.pop(
        conversion_position
    )

    function.body.insert(
        guard_position,
        conversion
    )

    # The guard moved one slot to the right.
    moved_guard = function.body[
        guard_position + 1
    ]

    if not isinstance(
        moved_guard,
        ast.If,
    ):
        return None

    _rewrite_negative_guard_to_local(
        moved_guard,
        local_name=quantity_local,
    )

    ast.fix_missing_locations(
        tree
    )

    candidate = (
        ast.unparse(
            tree
        ).rstrip()
        + "\n"
    )

    try:
        compile(
            candidate,
            "<fast-local-pair-field-order>",
            "exec",
        )
    except SyntaxError:
        return None

    return candidate


def _repair_generic_explicit_contract_closure(
    *,
    request: str,
    source: str,
    failure: str,
) -> tuple[str | None, str]:
    current = source
    reasons: list[str] = []

    candidate = (
        _repair_pair_field_int_conversion_order(
            request=request,
            source=current,
            failure=failure,
        )
    )

    if (
        candidate is not None
        and candidate != current
    ):
        current = candidate
        reasons.append(
            "pair-field-int-order"
        )

    candidate = (
        _repair_explicit_pair_availability_contract(
            request=request,
            source=current,
            failure=failure,
        )
    )

    if (
        candidate is not None
        and candidate != current
    ):
        current = candidate
        reasons.append(
            "explicit-pair-availability"
        )

    candidate = (
        _repair_explicit_int_contract(
            request=request,
            source=current,
            failure=failure,
        )
    )

    if (
        candidate is not None
        and candidate != current
    ):
        current = candidate
        reasons.append(
            "explicit-int-contract"
        )

    candidate = (
        _repair_any_iterable_materialization(
            request=request,
            source=current,
            failure=failure,
        )
    )

    if (
        candidate is not None
        and candidate != current
    ):
        current = candidate
        reasons.append(
            "iterable-materialization"
        )

    candidate = (
        _repair_bounded_one_level_recursion(
            request=request,
            source=current,
            failure=failure,
        )
    )

    if (
        candidate is not None
        and candidate != current
    ):
        current = candidate
        reasons.append(
            "bounded-one-level"
        )

    if not reasons:
        return (
            None,
            "",
        )

    try:
        compile(
            current,
            "<fast-local-generic-contract-closure>",
            "exec",
        )
    except SyntaxError:
        return (
            None,
            "",
        )

    return (
        current,
        "+".join(
            reasons
        ),
    )


def _deterministic_contract_repair(
    *,
    request: str,
    source: str,
    failure: str,
) -> tuple[str | None, str]:
    candidate = (
        _repair_explicit_string_conversion_contradiction(
            request=request,
            source=source,
            failure=failure,
        )
    )

    if candidate is not None:
        return (
            candidate,
            "string-conversion contradiction",
        )

    candidate = (
        _repair_unhashable_equality_contradiction(
            request=request,
            source=source,
            failure=failure,
        )
    )

    if candidate is not None:
        return (
            candidate,
            "unhashable-equality contradiction",
        )

    (
        candidate,
        generic_reason,
    ) = (
        _repair_generic_explicit_contract_closure(
            request=request,
            source=source,
            failure=failure,
        )
    )

    if candidate is not None:
        return (
            candidate,
            generic_reason,
        )

    return (
        None,
        "",
    )


def try_fast_local_python_coding(
    *,
    request: str,
    workspace: Path,
    backend: Backend,
    max_model_calls: int = 2,
) -> FastCodingResult:
    """Attempt a narrow verified Python edit, otherwise decline safely."""

    started = time.perf_counter()

    root = Path(workspace).expanduser().resolve()
    paths = _explicit_python_paths(request)

    relative_path, target_reason = (
        _resolve_fast_python_target(
            root=root,
            request=request,
            explicit_paths=paths,
        )
    )

    if relative_path is None:
        return FastCodingResult(
            attempted=False,
            success=False,
            reason=target_reason,
        )
    target = (root / relative_path).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        return FastCodingResult(
            attempted=False,
            success=False,
            reason="target escapes workspace",
        )

    if not target.is_file():
        return FastCodingResult(
            attempted=False,
            success=False,
            path=relative_path,
            reason="target file does not already exist",
        )

    tests = _pytest_files(root)

    if not tests:
        return FastCodingResult(
            attempted=False,
            success=False,
            path=relative_path,
            reason="bounded pytest evidence unavailable",
        )

    # Keep the context small enough for tiny local models.
    source = target.read_text(
        encoding="utf-8",
    )

    if len(source) > 12_000:
        return FastCodingResult(
            attempted=False,
            success=False,
            path=relative_path,
            reason="target file exceeds fast-path size bound",
        )

    tests_text_parts: list[str] = []
    tests_chars = 0

    for test in tests:
        content = test.read_text(
            encoding="utf-8",
            errors="replace",
        )

        block = (
            f"\nFILE: {test.relative_to(root)}\n"
            + content
        )

        if tests_chars + len(block) > 12_000:
            break

        tests_text_parts.append(block)
        tests_chars += len(block)

    if not tests_text_parts:
        return FastCodingResult(
            attempted=False,
            success=False,
            path=relative_path,
            reason="test context exceeds fast-path bound",
        )

    original = source
    calls: list[float] = []

    try:
        # ----------------------------------------------------
        # Call 1: direct candidate.
        # ----------------------------------------------------
        call_started = time.perf_counter()

        response = backend(
            _candidate_prompt(
                request,
                relative_path,
                source,
                "\n".join(tests_text_parts),
            ),
            _SYSTEM,
        )

        calls.append(
            time.perf_counter()
            - call_started
        )

        candidate = _extract_source(
            response
        )

        target.write_text(
            candidate,
            encoding="utf-8",
        )

        score = _score_pytest(
            root,
            tests,
        )

        if score["returncode"] == 0:
            return FastCodingResult(
                attempted=True,
                success=True,
                path=relative_path,
                model_calls=1,
                elapsed_seconds=(
                    time.perf_counter()
                    - started
                ),
                passed=score["passed"],
                failed=score["failed"],
                total=score["total"],
                test_output=score["output"],
                reason="first candidate passed pytest",
                call_seconds=calls,
            )

        if max_model_calls < 2:
            target.write_text(
                original,
                encoding="utf-8",
            )

            return FastCodingResult(
                attempted=True,
                success=False,
                path=relative_path,
                model_calls=1,
                elapsed_seconds=(
                    time.perf_counter()
                    - started
                ),
                passed=score["passed"],
                failed=score["failed"],
                total=score["total"],
                test_output=score["output"],
                reason="candidate failed and repair call disabled",
                call_seconds=calls,
            )

        # ----------------------------------------------------
        # Call 2: compact evidence repair.
        # ----------------------------------------------------
        call_started = time.perf_counter()

        response = backend(
            _repair_prompt(
                request,
                relative_path,
                candidate,
                score["output"],
            ),
            _SYSTEM,
        )

        calls.append(
            time.perf_counter()
            - call_started
        )

        repaired = _extract_source(
            response
        )

        target.write_text(
            repaired,
            encoding="utf-8",
        )

        repaired_score = _score_pytest(
            root,
            tests,
        )

        if repaired_score["returncode"] == 0:
            return FastCodingResult(
                attempted=True,
                success=True,
                path=relative_path,
                model_calls=2,
                elapsed_seconds=(
                    time.perf_counter()
                    - started
                ),
                passed=repaired_score["passed"],
                failed=repaired_score["failed"],
                total=repaired_score["total"],
                test_output=repaired_score["output"],
                reason="compact repair passed pytest",
                call_seconds=calls,
            )

        # ----------------------------------------------------
        # Deterministic contradiction closure.
        #
        # No third model call.  Apply only a mechanically
        # provable contradiction between the explicit request,
        # candidate source, and objective pytest evidence.
        # ----------------------------------------------------
        deterministic, deterministic_reason = (
            _deterministic_contract_repair(
                request=request,
                source=repaired,
                failure=repaired_score["output"],
            )
        )

        if deterministic is not None:
            target.write_text(
                deterministic,
                encoding="utf-8",
            )

            deterministic_score = _score_pytest(
                root,
                tests,
            )

            if deterministic_score["returncode"] == 0:
                return FastCodingResult(
                    attempted=True,
                    success=True,
                    path=relative_path,
                    model_calls=2,
                    elapsed_seconds=(
                        time.perf_counter()
                        - started
                    ),
                    passed=deterministic_score["passed"],
                    failed=deterministic_score["failed"],
                    total=deterministic_score["total"],
                    test_output=deterministic_score["output"],
                    reason=(
                        "deterministic "
                        + deterministic_reason
                        + " repair passed pytest"
                    ),
                    call_seconds=calls,
                )

        # Never leave an unverified fast-path edit behind.
        target.write_text(
            original,
            encoding="utf-8",
        )

        return FastCodingResult(
            attempted=True,
            success=False,
            path=relative_path,
            model_calls=2,
            elapsed_seconds=(
                time.perf_counter()
                - started
            ),
            passed=repaired_score["passed"],
            failed=repaired_score["failed"],
            total=repaired_score["total"],
            test_output=repaired_score["output"],
            reason=(
                "bounded fast path exhausted; "
                "original file restored for full runtime"
            ),
            call_seconds=calls,
        )

    except Exception as error:
        # Tier-1 failure must be transactional.
        target.write_text(
            original,
            encoding="utf-8",
        )

        return FastCodingResult(
            attempted=True,
            success=False,
            path=relative_path,
            model_calls=len(calls),
            elapsed_seconds=(
                time.perf_counter()
                - started
            ),
            reason=(
                f"fast path failed safely: "
                f"{type(error).__name__}: {error}"
            ),
            call_seconds=calls,
        )
