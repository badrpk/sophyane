import ast
from pathlib import Path


def test_run_adaptive_loop_operation_import_dominates_all_operation_uses():
    path = Path("src/sophyane/adaptive_execution.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    fn = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "run_adaptive_loop"
    )

    operation_uses = sorted(
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Name)
        and node.id == "Operation"
        and isinstance(node.ctx, ast.Load)
    )

    imports = sorted(
        node.lineno
        for node in fn.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "sophyane.rsi.authority"
        and any(
            alias.name == "Operation"
            and (alias.asname is None or alias.asname == "Operation")
            for alias in node.names
        )
    )

    assert operation_uses, "run_adaptive_loop must use Operation"
    assert imports, (
        "Operation must be imported unconditionally in the top-level "
        "body of run_adaptive_loop"
    )
    assert imports[0] < operation_uses[0]
