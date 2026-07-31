"""Evidence-based generic task execution for Sophyane.

The execution engine runs TaskContract actions through a capability registry.
It never contains product-specific functions such as create_snake_game().
"""

from __future__ import annotations

import argparse
import html.parser
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sophyane.task_intelligence import (
    PlannedAction,
    TaskContract,
    understand_request,
)


CapabilityHandler = Callable[
    ["ExecutionContext", PlannedAction],
    "ActionResult",
]


@dataclass
class ActionResult:
    action_id: str
    capability: str
    ok: bool
    started_at: str
    finished_at: str
    duration_ms: float
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionReport:
    task_id: str
    goal: str
    worker: str
    workspace: str
    success: bool
    attempts: int
    actions: list[ActionResult]
    failed_action: str = ""
    failure: str = ""
    final_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionContext:
    contract: TaskContract
    repository_root: Path
    workspace: Path
    attempt: int
    state: dict[str, Any] = field(default_factory=dict)
    previous_failure: dict[str, Any] = field(default_factory=dict)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, CapabilityHandler] = {}

    def register(
        self,
        capability: str,
        handler: CapabilityHandler,
    ) -> None:
        if capability in self._handlers:
            raise ValueError(
                f"Capability already registered: {capability}"
            )

        self._handlers[capability] = handler

    def execute(
        self,
        context: ExecutionContext,
        action: PlannedAction,
    ) -> ActionResult:
        handler = self._handlers.get(action.capability)

        if handler is None:
            return failed_result(
                action,
                f"No executor is registered for {action.capability}.",
            )

        started_monotonic = time.monotonic()
        started_at = now_iso()

        try:
            result = handler(context, action)
        except Exception as error:
            return ActionResult(
                action_id=action.action_id,
                capability=action.capability,
                ok=False,
                started_at=started_at,
                finished_at=now_iso(),
                duration_ms=round(
                    (time.monotonic() - started_monotonic)
                    * 1000,
                    2,
                ),
                error=f"{type(error).__name__}: {error}",
            )

        result.duration_ms = round(
            (time.monotonic() - started_monotonic) * 1000,
            2,
        )
        result.started_at = started_at
        result.finished_at = now_iso()
        return result


class MarkupInspector(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.script_sources: list[str] = []
        self.inline_scripts: list[str] = []
        self.local_assets: list[str] = []
        self._inside_script = False
        self._script_buffer: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tags.append(tag)
        attributes = dict(attrs)

        if tag == "script":
            source = attributes.get("src")

            if source:
                self.script_sources.append(source)
                self._record_asset(source)
            else:
                self._inside_script = True
                self._script_buffer = []

        for attribute in ("href", "src"):
            value = attributes.get(attribute)

            if value:
                self._record_asset(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside_script:
            self.inline_scripts.append(
                "".join(self._script_buffer)
            )
            self._inside_script = False
            self._script_buffer = []

    def handle_data(self, data: str) -> None:
        if self._inside_script:
            self._script_buffer.append(data)

    def _record_asset(self, value: str) -> None:
        lowered = value.casefold()

        if (
            lowered.startswith(("http://", "https://", "data:", "#"))
            or lowered.startswith("javascript:")
            or value.startswith("//")
        ):
            return

        clean = value.split("?", 1)[0].split("#", 1)[0]

        if clean:
            self.local_assets.append(clean)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def successful_result(
    action: PlannedAction,
    evidence: dict[str, Any],
) -> ActionResult:
    timestamp = now_iso()

    return ActionResult(
        action_id=action.action_id,
        capability=action.capability,
        ok=True,
        started_at=timestamp,
        finished_at=timestamp,
        duration_ms=0.0,
        evidence=evidence,
    )


def failed_result(
    action: PlannedAction,
    error: str,
    evidence: dict[str, Any] | None = None,
) -> ActionResult:
    timestamp = now_iso()

    return ActionResult(
        action_id=action.action_id,
        capability=action.capability,
        ok=False,
        started_at=timestamp,
        finished_at=timestamp,
        duration_ms=0.0,
        evidence=evidence or {},
        error=error,
    )


def repository_root() -> Path:
    configured = os.environ.get(
        "SOPHYANE_REPOSITORY_ROOT",
        "",
    ).strip()

    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = Path.cwd().resolve()

    if not (root / "pyproject.toml").is_file():
        raise RuntimeError(
            f"Repository root is invalid: {root}"
        )

    return root


def resolve_workspace(
    root: Path,
    requested: str,
) -> Path:
    relative = Path(requested)

    if relative.is_absolute():
        raise ValueError(
            "Task workspaces must be repository-relative."
        )

    resolved = (root / relative).resolve()

    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "Task workspace escapes the repository."
        ) from error

    forbidden = {
        root,
        root / ".git",
        root / ".github",
        root / "src",
        root / "tests",
    }

    if resolved in forbidden:
        raise ValueError(
            f"Unsafe generated-task workspace: {resolved}"
        )

    return resolved


def list_workspace_files(
    workspace: Path,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not workspace.exists():
        return []

    files: list[dict[str, Any]] = []

    for path in sorted(
        workspace.rglob("*"),
        key=lambda item: str(item).casefold(),
    ):
        if len(files) >= limit:
            break

        if not path.is_file() or path.is_symlink():
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        files.append(
            {
                "path": str(path.relative_to(workspace)),
                "size": stat.st_size,
            }
        )

    return files


def capability_workspace_inspect(
    context: ExecutionContext,
    action: PlannedAction,
) -> ActionResult:
    existed = context.workspace.exists()
    files = list_workspace_files(context.workspace)

    context.state["workspace_existed"] = existed
    context.state["files_before"] = files

    return successful_result(
        action,
        {
            "workspace": str(context.workspace),
            "existed": existed,
            "files": files,
            "file_count": len(files),
        },
    )


def worker_environment_name(worker: str) -> str:
    normalized = worker.upper().replace("-", "_")

    if worker == "auto":
        return "SOPHYANE_ARTIFACT_WORKER_COMMAND"

    return f"SOPHYANE_{normalized}_COMMAND"


def resolve_worker_command(
    contract: TaskContract,
) -> tuple[list[str] | None, str]:
    worker = contract.requested_worker
    environment_name = worker_environment_name(worker)
    configured = os.environ.get(environment_name, "").strip()

    if configured:
        return shlex.split(configured), environment_name

    # Generic auto-worker may use a separately configured artifact command.
    if worker != "auto":
        fallback = os.environ.get(
            "SOPHYANE_ARTIFACT_WORKER_COMMAND",
            "",
        ).strip()

        if fallback:
            return (
                shlex.split(fallback),
                "SOPHYANE_ARTIFACT_WORKER_COMMAND",
            )

    return None, environment_name


def capability_worker_produce(
    context: ExecutionContext,
    action: PlannedAction,
) -> ActionResult:
    command, source = resolve_worker_command(
        context.contract
    )

    if not command:
        return failed_result(
            action,
            (
                "No artifact worker command is configured. "
                f"Set {source} to an executable that accepts a "
                "TaskContract JSON document on standard input and "
                "writes artifacts inside SOPHYANE_WORKSPACE."
            ),
            {
                "requested_worker":
                    context.contract.requested_worker,
                "expected_environment": source,
            },
        )

    context.workspace.mkdir(parents=True, exist_ok=True)

    task_payload = context.contract.to_dict()
    task_payload["attempt"] = context.attempt
    task_payload["previous_failure"] = (
        context.previous_failure
    )

    environment = os.environ.copy()
    environment.update(
        {
            "SOPHYANE_TASK_ID":
                context.contract.task_id,
            "SOPHYANE_TASK_GOAL":
                context.contract.goal,
            "SOPHYANE_TASK_KIND":
                context.contract.task_kind,
            "SOPHYANE_TASK_ATTEMPT":
                str(context.attempt),
            "SOPHYANE_WORKSPACE":
                str(context.workspace),
            "SOPHYANE_REPOSITORY_ROOT":
                str(context.repository_root),
        }
    )

    before = {
        item["path"]: item["size"]
        for item in list_workspace_files(
            context.workspace,
            limit=1000,
        )
    }

    started = time.monotonic()

    try:
        completed = subprocess.run(
            command,
            input=json.dumps(
                task_payload,
                ensure_ascii=False,
            ),
            cwd=str(context.repository_root),
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1, action.timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return failed_result(
            action,
            (
                f"Worker exceeded "
                f"{action.timeout_seconds} seconds."
            ),
            {
                "command": command,
                "command_source": source,
            },
        )
    except OSError as error:
        return failed_result(
            action,
            f"Worker could not start: {error}",
            {
                "command": command,
                "command_source": source,
            },
        )

    after_files = list_workspace_files(
        context.workspace,
        limit=1000,
    )
    after = {
        item["path"]: item["size"]
        for item in after_files
    }

    created = sorted(set(after) - set(before))
    changed = sorted(
        path
        for path in set(after).intersection(before)
        if after[path] != before[path]
    )

    evidence = {
        "command": command,
        "command_source": source,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-6000:],
        "stderr": (completed.stderr or "")[-3000:],
        "worker_duration_ms": round(
            (time.monotonic() - started) * 1000,
            2,
        ),
        "created_files": created,
        "changed_files": changed,
        "workspace_files": after_files,
    }

    context.state["worker_evidence"] = evidence

    if completed.returncode != 0:
        return failed_result(
            action,
            (
                "Artifact worker returned "
                f"{completed.returncode}."
            ),
            evidence,
        )

    if not created and not changed and not after_files:
        return failed_result(
            action,
            "Worker succeeded but produced no file evidence.",
            evidence,
        )

    return successful_result(action, evidence)


def find_entry_file(workspace: Path) -> Path | None:
    candidates = (
        workspace / "index.html",
        workspace / "public" / "index.html",
        workspace / "dist" / "index.html",
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    discovered = sorted(workspace.rglob("index.html"))

    return discovered[0] if discovered else None


def validate_javascript(
    scripts: list[tuple[str, str]],
) -> tuple[bool, list[dict[str, Any]]]:
    node = shutil.which("node")
    evidence: list[dict[str, Any]] = []

    if not scripts:
        return True, evidence

    if not node:
        return (
            False,
            [
                {
                    "ok": False,
                    "error": (
                        "Node.js is required for JavaScript "
                        "syntax validation."
                    ),
                }
            ],
        )

    all_valid = True

    with tempfile.TemporaryDirectory(
        prefix="sophyane-js-check-"
    ) as raw:
        directory = Path(raw)

        for index, (name, source) in enumerate(
            scripts,
            start=1,
        ):
            temporary = directory / f"script-{index}.js"
            temporary.write_text(
                source,
                encoding="utf-8",
            )

            completed = subprocess.run(
                [node, "--check", str(temporary)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                check=False,
            )

            item = {
                "source": name,
                "ok": completed.returncode == 0,
                "stdout":
                    (completed.stdout or "")[-1000:],
                "stderr":
                    (completed.stderr or "")[-1500:],
            }

            evidence.append(item)

            if not item["ok"]:
                all_valid = False

    return all_valid, evidence


def capability_validate_web(
    context: ExecutionContext,
    action: PlannedAction,
) -> ActionResult:
    entry = find_entry_file(context.workspace)

    if entry is None:
        return failed_result(
            action,
            "No index.html entry file was found.",
            {
                "workspace": str(context.workspace),
                "files": list_workspace_files(
                    context.workspace
                ),
            },
        )

    content = entry.read_text(
        encoding="utf-8",
        errors="replace",
    )

    lowered = content.casefold()
    structural_checks = {
        "doctype": "<!doctype html" in lowered,
        "html_close": "</html>" in lowered,
        "body_close": "</body>" in lowered,
        "nonempty": len(content.strip()) >= 100,
    }

    inspector = MarkupInspector()

    try:
        inspector.feed(content)
        parser_error = ""
    except Exception as error:
        parser_error = f"{type(error).__name__}: {error}"

    missing_assets: list[str] = []

    for asset in sorted(set(inspector.local_assets)):
        candidate = (entry.parent / asset).resolve()

        try:
            candidate.relative_to(context.workspace)
        except ValueError:
            missing_assets.append(
                f"{asset} (escapes workspace)"
            )
            continue

        if not candidate.is_file():
            missing_assets.append(asset)

    scripts: list[tuple[str, str]] = []

    for index, source in enumerate(
        inspector.inline_scripts,
        start=1,
    ):
        if source.strip():
            scripts.append(
                (f"inline-script-{index}", source)
            )

    for source in inspector.script_sources:
        if source.casefold().startswith(
            ("http://", "https://", "//")
        ):
            continue

        script_path = (entry.parent / source).resolve()

        if script_path.is_file():
            scripts.append(
                (
                    str(script_path.relative_to(
                        context.workspace
                    )),
                    script_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ),
                )
            )

    javascript_ok, javascript_evidence = (
        validate_javascript(scripts)
    )

    evidence = {
        "entry_file": str(entry),
        "size": entry.stat().st_size,
        "structural_checks": structural_checks,
        "parser_error": parser_error,
        "tags_seen": sorted(set(inspector.tags)),
        "missing_assets": missing_assets,
        "javascript": javascript_evidence,
    }

    context.state["entry_file"] = str(entry)
    context.state["validation"] = evidence

    if not all(structural_checks.values()):
        return failed_result(
            action,
            "HTML structural validation failed.",
            evidence,
        )

    if parser_error:
        return failed_result(
            action,
            "HTML parsing failed.",
            evidence,
        )

    if missing_assets:
        return failed_result(
            action,
            "Generated page references missing local assets.",
            evidence,
        )

    if not javascript_ok:
        return failed_result(
            action,
            "JavaScript syntax validation failed.",
            evidence,
        )

    return successful_result(action, evidence)


def choose_free_port(host: str) -> int:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def capability_http_start_server(
    context: ExecutionContext,
    action: PlannedAction,
) -> ActionResult:
    python_command = (
        shutil.which("python")
        or shutil.which("python3")
    )

    if not python_command:
        return failed_result(
            action,
            "Python HTTP server is unavailable.",
        )

    host = str(action.inputs.get("host") or "127.0.0.1")
    port = choose_free_port(host)
    log_path = (
        context.workspace
        / ".sophyane-http-server.log"
    )
    log_handle = log_path.open("ab")

    try:
        process = subprocess.Popen(
            [
                python_command,
                "-m",
                "http.server",
                str(port),
                "--bind",
                host,
                "--directory",
                str(context.workspace),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        log_handle.close()
        return failed_result(
            action,
            f"HTTP server could not start: {error}",
        )

    url = f"http://{host}:{port}/"

    context.state.update(
        {
            "server_process": process,
            "server_pid": process.pid,
            "server_log": str(log_path),
            "url": url,
        }
    )

    time.sleep(0.35)

    if process.poll() is not None:
        return failed_result(
            action,
            "HTTP server exited during startup.",
            {
                "pid": process.pid,
                "url": url,
                "log": str(log_path),
            },
        )

    return successful_result(
        action,
        {
            "pid": process.pid,
            "host": host,
            "port": port,
            "url": url,
            "log": str(log_path),
        },
    )


def capability_http_check(
    context: ExecutionContext,
    action: PlannedAction,
) -> ActionResult:
    url = str(context.state.get("url") or "")

    if not url:
        return failed_result(
            action,
            "No HTTP server URL is available.",
        )

    last_error = ""

    for attempt in range(1, 7):
        try:
            with urllib.request.urlopen(
                url,
                timeout=3,
            ) as response:
                status = int(response.status)
                body = response.read(4096)

            evidence = {
                "url": url,
                "status": status,
                "content_type":
                    response.headers.get(
                        "Content-Type",
                        "",
                    ),
                "bytes_sampled": len(body),
                "attempt": attempt,
            }

            context.state["http_evidence"] = evidence

            if 200 <= status < 400:
                return successful_result(
                    action,
                    evidence,
                )

            last_error = f"HTTP status {status}"
        except (
            OSError,
            urllib.error.URLError,
        ) as error:
            last_error = str(error)

        time.sleep(0.25)

    return failed_result(
        action,
        f"HTTP verification failed: {last_error}",
        {"url": url},
    )


def capability_browser_open(
    context: ExecutionContext,
    action: PlannedAction,
) -> ActionResult:
    url = str(context.state.get("url") or "")

    if not url:
        return failed_result(
            action,
            "No verified URL is available.",
        )

    commands: list[list[str]] = []

    termux_open = shutil.which("termux-open-url")

    if termux_open:
        commands.append([termux_open, url])

    am = shutil.which("am")

    if am:
        commands.append(
            [
                am,
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                url,
            ]
        )

    xdg_open = shutil.which("xdg-open")

    if xdg_open:
        commands.append([xdg_open, url])

    if not commands:
        return failed_result(
            action,
            "No supported browser-opening command exists.",
            {"url": url},
        )

    attempts: list[dict[str, Any]] = []

    for command in commands:
        try:
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
        except Exception as error:
            attempts.append(
                {
                    "command": command,
                    "ok": False,
                    "error":
                        f"{type(error).__name__}: {error}",
                }
            )
            continue

        item = {
            "command": command,
            "returncode": completed.returncode,
            "stdout":
                (completed.stdout or "")[-1000:],
            "stderr":
                (completed.stderr or "")[-1000:],
            "ok": completed.returncode == 0,
        }
        attempts.append(item)

        if item["ok"]:
            return successful_result(
                action,
                {
                    "url": url,
                    "attempts": attempts,
                },
            )

    return failed_result(
        action,
        "All browser-opening commands failed.",
        {
            "url": url,
            "attempts": attempts,
        },
    )


def default_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        "workspace.inspect",
        capability_workspace_inspect,
    )
    registry.register(
        "worker.produce_artifact",
        capability_worker_produce,
    )
    registry.register(
        "artifact.validate_web",
        capability_validate_web,
    )
    registry.register(
        "http.start_server",
        capability_http_start_server,
    )
    registry.register(
        "http.check",
        capability_http_check,
    )
    registry.register(
        "browser.open",
        capability_browser_open,
    )
    return registry


def dependencies_satisfied(
    action: PlannedAction,
    results: dict[str, ActionResult],
) -> bool:
    return all(
        dependency in results
        and results[dependency].ok
        for dependency in action.depends_on
    )


def stop_server(context: ExecutionContext) -> None:
    process = context.state.get("server_process")

    if process is None:
        return

    keep_server = os.environ.get(
        "SOPHYANE_KEEP_TASK_SERVER",
        "1",
    ).strip().casefold() not in {
        "0",
        "false",
        "no",
    }

    if keep_server:
        return

    try:
        process.terminate()
        process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def execute_contract(
    contract: TaskContract,
    *,
    registry: CapabilityRegistry | None = None,
    root: Path | None = None,
) -> ExecutionReport:
    resolved_root = (
        root.expanduser().resolve()
        if root is not None
        else repository_root()
    )
    workspace = resolve_workspace(
        resolved_root,
        contract.workspace,
    )
    selected_registry = registry or default_registry()

    all_results: list[ActionResult] = []
    previous_failure: dict[str, Any] = {}
    final_context: ExecutionContext | None = None

    for attempt in range(1, contract.max_attempts + 1):
        context = ExecutionContext(
            contract=contract,
            repository_root=resolved_root,
            workspace=workspace,
            attempt=attempt,
            previous_failure=previous_failure,
        )
        final_context = context
        current: dict[str, ActionResult] = {}
        failed_action = ""
        failure = ""

        for action in contract.actions:
            if not dependencies_satisfied(action, current):
                result = failed_result(
                    action,
                    "A required prior action did not succeed.",
                    {
                        "dependencies":
                            list(action.depends_on),
                    },
                )
                current[action.action_id] = result
                all_results.append(result)
                failed_action = action.action_id
                failure = result.error
                break

            result = selected_registry.execute(
                context,
                action,
            )
            current[action.action_id] = result
            all_results.append(result)

            if not result.ok:
                failed_action = action.action_id
                failure = result.error
                previous_failure = result.to_dict()
                break

        if not failed_action:
            return ExecutionReport(
                task_id=contract.task_id,
                goal=contract.goal,
                worker=contract.requested_worker,
                workspace=str(workspace),
                success=True,
                attempts=attempt,
                actions=all_results,
                final_url=str(
                    context.state.get("url") or ""
                ),
            )

        stop_server(context)

        # Read-only delivery steps cannot repair the artifact by retrying
        # themselves. A new attempt returns to the worker with the complete
        # previous failure as structured repair feedback.
        if failed_action not in {
            "produce",
            "validate",
            "http_check",
        }:
            break

    if final_context is not None:
        stop_server(final_context)

    last = all_results[-1] if all_results else None

    return ExecutionReport(
        task_id=contract.task_id,
        goal=contract.goal,
        worker=contract.requested_worker,
        workspace=str(workspace),
        success=False,
        attempts=(
            final_context.attempt
            if final_context is not None
            else 0
        ),
        actions=all_results,
        failed_action=(
            last.action_id if last else ""
        ),
        failure=(
            last.error
            if last
            else "No execution action was run."
        ),
        final_url=str(
            final_context.state.get("url") or ""
            if final_context is not None
            else ""
        ),
    )


def format_report(report: ExecutionReport) -> str:
    lines = [
        (
            "Task completed successfully."
            if report.success
            else "Task did not complete."
        ),
        f"Task: {report.task_id}",
        f"Goal: {report.goal}",
        f"Worker: {report.worker}",
        f"Workspace: {report.workspace}",
        f"Attempts: {report.attempts}",
    ]

    if report.final_url:
        lines.append(f"URL: {report.final_url}")

    lines.append("")
    lines.append("Evidence:")

    for result in report.actions:
        status = "PASS" if result.ok else "FAIL"
        lines.append(
            f"- {status} {result.capability} "
            f"({result.duration_ms:.0f} ms)"
        )

        if result.error:
            lines.append(f"  {result.error}")

    if report.failure:
        lines.extend(
            [
                "",
                f"Failure: {report.failure}",
            ]
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-execute",
        description=(
            "Understand and execute a task using generic "
            "evidence-based capabilities."
        ),
    )
    parser.add_argument("request", nargs="+")
    parser.add_argument(
        "--json",
        action="store_true",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
    )
    args = parser.parse_args(argv)

    request = " ".join(args.request)
    contract = understand_request(request)

    if args.plan_only:
        print(
            json.dumps(
                contract.to_dict(),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    report = execute_contract(contract)

    if args.json:
        print(
            json.dumps(
                report.to_dict(),
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(format_report(report))

    return 0 if report.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
