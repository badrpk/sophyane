"""VELA: Validated Execution and Learning Audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from sophyane.sli_learner import learn_execution
from sophyane.sli_schema import ensure_current_schema


def snapshot(root: Path) -> dict[str, str]:
    output: dict[str, str] = {}
    if not root.exists():
        return output
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            output[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            continue
    return output


def latest_workspace() -> Path | None:
    root = Path.home() / ".sophyane" / "workspaces"
    if not root.exists():
        return None
    workspaces = [path for path in root.iterdir() if path.is_dir()]
    return max(workspaces, key=lambda path: path.stat().st_mtime) if workspaces else None


def validate_workspace(workspace: Path) -> dict[str, Any]:
    started = time.monotonic()
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    workspace = workspace.expanduser().resolve()

    checks.append({"name": "workspace_exists", "passed": workspace.is_dir(), "detail": str(workspace)})
    if not workspace.is_dir():
        return {
            "ok": False,
            "workspace": str(workspace),
            "checks": checks,
            "errors": ["Workspace does not exist."],
            "files": {},
            "elapsed_seconds": time.monotonic() - started,
        }

    escaped_links: list[str] = []
    for path in workspace.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            resolved = path.resolve()
            if resolved != workspace and workspace not in resolved.parents:
                escaped_links.append(str(path.relative_to(workspace)))
        except OSError:
            escaped_links.append(str(path.relative_to(workspace)))
    checks.append({"name": "no_path_escape", "passed": not escaped_links, "detail": escaped_links})
    if escaped_links:
        errors.append("Workspace contains links escaping its root: " + ", ".join(escaped_links))

    files = snapshot(workspace)
    checks.append({"name": "artifact_exists", "passed": bool(files), "detail": f"{len(files)} file(s)"})
    if not files:
        errors.append("Workspace contains no files.")

    html = workspace / "index.html"
    if html.exists():
        source = html.read_text(encoding="utf-8", errors="replace")
        lowered = source.lower()
        html_checks = {
            "doctype": "<!doctype html" in lowered,
            "html_element": "<html" in lowered and "</html>" in lowered,
            "body_element": "<body" in lowered and "</body>" in lowered,
            "nonempty": bool(source.strip()),
        }
        for name, passed in html_checks.items():
            checks.append({"name": f"html_{name}", "passed": passed, "detail": str(html)})
            if not passed:
                errors.append(f"HTML check failed: {name}")

    checks.append({"name": "all_deterministic_checks", "passed": not errors, "detail": f"{len(checks)} checks"})
    return {
        "ok": not errors,
        "workspace": str(workspace),
        "checks": checks,
        "errors": errors,
        "files": files,
        "elapsed_seconds": time.monotonic() - started,
    }


def record_validation(*, report: dict[str, Any], request: str) -> dict[str, Any]:
    ensure_current_schema()
    workspace = Path(report["workspace"])
    status = "succeeded" if report["ok"] else "failed"
    result = json.dumps(
        {"validator": "VELA", "checks": report["checks"], "errors": report["errors"]},
        ensure_ascii=False,
    )
    return learn_execution(
        trace_id="vela-" + uuid.uuid4().hex[:12],
        request=request,
        workspace_before={},
        workspace_after=snapshot(workspace),
        status=status,
        reward=1.0 if report["ok"] else -1.0,
        result=result,
        elapsed_seconds=float(report.get("elapsed_seconds") or 0.0),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-vela",
        description="VELA — deterministic workspace validation with SLI learning.",
    )
    parser.add_argument("workspace", nargs="?", help="Workspace to validate; defaults to the latest Sophyane project.")
    parser.add_argument("--record", action="store_true", help="Record the validation outcome in SLI.")
    parser.add_argument("--json", action="store_true", help="Print the complete report as JSON.")
    parser.add_argument("--request", default="VELA validate workspace")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace) if args.workspace else latest_workspace()
    if workspace is None:
        print("VELA: no Sophyane workspace found.")
        return 2

    report = validate_workspace(workspace)
    if args.record:
        try:
            report["learning"] = record_validation(report=report, request=args.request)
        except Exception as error:  # noqa: BLE001
            report["learning_error"] = f"{type(error).__name__}: {error}"
            report["ok"] = False

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"VELA {'PASS' if report['ok'] else 'FAIL'}")
        print(f"Workspace: {report['workspace']}")
        for check in report["checks"]:
            print(f"  {'PASS' if check['passed'] else 'FAIL':4}  {check['name']}: {check['detail']}")
        if report.get("learning"):
            learned = report["learning"]
            print(f"SLI recorded: quality_reward={float(learned.get('quality_reward', 0.0)):+.2f}")
        for error in report["errors"]:
            print(f"  - {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
