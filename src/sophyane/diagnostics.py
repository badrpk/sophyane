"""Sophyane self-diagnostic checks."""

from __future__ import annotations

import inspect
import json
import os
import py_compile
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from sophyane.config import (
    CONFIG_FILE,
    DATA_DIR,
    LOG_DIR,
    WORKSPACE_DIR,
    ensure_directories,
    load_config,
)
from sophyane.memory import MemoryStore
from sophyane.plugin_loader import PluginLoader
from sophyane.providers.base import Provider
from sophyane.version import __version__


def run_diagnostics() -> tuple[bool, str]:
    ensure_directories()
    checks: list[dict[str, Any]] = []

    def record(
        name: str,
        passed: bool,
        detail: str,
    ) -> None:
        checks.append(
            {
                "name": name,
                "passed": passed,
                "detail": detail,
            }
        )

    record(
        "Python version",
        sys.version_info >= (3, 10),
        sys.version.split()[0],
    )

    loader = PluginLoader()
    providers = loader.discover()

    record(
        "Provider discovery",
        bool(providers),
        ", ".join(sorted(providers))
        or json.dumps(loader.errors),
    )

    timeout_support = True
    timeout_details: list[str] = []

    for provider_id, provider_class in providers.items():
        signature = inspect.signature(provider_class.__init__)
        supports_timeout = (
            "timeout" in signature.parameters
            or any(
                parameter.kind
                == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
        )

        timeout_support = timeout_support and supports_timeout
        timeout_details.append(
            f"{provider_id}:{'yes' if supports_timeout else 'no'}"
        )

    record(
        "Provider timeout compatibility",
        timeout_support,
        ", ".join(timeout_details),
    )

    try:
        memory = MemoryStore()
        test_fact = (
            "__sophyane_doctor_test_memory_do_not_keep__"
        )
        memory.remember(
            test_fact,
            importance=1,
            source="doctor",
        )

        matching = [
            item
            for item in memory.list(limit=200)
            if item["content"] == test_fact
        ]

        if matching:
            memory.forget(int(matching[0]["id"]))

        record(
            "SQLite memory",
            bool(matching),
            str(memory.path),
        )
    except (OSError, sqlite3.Error) as error:
        record("SQLite memory", False, str(error))

    writable_paths = [
        DATA_DIR,
        WORKSPACE_DIR,
        LOG_DIR,
    ]

    for path in writable_paths:
        try:
            probe = path / ".doctor-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            record(
                f"Writable: {path.name}",
                True,
                str(path),
            )
        except OSError as error:
            record(
                f"Writable: {path.name}",
                False,
                str(error),
            )

    config = load_config()

    record(
        "Configuration",
        bool(config.get("provider")),
        str(CONFIG_FILE),
    )

    package_root = Path(__file__).resolve().parent
    compile_errors: list[str] = []

    for path in package_root.rglob("*.py"):
        try:
            py_compile.compile(
                str(path),
                doraise=True,
            )
        except py_compile.PyCompileError as error:
            compile_errors.append(
                f"{path.name}: {error.msg}"
            )

    record(
        "Python compilation",
        not compile_errors,
        "; ".join(compile_errors) or "all modules compile",
    )

    cache_files = list(
        package_root.rglob("__pycache__")
    )

    record(
        "Runtime package",
        package_root.exists(),
        str(package_root),
    )

    record(
        "Git executable",
        shutil.which("git") is not None,
        shutil.which("git") or "not installed",
    )

    passed = all(check["passed"] for check in checks)

    lines = [
        f"Sophyane {__version__} diagnostics",
        "=" * 44,
    ]

    for check in checks:
        marker = "PASS" if check["passed"] else "FAIL"
        lines.append(
            f"[{marker}] {check['name']}: {check['detail']}"
        )

    lines.extend(
        [
            "=" * 44,
            (
                "RESULT: ALL CORE CHECKS PASSED"
                if passed
                else "RESULT: ONE OR MORE CHECKS FAILED"
            ),
        ]
    )

    return passed, "\n".join(lines)
