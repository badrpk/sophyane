from __future__ import annotations

import ast
from pathlib import Path

from sophyane import harness


def test_harness_resource_import_is_optional() -> None:
    path = Path(
        "src/sophyane/harness.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8",
        )
    )

    plain_resource_imports = []

    for node in tree.body:
        if isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                if alias.name == "resource":
                    plain_resource_imports.append(
                        node.lineno
                    )

    assert plain_resource_imports == []


def test_preexec_is_safe_when_resource_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        harness,
        "resource",
        None,
    )

    runner = harness.SandboxRunner()

    runner._preexec()


def test_windows_execution_does_not_require_preexec(
    monkeypatch,
) -> None:
    runner = harness.SandboxRunner()

    captured = {}

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(
        *args,
        **kwargs,
    ):
        captured.update(
            kwargs
        )
        return Completed()

    monkeypatch.setattr(
        harness.os,
        "name",
        "nt",
    )

    monkeypatch.setattr(
        harness.subprocess,
        "run",
        fake_run,
    )

    result = runner.run(
        [
            "python",
            "-c",
            "print('ok')",
        ],
        shell=False,
    )

    assert result.ok is True

    assert (
        captured["preexec_fn"]
        is None
    )
