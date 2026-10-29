"""Codane-backed routing for Sophyane repository coding requests.

Codane owns the agent process and orchestration policy.  Sophyane only decides
whether a request belongs on that backend and supplies the isolated workspace.
"""
from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


_BROWSER_TERMS = (
    "browser",
    "web page",
    "website url",
    "open the page",
    "inspect the page",
)
_CODING_TERMS = (
    "code",
    "repository",
    "repo",
    "file",
    "bug",
    "fix",
    "implement",
    "modify",
    "edit",
    "patch",
    "refactor",
    "build",
    "compile",
    "test",
    "pytest",
    "ctest",
    "feature",
    "function",
    "class",
    "api",
    "app",
    "application",
    "game",
    "program",
    "project",
    "script",
    "web app",
    "website",
)
_MUTATION_TERMS = (
    "fix",
    "implement",
    "modify",
    "edit",
    "patch",
    "refactor",
    "add",
    "remove",
    "create",
    "write",
    "change",
    "update",
    "build",
    "vibe code",
)


class CodaneInvocationError(RuntimeError):
    """A coding request could not be handed to Codane."""


@dataclass(frozen=True)
class CodaneResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    graph_path: Path
    run_id: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def as_text(self) -> str:
        status = "succeeded" if self.ok else "failed"
        visible_stdout: list[str] = []
        event_count = 0
        for line in self.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                visible_stdout.append(line)
                continue
            if isinstance(event, dict) and event.get("event_type"):
                event_count += 1
            else:
                visible_stdout.append(line)
        parts = [
            f"Codane {status} (exit_code={self.exit_code})",
            "STAGE_PIPELINE_ACCEPTED" if self.ok else "STAGE_PIPELINE_FAILED",
        ]
        if self.run_id:
            parts.append(f"Codane run id: {self.run_id}")
            if not self.ok:
                parts.append(f"Resume with: codane resume {self.run_id} --provider codex")
        if event_count:
            parts.append(f"{event_count} structured Codane events captured")
        if self.stdout_truncated:
            parts.append("stdout truncated at the configured capture limit")
        if self.stderr_truncated:
            parts.append("stderr truncated at the configured capture limit")
        if visible_stdout:
            parts.append(f"STDOUT:\n{chr(10).join(visible_stdout).strip()}")
        if self.stderr.strip():
            parts.append(f"STDERR:\n{self.stderr.strip()}")
        return "\n\n".join(parts)


def is_repository_coding_request(request: str) -> bool:
    """Return true only for requests that ask Sophyane to change/test code."""
    text = str(request or "").strip().lower()
    if not text or any(term in text for term in _BROWSER_TERMS):
        return False
    has_coding = any(term in text for term in _CODING_TERMS)
    has_mutation_or_test = any(term in text for term in _MUTATION_TERMS) or any(
        term in text for term in ("run tests", "run ctest", "run pytest", "verify tests")
    )
    return has_coding and has_mutation_or_test


def select_verification_command(workspace: Path, request: str) -> list[str] | None:
    """Choose a known test runner without interpreting user text as a command."""
    workspace = workspace.expanduser().resolve()
    text = str(request or "").lower()
    if (workspace / "CMakeLists.txt").is_file() and any(
        term in text for term in ("test", "ctest", "verify", "build")
    ):
        return ["ctest", "--test-dir", "build", "--output-on-failure"]
    if any((workspace / name).is_file() for name in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg")):
        if any(term in text for term in ("test", "pytest", "verify", "check")):
            return [sys.executable, "-m", "pytest", "-q"]
    if (workspace / "package.json").is_file() and any(
        term in text for term in ("test", "verify", "check")
    ):
        return ["npm", "test"]
    return None


def build_coding_graph(request: str, *, workspace: Path) -> dict[str, object]:
    workspace = workspace.expanduser().resolve()
    stage_dir = workspace / ".codane" / "stages"
    common = f"Workspace: {workspace}\nUser request: {request}\n"
    verification = select_verification_command(workspace, request)
    if verification is None:
        verify_node: dict[str, object] = {
            "id": "verify",
            "type": "agent",
            "depends_on": ["implement"],
            "prompt": common + (
                "You are the verification stage. Inspect the implemented diff and run the safest available "
                "repository tests. Write .codane/stages/verification.md with the commands and exact results. "
                "If no test runner is available, state that explicitly; never invent a shell command."
            ),
        }
    else:
        verify_node = {
            "id": "verify",
            "type": "command",
            "depends_on": ["implement"],
            "command": verification,
            "command_in_workspace": True,
        }
    review_node: dict[str, object] = {
        "id": "review",
        "type": "agent",
        "depends_on": ["verify"],
        "allow_failed_dependencies": True,
        "prompt": common + (
            "You are the review stage. Inspect the actual Git diff and verification evidence. Check "
            "correctness, regressions, tests, and scope. If acceptable, write "
            ".codane/stages/review.md whose first line is exactly REVIEW_ACCEPTED. If not acceptable, "
            "write REVIEW_REJECTED followed by precise repair instructions."
        ),
    }
    if verification is not None:
        review_node["artifact_inputs"] = [
            {"from": "verify", "path": "stdout.txt"},
            {"from": "verify", "path": "stderr.txt"},
        ]
    return {
        "name": "sophyane-coding",
        "max_parallel": 1,
        "fail_fast": False,
        "nodes": [
            {
                "id": "context",
                "type": "agent",
                "prompt": common + (
                    "You are the repository-understanding stage. Inspect manifests, relevant source, tests, "
                    "and current Git state. Write a concise implementation brief to "
                    ".codane/stages/context.md. Do not modify product code."
                ),
            },
            {
                "id": "implement",
                "type": "agent",
                "depends_on": ["context"],
                "prompt": common + (
                    "You are the implementation stage. Read .codane/stages/context.md, make the requested "
                    "code changes in the workspace, and do not merely describe a patch. Keep changes focused."
                ),
            },
            verify_node,
            review_node,
            {
                "id": "repair",
                "type": "agent",
                "depends_on": ["review"],
                "prompt": common + (
                    "You are the single bounded repair stage. Read .codane/stages/review.md. If its first "
                    "line is REVIEW_REJECTED, fix only the listed defects, rerun the relevant verification, "
                    "and rewrite the report with REVIEW_ACCEPTED when the defects are fixed. If it is already "
                    "REVIEW_ACCEPTED, make no product changes and state that no repair was needed. Do not retry "
                    "or broaden scope beyond this one bounded repair."
                ),
            },
            {
                "id": "accept",
                "type": "command",
                "depends_on": ["repair"],
                "command": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; p=Path('.codane/stages/review.md'); assert p.is_file() and p.read_text(encoding='utf-8').splitlines()[0] == 'REVIEW_ACCEPTED'",
                ],
                "command_in_workspace": True,
            },
        ],
    }


def _default_executable() -> list[str]:
    configured = os.environ.get("CODANE_BIN", "").strip()
    if configured:
        return [configured]
    built = Path("/data/data/com.termux/files/home/Codane/Codane/build/codane")
    if built.is_file() and os.access(built, os.X_OK):
        return [str(built)]
    found = shutil.which("codane")
    return [found or "codane"]


class CodaneBackend:
    """Invoke Codane with Codex as the explicit agent provider."""

    def __init__(
        self,
        executable: Sequence[str] | str | None = None,
        *,
        timeout: int = 1800,
        max_capture: int = 64_000,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        if executable is None:
            self.executable = _default_executable()
        elif isinstance(executable, str):
            self.executable = [executable]
        else:
            self.executable = [str(item) for item in executable]
        self.timeout = max(1, int(timeout))
        self.max_capture = max(1024, int(max_capture))
        self.progress = progress

    def run(self, request: str, *, workspace: Path) -> CodaneResult:
        workspace = workspace.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        executable = self.executable[0] if self.executable else ""
        if not executable or (os.path.sep in executable and not Path(executable).is_file()):
            raise CodaneInvocationError(f"Codane executable not found: {executable or '<empty>'}")
        request_dir = workspace / ".codane" / "requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        graph_path = request_dir / f"sophyane-{uuid.uuid4().hex}.json"
        graph_path.write_text(
            json.dumps(build_coding_graph(request, workspace=workspace), ensure_ascii=False),
            encoding="utf-8",
        )
        argv = [*self.executable, "--events-json", "run", str(graph_path), "--provider", "codex"]
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_size = [0]
        stderr_size = [0]
        stdout_truncated = [False]
        stderr_truncated = [False]
        run_ids: list[str] = []

        def capture_line(lines: list[str], size: list[int], truncated: list[bool], line: str) -> None:
            remaining = self.max_capture - size[0]
            if remaining <= 0:
                truncated[0] = True
                return
            kept = line[:remaining]
            lines.append(kept)
            size[0] += len(kept)
            if len(kept) < len(line):
                truncated[0] = True

        def emit_event(line: str) -> None:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return
            if not isinstance(event, dict):
                return
            event_type = str(event.get("event_type", "event"))
            if event_type == "run_started" and event.get("run_id"):
                run_ids.append(str(event["run_id"]))
            if self.progress is None:
                return
            node_id = str(event.get("node_id", "")).strip()
            label = f"{event_type}:{node_id}" if node_id else event_type
            try:
                self.progress(label)
            except Exception:  # noqa: BLE001
                # UI progress must never break the coding process.
                return

        def read_stdout(stream: object) -> None:
            for line in stream:  # type: ignore[union-attr]
                text = str(line)
                capture_line(stdout_lines, stdout_size, stdout_truncated, text)
                emit_event(text.strip())

        def read_stderr(stream: object) -> None:
            for line in stream:  # type: ignore[union-attr]
                capture_line(stderr_lines, stderr_size, stderr_truncated, str(line))

        def stop_process(process: subprocess.Popen[str]) -> None:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    return
                except (ProcessLookupError, OSError):
                    pass
            process.kill()

        try:
            process = subprocess.Popen(
                argv,
                cwd=workspace,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                start_new_session=os.name != "nt",
            )
            if process.stdin is not None:
                process.stdin.close()
            stdout_thread = threading.Thread(target=read_stdout, args=(process.stdout,), daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, args=(process.stderr,), daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            try:
                returncode = process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired as error:
                stop_process(process)
                process.wait()
                stdout_thread.join()
                stderr_thread.join()
                run_hint = f"; run id: {run_ids[-1]}" if run_ids else ""
                raise CodaneInvocationError(
                    f"Codane timed out after {self.timeout}s: {executable}{run_hint}"
                ) from error
            except BaseException:
                stop_process(process)
                process.wait()
                stdout_thread.join()
                stderr_thread.join()
                raise
            stdout_thread.join()
            stderr_thread.join()
        except FileNotFoundError as error:
            raise CodaneInvocationError(f"Codane executable not found: {executable}") from error
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        return CodaneResult(
            returncode == 0,
            returncode,
            stdout,
            stderr,
            graph_path,
            run_ids[-1] if run_ids else None,
            stdout_truncated[0],
            stderr_truncated[0],
        )
