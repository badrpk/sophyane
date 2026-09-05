"""Persistent interactive learning loop for Sophyane SLI.

Each user instruction is processed through the existing SLI router. Successful
artifacts are validated, ingested into code memory, reinforced, and recorded.
The loop runs until Ctrl+C, EOF, /quit or /exit.

No local or cloud LLM fallback is enabled by this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import sys
import time
import traceback

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


Progress = Callable[[str], None]

STATE_ROOT = (
    Path.home()
    / ".local/share/sophyane/continuous_sli"
)

RUNS_ROOT = STATE_ROOT / "runs"
EVENTS_FILE = STATE_ROOT / "events.jsonl"
CURRENT_LINK = STATE_ROOT / "current"

SUPPORTED_ARTIFACT_SUFFIXES = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".json",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
}

FAILURE_MARKERS = {
    "success: false",
    "family unavailable",
    "failed validation",
    "acquisition failed",
    "composition failed",
    "could not find compatible",
    "did not meet",
    "no relevant html",
    "no valid",
    "unsupported",
    "traceback",
}

SUCCESS_MARKERS = {
    "success: true",
    "validation: passed",
    "smoke test: passed",
    "grounded contract smoke test: passed",
    "artifact validation passed",
}


@dataclass
class RunEvent:
    run_id: str
    request: str
    workspace: str
    started_at: float
    finished_at: float
    elapsed_seconds: float
    success: bool
    report: str
    files: list[str]
    bytes_generated: int
    chunks_before: int
    chunks_after: int
    chunks_learned: int
    learned_chunk_ids: list[str]
    error: str | None = None


def _normalise(value: str) -> str:
    return " ".join(
        str(value or "").strip().split()
    )


def _slug(value: str, limit: int = 58) -> str:
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value or "").lower(),
    ).strip("-")

    return slug[:limit].rstrip("-") or "instruction"


def _run_id(request: str) -> str:
    timestamp = time.strftime(
        "%Y%m%d-%H%M%S"
    )

    digest = hashlib.sha256(
        (
            request
            + "\0"
            + str(time.time_ns())
        ).encode("utf-8")
    ).hexdigest()[:8]

    return (
        f"{timestamp}-"
        f"{_slug(request)}-"
        f"{digest}"
    )


def _append_jsonl(
    path: Path,
    record: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write(
            json.dumps(
                record,
                ensure_ascii=False,
            )
            + "\n"
        )


def _write_text(
    path: Path,
    value: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        str(value),
        encoding="utf-8",
    )


def _set_current_workspace(
    workspace: Path,
) -> None:
    STATE_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = STATE_ROOT / ".current.tmp"

    temporary.unlink(
        missing_ok=True,
    )

    try:
        temporary.symlink_to(
            workspace,
            target_is_directory=True,
        )

        os.replace(
            temporary,
            CURRENT_LINK,
        )

    except OSError:
        temporary.unlink(
            missing_ok=True,
        )

        _write_text(
            STATE_ROOT / "current.txt",
            str(workspace),
        )


def _artifact_files(
    workspace: Path,
) -> list[Path]:
    files = []

    if not workspace.is_dir():
        return files

    for path in workspace.rglob("*"):
        if not path.is_file():
            continue

        if any(
            part.startswith(".")
            and part not in {".well-known"}
            for part in path.relative_to(
                workspace
            ).parts
        ):
            continue

        if path.suffix.lower() not in SUPPORTED_ARTIFACT_SUFFIXES:
            continue

        try:
            size = path.stat().st_size
        except OSError:
            continue

        if size <= 0 or size > 5_000_000:
            continue

        files.append(path)

    files.sort(
        key=lambda path:
            str(
                path.relative_to(workspace)
            )
    )

    return files


def _artifact_is_credible(
    workspace: Path,
    report: str,
) -> tuple[bool, list[Path], list[str]]:
    files = _artifact_files(
        workspace
    )

    issues: list[str] = []
    low_report = str(
        report or ""
    ).lower()

    explicit_failure = any(
        marker in low_report
        for marker in FAILURE_MARKERS
    )

    explicit_success = any(
        marker in low_report
        for marker in SUCCESS_MARKERS
    )

    if explicit_failure:
        issues.append(
            "report contains a failure marker"
        )

    if not files:
        issues.append(
            "no supported artifact files"
        )

    browser_files = [
        path
        for path in files
        if path.suffix.lower()
        in {".html", ".htm"}
    ]

    for browser_file in browser_files:
        source = browser_file.read_text(
            encoding="utf-8",
            errors="replace",
        ).lower()

        if not (
            "<html" in source
            and "<body" in source
            and "</html>" in source
        ):
            issues.append(
                f"incomplete HTML: {browser_file.name}"
            )

        unfinished = [
            marker
            for marker in (
                "todo: implement",
                "not implemented",
                "your code here",
                "coming soon",
                "lorem ipsum",
            )
            if marker in source
        ]

        if unfinished:
            issues.append(
                f"unfinished HTML {browser_file.name}: "
                + ", ".join(unfinished)
            )

    python_files = [
        path
        for path in files
        if path.suffix.lower() == ".py"
    ]

    if python_files:
        import py_compile

        for python_file in python_files:
            try:
                py_compile.compile(
                    str(python_file),
                    doraise=True,
                )
            except Exception as error:
                issues.append(
                    f"Python compile failure "
                    f"{python_file.name}: {error}"
                )

    success = (
        bool(files)
        and not issues
        and (
            explicit_success
            or not explicit_failure
        )
    )

    return success, files, issues


def _learn_successful_workspace(
    request: str,
    workspace: Path,
    *,
    progress: Progress,
) -> tuple[int, int, list[str]]:
    from sophyane.code_memory.acquire import (
        acquire_tree,
    )
    from sophyane.code_memory.learner import (
        apply_outcome,
    )
    from sophyane.code_memory.store import (
        ChunkStore,
    )

    before_store = ChunkStore()
    before_ids = set(
        before_store.ids
    )
    before_count = len(
        before_ids
    )

    source_id = hashlib.sha256(
        request.encode("utf-8")
    ).hexdigest()[:16]

    report = acquire_tree(
        workspace,
        limit_files=300,
        limit_chunks=1_500,
        source=(
            "continuous-generated:"
            + source_id
        ),
        progress=progress,
    )

    progress(
        "SLI learning ingest: "
        + str(report)
    )

    after_store = ChunkStore()
    after_ids = set(
        after_store.ids
    )

    learned_ids = sorted(
        after_ids - before_ids
    )

    if learned_ids:
        apply_outcome(
            after_store,
            learned_ids,
            success=True,
            strength=0.20,
        )

    return (
        before_count,
        len(after_ids),
        learned_ids,
    )


def _preview(
    workspace: Path,
    *,
    progress: Progress,
) -> str:
    if os.environ.get(
        "SOPHYANE_CONTINUOUS_AUTO_PREVIEW",
        "1",
    ).strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return (
            "Automatic preview disabled."
        )

    if not (
        workspace / "index.html"
    ).is_file():
        return (
            "No browser artifact to preview."
        )

    try:
        from sophyane.sli_capability_engine import (
            preview_sli_artifact,
        )

        return str(
            preview_sli_artifact(
                workspace,
                progress=progress,
            )
        )

    except Exception as error:
        return (
            "Preview warning: "
            f"{type(error).__name__}: {error}"
        )


def _latest_events(
    limit: int = 10,
) -> list[dict]:
    if not EVENTS_FILE.is_file():
        return []

    records = []

    for line in EVENTS_FILE.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        if not line.strip():
            continue

        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        records.append(record)

    return records[-limit:]


def _print_status() -> None:
    from sophyane.code_memory.store import (
        ChunkStore,
    )

    store = ChunkStore()
    events = _latest_events(
        limit=1,
    )

    print()
    print("Continuous SLI status")
    print("─────────────────────")
    print(
        "Memory chunks :",
        len(store.ids),
    )
    print(
        "Runs recorded :",
        len(
            _latest_events(
                limit=1_000_000
            )
        ),
    )
    print(
        "Runs root     :",
        RUNS_ROOT,
    )

    if events:
        latest = events[-1]

        print(
            "Last request  :",
            latest.get(
                "request",
                "",
            ),
        )
        print(
            "Last success  :",
            latest.get(
                "success",
                False,
            ),
        )
        print(
            "Last learned  :",
            latest.get(
                "chunks_learned",
                0,
            ),
        )

    print()


def _print_history() -> None:
    events = _latest_events(
        limit=12,
    )

    print()

    if not events:
        print(
            "No continuous SLI runs recorded."
        )
        print()
        return

    print("Recent continuous SLI runs")
    print("──────────────────────────")

    for event in events:
        marker = (
            "✓"
            if event.get("success")
            else "✗"
        )

        print(
            f"{marker} "
            f"{event.get('run_id', '')}  "
            f"learned={event.get('chunks_learned', 0)}  "
            f"{event.get('request', '')}"
        )

    print()


def execute_instruction(
    request: str,
    *,
    progress: Progress | None = None,
) -> RunEvent:
    from sophyane.sli_chunk_router import (
        try_sli_chunks,
    )

    progress = progress or (
        lambda message:
            print(
                f"[SLI] {message}",
                flush=True,
            )
    )

    request = _normalise(
        request
    )

    run_id = _run_id(
        request
    )

    workspace = (
        RUNS_ROOT
        / run_id
    )

    workspace.mkdir(
        parents=True,
        exist_ok=False,
    )

    _set_current_workspace(
        workspace
    )

    _write_text(
        workspace / "request.txt",
        request + "\n",
    )

    started = time.time()
    report = ""
    success = False
    error_text = None
    files: list[Path] = []
    learned_ids: list[str] = []
    chunks_before = 0
    chunks_after = 0

    try:
        report = str(
            try_sli_chunks(
                request,
                workspace=workspace,
                progress=progress,
            )
        )

        success, files, issues = (
            _artifact_is_credible(
                workspace,
                report,
            )
        )

        if issues:
            report += (
                "\nContinuous-loop validation: "
                + "; ".join(issues)
            )

        if success:
            (
                chunks_before,
                chunks_after,
                learned_ids,
            ) = _learn_successful_workspace(
                request,
                workspace,
                progress=progress,
            )

            report += (
                "\nContinuous-loop learning: "
                f"{len(learned_ids)} new chunks promoted."
            )

            preview_report = _preview(
                workspace,
                progress=progress,
            )

            if preview_report:
                report += (
                    "\n" + preview_report
                )

    except KeyboardInterrupt:
        raise

    except Exception as error:
        success = False
        error_text = (
            f"{type(error).__name__}: {error}"
        )

        report = (
            report
            + "\nContinuous-loop execution error: "
            + error_text
        ).strip()

        _write_text(
            workspace
            / "traceback.txt",
            traceback.format_exc(),
        )

    finished = time.time()

    files = _artifact_files(
        workspace
    )

    relative_files = [
        str(
            path.relative_to(
                workspace
            )
        )
        for path in files
    ]

    bytes_generated = sum(
        path.stat().st_size
        for path in files
    )

    event = RunEvent(
        run_id=run_id,
        request=request,
        workspace=str(workspace),
        started_at=started,
        finished_at=finished,
        elapsed_seconds=round(
            finished - started,
            3,
        ),
        success=success,
        report=report,
        files=relative_files,
        bytes_generated=bytes_generated,
        chunks_before=chunks_before,
        chunks_after=chunks_after,
        chunks_learned=len(
            learned_ids
        ),
        learned_chunk_ids=learned_ids,
        error=error_text,
    )

    _write_text(
        workspace / "report.txt",
        report.rstrip() + "\n",
    )

    _write_text(
        workspace / "event.json",
        json.dumps(
            asdict(event),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )

    _append_jsonl(
        EVENTS_FILE,
        asdict(event),
    )

    return event


def run_continuous_sli_loop() -> int:
    os.environ[
        "SOPHYANE_SESSION_MODE"
    ] = "sli_chunks"

    os.environ[
        "SOPHYANE_SLI_ONLY"
    ] = "1"

    os.environ[
        "SOPHYANE_SLI_CONTINUOUS"
    ] = "1"

    RUNS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print(
        "◆ Continuous SLI learning loop"
    )
    print(
        "  Every successful instruction is generated, "
        "validated, ingested and reinforced."
    )
    print(
        "  Commands: /status, /history, /preview, "
        "/workspace, /help, /quit"
    )
    print(
        "  Press Ctrl+C at any time to stop."
    )
    print()

    while True:
        try:
            request = input(
                "SLI learn ❯ "
            ).strip()

        except EOFError:
            print(
                "\nContinuous SLI loop ended."
            )
            return 0

        except KeyboardInterrupt:
            print(
                "\nContinuous SLI loop stopped."
            )
            return 130

        if not request:
            continue

        command = request.lower()

        if command in {
            "/quit",
            "/exit",
            "quit",
            "exit",
        }:
            print(
                "Continuous SLI loop ended."
            )
            return 0

        if command == "/status":
            _print_status()
            continue

        if command == "/history":
            _print_history()
            continue

        if command == "/workspace":
            print(
                CURRENT_LINK
                if CURRENT_LINK.exists()
                else "No current workspace."
            )
            continue

        if command.startswith("/ask "):
            # Explicit read-only harness access to learned episodic context.
            from sophyane.durable_memory import recall

            question = request[5:].strip()
            hits = recall(question, limit=3) if question else []
            if hits:
                print("\n".join(str(item.get("content") or "") for item in hits))
            else:
                print("No learned context matched this question.")
            continue

        if command == "/preview":
            events = _latest_events(
                limit=1,
            )

            if not events:
                print(
                    "No previous run to preview."
                )
                continue

            workspace = Path(
                events[-1]["workspace"]
            )

            print(
                _preview(
                    workspace,
                    progress=lambda message:
                        print(
                            f"[SLI] {message}"
                        ),
                )
            )

            continue

        if command == "/help":
            print(
                "\nEnter any build instruction.\n"
                "/status    memory and latest run\n"
                "/history   recent learning runs\n"
                "/workspace latest workspace\n"
                "/ask       query learned episodic context\n"
                "/preview   preview latest index.html\n"
                "/quit      stop the loop\n"
            )
            continue

        print()
        print(
            "─" * 72
        )
        print(
            "Instruction:",
            request,
        )
        print(
            "─" * 72
        )

        try:
            event = execute_instruction(
                request
            )

        except KeyboardInterrupt:
            print(
                "\nCurrent instruction cancelled. "
                "Continuous SLI loop stopped."
            )
            return 130

        print()
        print(
            event.report
        )
        print()
        print(
            "Run summary"
        )
        print(
            "───────────"
        )
        print(
            "Success       :",
            event.success,
        )
        print(
            "Files         :",
            len(event.files),
        )
        print(
            "Bytes         :",
            event.bytes_generated,
        )
        print(
            "Chunks learned:",
            event.chunks_learned,
        )
        print(
            "Workspace     :",
            event.workspace,
        )
        print()



# SOPHYANE_FRESH_PREVIEW_GUARD_V1
#
# Intermediate composers must not open stale output. Only the final successful
# workspace may be previewed, through a verified no-cache server.

_execute_instruction_before_fresh_preview = execute_instruction


def _preview(
    workspace: Path,
    *,
    progress: Progress,
) -> str:
    from sophyane.code_memory.fresh_preview import (
        preview_workspace,
    )

    return preview_workspace(
        Path(workspace),
        progress=progress,
        open_browser=True,
    )


def execute_instruction(
    request: str,
    *,
    progress: Progress | None = None,
) -> RunEvent:
    saved = {
        name: os.environ.get(name)
        for name in (
            "SOPHYANE_DISABLE_BROWSER_OPEN",
            "SOPHYANE_NO_AUTO_OPEN",
            "SOPHYANE_BROWSER_PREVIEW",
            "BROWSER",
        )
    }

    # Block every intermediate attempt from opening a browser.
    os.environ["SOPHYANE_DISABLE_BROWSER_OPEN"] = "1"
    os.environ["SOPHYANE_NO_AUTO_OPEN"] = "1"
    os.environ["SOPHYANE_BROWSER_PREVIEW"] = "0"
    os.environ["BROWSER"] = "/bin/false"

    try:
        event = _execute_instruction_before_fresh_preview(
            request,
            progress=progress,
        )

    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # The old function may have attempted preview while browser opening was
    # suppressed. Preview again only when this run is genuinely successful.
    if event.success:
        workspace = Path(event.workspace)
        artifact = workspace / "index.html"

        if artifact.is_file():
            preview_report = _preview(
                workspace,
                progress=(
                    progress
                    or (
                        lambda message:
                            print(
                                f"[SLI] {message}",
                                flush=True,
                            )
                    )
                ),
            )

            if preview_report not in event.report:
                event.report = (
                    event.report.rstrip()
                    + "\n"
                    + preview_report
                )

    return event

def main() -> int:
    return run_continuous_sli_loop()


if __name__ == "__main__":
    raise SystemExit(main())

# SOPHYANE_PRODUCT_ARTIFACT_FILTER_V1
#
# request.txt, reports and audit records are run metadata—not generated
# products. They must never make a failed instruction appear to have output.

_artifact_files_before_product_filter = _artifact_files

_SLI_CONTROL_FILES = {
    "request.txt",
    "report.txt",
    "event.json",
    "traceback.txt",
}


def _artifact_files(workspace: Path) -> list[Path]:
    files = _artifact_files_before_product_filter(
        Path(workspace)
    )

    output = []

    for path in files:
        try:
            relative = path.relative_to(
                workspace
            )
        except ValueError:
            continue

        if relative.name in _SLI_CONTROL_FILES:
            continue

        if any(
            part in {
                "__pycache__",
                ".git",
                ".sophyane",
            }
            for part in relative.parts
        ):
            continue

        output.append(path)

    return output
