"""Sandboxed Python code interpreter for agent tool-use."""

from __future__ import annotations

import ast
import io
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

# Disallow dangerous imports / calls in AST (best-effort sandbox).
_BLOCKED_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "input",
    "breakpoint",
    "exit",
    "quit",
}
_BLOCKED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "ctypes",
    "multiprocessing",
    "signal",
    "importlib",
    "http",
    "urllib",
    "requests",
}


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_MODULES:
                    raise ValueError(f"import blocked: {alias.name}")
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in _BLOCKED_MODULES:
                raise ValueError(f"import blocked: {node.module}")
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in _BLOCKED_NAMES:
                raise ValueError(f"name blocked: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("dunder attribute access blocked")


def run_python(code: str, *, timeout_note: str = "best-effort sandbox") -> dict[str, Any]:
    """Execute a restricted Python snippet; returns stdout/stderr/result."""
    code = (code or "").strip()
    if not code:
        return {"ok": False, "error": "empty code"}
    if len(code) > 20_000:
        return {"ok": False, "error": "code too large"}
    try:
        tree = ast.parse(code, mode="exec")
        _validate_ast(tree)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"validation: {error}"}

    stdout = io.StringIO()
    stderr = io.StringIO()
    # Safe builtins subset
    safe_builtins = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "print": print,
        "range": range,
        "reversed": reversed,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        "True": True,
        "False": False,
        "None": None,
    }
    globals_dict: dict[str, Any] = {"__builtins__": safe_builtins}
    locals_dict: dict[str, Any] = {}
    try:
        compiled = compile(tree, "<sophyane-repl>", "exec")
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(compiled, globals_dict, locals_dict)  # noqa: S102 — intentional restricted exec
        # Prefer last expression value if present
        result = None
        try:
            # re-parse last line as expression
            last = code.strip().splitlines()[-1]
            expr_tree = ast.parse(last, mode="eval")
            _validate_ast(expr_tree)
            result = eval(compile(expr_tree, "<sophyane-repl-eval>", "eval"), globals_dict, locals_dict)  # noqa: S307
        except Exception:  # noqa: BLE001
            result = locals_dict.get("result", locals_dict.get("out"))
        return {
            "ok": True,
            "stdout": stdout.getvalue()[-8000:],
            "stderr": stderr.getvalue()[-2000:],
            "result": repr(result) if result is not None else None,
            "sandbox": timeout_note,
        }
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "stdout": stdout.getvalue()[-4000:],
            "stderr": (stderr.getvalue() + traceback.format_exc())[-4000:],
            "error": str(error),
        }
