"""Provider-driven adaptive execution for Sophyane.

Application code always comes from the configured provider. This module only adapts
model output into safe workspace artifacts, execution and mechanical verification.
"""
from __future__ import annotations

from sophyane.environment_constraints import verification_result_is_meaningful

import re
import shlex
import sys
import shutil
from pathlib import Path
from typing import Any, Callable


def _files(workspace: Path) -> list[str]:
    return [str(p.relative_to(workspace)) for p in sorted(workspace.rglob("*")) if p.is_file()]


def _browser_request(request: str) -> bool:
    text = request.lower()
    return any(word in text for word in ("browser", "website", "web app", "html", "game", "design", "touch controls"))


def _extract_html(text: str) -> str | None:
    value = text.strip()
    fenced = re.search(r"```(?:html)?\s*(<!doctype html.*?</html>)\s*```", value, re.I | re.S)
    if fenced:
        value = fenced.group(1).strip()
    else:
        lower = value.lower()
        start = lower.find("<!doctype html")
        if start < 0:
            start = lower.find("<html")
        end = lower.rfind("</html>")
        if start >= 0 and end > start:
            value = value[start : end + len("</html>")]
    lower = value.lower()
    if ("<!doctype html" in lower or "<html" in lower) and "</html>" in lower:
        return value
    return None


def _extract_partial_html(text: str) -> str | None:
    """Recover an unfinished HTML document emitted by a token-limited provider."""
    value = (text or "").strip()
    lower = value.lower()
    start = lower.find("<!doctype html")
    if start < 0:
        start = lower.find("<html")
    if start < 0:
        return None
    value = value[start:]
    value = re.sub(r"\s*```\s*$", "", value, flags=re.S)
    # Providers may be truncated immediately after opening a script, string,
    # or element. Preserve any meaningful HTML prefix for bounded recovery.
    return value.strip() if len(value.strip()) >= 20 else None


def _raw_html_prompt(original_request: str, existing: str = "") -> str:
    if existing:
        return (
            "Rewrite this existing browser project as ONE complete self-contained index.html. "
            "Apply the requested change, preserve working features, include CSS and JavaScript inline, and output raw HTML only. "
            "No JSON, markdown, explanation, shell commands, cd, or make. Keep code compact.\n"
            f"CHANGE: {original_request[-240:]}\nEXISTING HTML:\n{existing[:1800]}"
        )
    return (
        "Create ONE compact self-contained index.html for the request. Put CSS and JavaScript inline. "
        "Use no external files, images, libraries, or fonts. Output raw HTML only, beginning <!doctype html> and ending </html>. "
        "Close every script and body tag. No JSON, markdown, explanation, shell commands, cd, or make. "
        "Prefer short variable names and compact code.\n"
        f"REQUEST: {original_request[-360:]}"
    )


def _html_continuation_prompt(partial: str, problem: str = "") -> str:
    tail = partial[-1600:]
    issue = f" The current structural problem is: {problem}." if problem else ""
    return (
        "Continue the unfinished index.html from exactly after its final character."
        f"{issue} Output ONLY missing JavaScript/HTML; never repeat earlier code or opening tags. "
        "Complete the current function and game loop, close every open brace, then close </script>, </body>, and </html>. "
        "End immediately after </html>. No markdown or explanation.\n"
        f"FINAL TAIL:\n{tail}"
    )


def _join_html_continuation(partial: str, continuation: str) -> str:
    addition = (continuation or "").strip()
    addition = re.sub(r"^```(?:html)?\s*", "", addition, flags=re.I)
    addition = re.sub(r"\s*```\s*$", "", addition)
    lower = addition.lower()
    for marker in ("<!doctype html", "<html"):
        repeated = lower.find(marker)
        if repeated >= 0:
            addition = addition[repeated:]
            body = addition.lower().find("<body")
            if body >= 0:
                addition = addition[body:]
            break
    # Continuation prompts request bytes immediately after the exact cutoff.
    # Do not inject a newline, which can corrupt JavaScript strings or tokens.
    left = partial.rstrip()
    right = addition.lstrip()

    overlap = min(500, len(left), len(right))
    for size in range(overlap, 0, -1):
        if left[-size:] == right[:size]:
            right = right[size:]
            break

    return left + right


def _prepare_for_continuation(html: str) -> str:
    """Remove premature document closers so continuation lands inside the document."""
    value = html.rstrip()
    value = re.sub(r"</html>\s*$", "", value, flags=re.I)
    if value.lower().count("<body") > value.lower().count("</body>"):
        value = re.sub(r"</body>\s*$", "", value, flags=re.I)
    return value.rstrip()


def _javascript_balance_problem(source: str) -> str:
    """Detect obvious truncation while ignoring strings and comments."""
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    i = 0
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", "\"", "`"):
            quote = ch
        elif ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        elif ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        elif ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack[-1] != pairs[ch]:
                return f"JavaScript has an unmatched {ch}"
            stack.pop()
        i += 1
    if quote:
        return "JavaScript ends inside a string"
    if block_comment:
        return "JavaScript ends inside a block comment"
    if stack:
        return f"JavaScript has {len(stack)} unclosed bracket(s)"
    return ""


def _validate_html(html: str, request: str) -> str:
    lower = html.lower()
    if len(html.encode("utf-8")) < 300:
        return "HTML is too small to be a meaningful application"
    if "<body" not in lower or "</html>" not in lower:
        return "HTML structure is incomplete"
    if lower.count("<body") != lower.count("</body>"):
        return "HTML body tag is not closed"
    if lower.count("<script") != lower.count("</script>"):
        return "HTML script tag is not closed"
    if "game" in request.lower() and "<script" not in lower:
        return "game artifact contains no JavaScript"
    for match in re.finditer(r"<script\b[^>]*>(.*?)</script>", html, re.I | re.S):
        problem = _javascript_balance_problem(match.group(1))
        if problem:
            return problem
    return ""


def _one_shot_browser_artifact(
    *,
    ask: Callable[[str], Any],
    original_request: str,
    workspace: Path,
    progress: Callable[[str], None],
    ask_raw: Callable[[str], Any] | None = None,
) -> str | None:
    target = workspace / "index.html"
    existing = ""
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8")
        except Exception:
            existing = ""
    progress("Requesting one-shot provider-generated HTML edit" if existing else "Requesting one-shot provider-generated HTML artifact")
    artifact_ask = ask_raw or ask
    response = artifact_ask(
        _raw_html_prompt(original_request, existing)
    )
    raw = getattr(response, "text", str(response))
    html = _extract_html(raw)
    partial = _extract_partial_html(raw)

    for attempt in range(1, 3):
        problem = _validate_html(html, original_request) if html is not None else "document has no closing </html>"
        if html is not None and not problem:
            break
        if partial is None and html is not None:
            partial = _prepare_for_continuation(html)
        elif partial is not None:
            partial = _prepare_for_continuation(partial)
        if partial is None:
            break
        progress(
            f"Repairing incomplete provider HTML ({attempt}/2; {len(partial)} characters preserved): {problem}"
        )
        response = artifact_ask(
            _html_continuation_prompt(partial, problem)
        )
        continuation = getattr(response, "text", str(response))
        partial = _join_html_continuation(partial, continuation)
        html = _extract_html(partial)

    if html is None:
        if partial is not None:
            progress(f"Provider HTML remained incomplete after repair ({len(partial)} characters)")
        else:
            progress(f"Provider returned no HTML document (response length {len(raw)})")
        return None

    problem = _validate_html(html, original_request)
    if problem:
        progress(f"Provider HTML rejected after targeted repair: {problem}")
        return None

    temporary = target.with_suffix(".html.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(target)
    progress(f"Wrote {target} ({target.stat().st_size} bytes)")
    from sophyane import execution_runtime as runtime
    progress("Browser artifact passed structural verification; opening demo")
    ok, result = runtime.execute_action({"type": "open_browser"}, workspace, progress)
    if not ok:
        return None
    return (
        "Updated and opened the provider-generated browser project.\n\n"
        f"Workspace: {workspace}\nFile: index.html\n\nExecution evidence:\n"
        f"- index.html exists ({target.stat().st_size} bytes)\n"
        "- HTML body/script structure verified\n"
        "- JavaScript bracket structure verified\n"
        f"- {result}"
    )


def _file_bundle_action(plan: dict[str, Any]) -> dict[str, Any] | None:
    files = plan.get("files")
    if not isinstance(files, list) or not files:
        return None
    actions: list[dict[str, Any]] = []
    for item in files:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("file") or "").strip()
            content = item.get("content")
            if path and isinstance(content, str) and content:
                actions.append({"type": "write_file", "path": path, "content": content})
    return {"type": "batch", "actions": actions} if actions else None


def _normalise_action(action: Any) -> dict[str, Any] | None:
    """Accept common provider action aliases and convert them to runtime actions."""
    if not isinstance(action, dict):
        return None

    value = dict(action)
    kind = str(value.get("type") or value.get("kind") or "").strip().lower()

    aliases = {
        "command": "run_command",
        "cmd": "run_command",
        "shell": "run_command",
        "shell_execute": "run_command",
        "execute_shell": "run_command",
        "bash": "run_command",
        "run": "run_command",
        "execute": "run_command",
        "exec": "run_command",
        "file": "write_file",
        "write": "write_file",
        "create_file": "write_file",
        "complete": "message",
        "completed": "message",
        "done": "message",
        "finish": "message",
        "finished": "message",
        "final": "message",
        "success": "message",
    }

    if kind in aliases:
        value["type"] = aliases[kind]
    elif kind:
        value["type"] = kind

    if value.get("type") == "run_command":
        command = (
            value.get("command")
            or value.get("cmd")
            or value.get("content")
        )
        if not isinstance(command, str) or not command.strip():
            return None
        value["command"] = command.strip()

    if value.get("type") in {"write_file", "append_file"}:
        path = value.get("path") or value.get("file")
        content = value.get("content")
        if not isinstance(path, str) or not path.strip():
            return None
        if not isinstance(content, str):
            return None
        value["path"] = path.strip()

    return value


def _selected_action(runtime: Any, plan: dict[str, Any]) -> dict[str, Any] | None:
    bundle = _file_bundle_action(plan)
    if bundle:
        return bundle

    # Prefer the explicit top-level action. Gemini commonly returns the full
    # planning schema with its executable action nested here.
    explicit = _normalise_action(plan.get("action"))
    if explicit:
        return explicit

    selected_index = plan.get("selected_index")
    candidates = plan.get("candidates")

    if isinstance(candidates, list) and candidates:
        if not isinstance(selected_index, int):
            selected_index = 0

        if 0 <= selected_index < len(candidates):
            candidate = candidates[selected_index]
            if isinstance(candidate, dict):
                nested = _normalise_action(candidate.get("action"))
                if nested:
                    return nested

                direct = _normalise_action(candidate)
                if direct:
                    return direct

    return _normalise_action(runtime.selected_action(plan))


def _command_text(action: dict[str, Any]) -> str:
    argv = action.get("argv")
    if isinstance(argv, list):
        return shlex.join(str(x) for x in argv)
    return str(action.get("command") or action.get("content") or action.get("cmd") or "").strip()


def _command_problem(action: dict[str, Any], workspace: Path) -> str:
    kind = str(action.get("type") or "").lower()
    if kind not in {
        "command",
        "run",
        "shell",
        "run_command",
        "bash",
        "run_interactive",
        "interactive",
        "play_demo",
    }:
        return ""
    command = _command_text(action)
    if not command:
        return "command action contains no command"
    try:
        tokens = shlex.split(command)
    except ValueError as error:
        return f"command cannot be parsed: {error}"
    if not tokens:
        return "command action contains no executable"
    first = tokens[0]
    if first in {"cd", "build", "create", "develop", "design", "implement", "write", "fix", "repair", "generate"}:
        return "model returned a shell recipe or natural-language instruction instead of source files"
    if first == "make" and not any((workspace / n).is_file() for n in ("Makefile", "makefile", "GNUmakefile")):
        return "make was requested before a Makefile exists"
    executable = Path(first)
    exists = executable.is_file() if executable.is_absolute() else (workspace / executable).is_file()
    if not exists and shutil.which(first) is None:
        return f"executable does not exist: {first}"
    return ""


_DISCOVERY_REQUEST_PATTERNS = (
    r"\blocate\b",
    r"\bfind\b",
    r"\bwhere\s+is\b",
    r"\bwhere(?:'s|\s+is)\b",
    r"\bshow\s+(?:me\s+)?(?:the\s+)?path\b",
    r"\bwhich\b",
)


def _command_stdout(result: str) -> str:
    """Extract STDOUT from a formatted command execution result."""

    match = re.search(
        r"STDOUT:\s*(.*?)\s*STDERR:",
        str(result or ""),
        re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _discovery_request_completed(
    request: str,
    action: dict[str, Any],
    ok: bool,
    result: str,
) -> bool:
    """Return True when a read-only discovery request produced an answer."""

    if not ok:
        return False

    kind = str(action.get("type") or "").lower()
    if kind not in {
        "command",
        "run",
        "shell",
        "run_command",
        "bash",
    }:
        return False

    request_text = str(request or "").lower()

    if not any(
        re.search(pattern, request_text)
        for pattern in _DISCOVERY_REQUEST_PATTERNS
    ):
        return False

    result_text = str(result or "")

    if "Exit code: 0" not in result_text:
        return False

    # `find` exits successfully even when it finds nothing, so non-empty
    # stdout is required before treating the request as complete.
    return bool(_command_stdout(result_text))


def _execute(runtime: Any, action: dict[str, Any], workspace: Path,
             progress: Callable[[str], None]) -> tuple[bool, str]:
    kind = str(action.get("type") or "").lower()
    if kind == "batch":
        children = action.get("actions")
        if not isinstance(children, list) or not children:
            return False, "Batch action contained no actions."
        results: list[str] = []
        for i, child in enumerate(children, 1):
            if not isinstance(child, dict):
                return False, f"Batch item {i} is invalid."
            progress(f"Batch {i}/{len(children)}: {child.get('type', 'action')}")
            ok, result = _execute(runtime, child, workspace, progress)
            results.append(f"Batch {i}: {result}")
            if not ok:
                return False, "\n".join(results)
        return True, "\n".join(results)

    if kind in {"write_file", "append_file"}:
        path = str(action.get("path") or action.get("file") or "").strip()
        content = str(action.get("content") or action.get("text") or "")
        if not path:
            return False, "File action rejected: missing path."
        if not content:
            return False, "File action rejected: empty content."
        if kind == "append_file" and Path(path).suffix.lower() == ".html" and re.search(r"<!doctype\s+html|<html", content, re.I):
            action = dict(action)
            action["type"] = "write_file"
            progress(f"Converted complete HTML append to atomic replacement for {path}")

    problem = _command_problem(action, workspace)
    if problem:
        return False, f"Rejected unsafe/invalid command action: {problem}."
    return runtime.execute_action(action, workspace, progress)


def execution_prefix_for_repair(request: str) -> str:
    try:
        from sophyane.harness_task_policy import execution_prefix
        return execution_prefix(request)
    except Exception:
        return (
            "Return one executable JSON action for the current task. "
            "Do not return prose."
        )


def _compact_repair_prompt(request: str, files: list[str], result: str) -> str:
    existing = ", ".join(files[-40:]) if files else "(none)"
    return (
        "ADAPTIVE EXECUTION REPAIR FOR THE CURRENT TASK. "
        "Ignore unrelated cached output and any previous-task response. "
        "This prompt requires a local software-runtime JSON action only. "
        "Do not answer with explanation, planning prose, Markdown, or examples. "
        "Return exactly one valid JSON object with no markdown. "
        "Use either "
        "{\\\"action\\\":{\\\"type\\\":\\\"write_file\\\","
        "\\\"path\\\":\\\"relative/path\\\","
        "\\\"content\\\":\\\"complete content\\\"}} "
        "or {\\\"files\\\":[{\\\"path\\\":\\\"relative/path\\\","
        "\\\"content\\\":\\\"complete content\\\"}]}. "
        "Keep every JSON response below 3500 characters. "
        "Keep file content in each response below 2600 characters. "
        "For a large file, first use write_file with the first chunk, then use "
        "append_file for later chunks. Never resend the whole large file. "
        "Each chunk must end at a safe source-code boundary, not inside a string. "
        "Create or extend only one project file per response. "
        "When all required files are ready, return exactly one run_command action. "
        "Use relative paths only and never use cd.\n"
        "EXECUTION CONTRACT:\n"
        + execution_prefix_for_repair(request)
        + "\n"
        + f"ORIGINAL TASK:\n{request[-7000:]}\n"
        + f"CURRENT FILES:\n{existing}\n"
        f"LAST RESPONSE OR RESULT:\n{result[-1800:]}\n"
        "Choose the single next unfinished action for ORIGINAL TASK only."
    )


_READ_ONLY_INSPECTION_HINTS = (
    "which file",
    "what file",
    "find file",
    "latest file",
    "largest file",
    "newest file",
    "oldest file",
    "modified",
    "amendment",
    "last amendment",
    "filesystem",
    "folder",
    "directory",
    "memory usage",
)

def _read_only_inspection(request: str) -> bool:
    t = request.lower()
    return any(x in t for x in _READ_ONLY_INSPECTION_HINTS)



def _canonicalize_explicit_file_path(
    original_request: str,
    action: dict[str, Any],
) -> dict[str, Any]:
    """Keep explicitly named bare files at the workspace root."""
    kind = str(action.get("type") or "").casefold()
    if kind not in {"write_file", "append_file"}:
        return action

    requested = re.findall(
        r"""(?:file\s+(?:named|called)?|create\s+(?:a|the)\s+file|write\s+(?:a|the)\s+file)
            \s*["'`]?([A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)["'`]?""",
        str(original_request or ""),
        flags=re.I | re.X,
    )

    if not requested:
        return action

    # Only canonicalize an explicitly bare filename. Requests containing an
    # intended directory such as tests/example.txt retain that directory.
    requested_name = requested[0].strip()
    if "/" in requested_name or "\\" in requested_name:
        return action

    current_path = str(
        action.get("path")
        or action.get("file")
        or ""
    ).strip()

    if not current_path:
        return action

    if Path(current_path).name.casefold() != requested_name.casefold():
        return action

    corrected = dict(action)
    corrected["path"] = requested_name
    corrected.pop("file", None)
    return corrected


def _simple_file_write_request_completed(
    original_request: str,
    action: dict[str, Any],
    ok: bool,
    workspace: Path,
) -> bool:
    """Stop after a verified single-file write instead of requesting repeats."""
    if not ok:
        return False

    kind = str(action.get("type") or "").casefold()
    if kind not in {"write_file", "append_file"}:
        return False

    request = " ".join(str(original_request or "").casefold().split())

    # Do not short-circuit compound build, test, judge, or shell workflows.
    compound_markers = (
        "run ",
        "execute ",
        "test ",
        "pytest",
        "judge.sh",
        "compile",
        "build ",
        "copy ",
        "then create",
        "create directories",
        "create these directories",
        "multiple files",
    )
    if any(marker in request for marker in compound_markers):
        return False

    if not any(
        phrase in request
        for phrase in (
            "create a file",
            "create the file",
            "write a file",
            "write the file",
        )
    ):
        return False

    raw_path = str(action.get("path") or "").strip()
    if not raw_path:
        return False

    target = Path(raw_path)
    if not target.is_absolute():
        target = workspace / target

    try:
        target = target.resolve()
        target.relative_to(workspace.resolve())
    except (OSError, ValueError):
        return False

    if not target.is_file():
        return False

    expected = action.get("content")
    if expected is not None:
        try:
            if target.read_text(encoding="utf-8") != str(expected):
                return False
        except OSError:
            return False

    # When a filename is explicitly named, ensure the written basename matches.
    names = re.findall(
        r"""(?:named|called|file)\s+["'`]?([A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)""",
        original_request,
        flags=re.I,
    )
    if names and target.name.casefold() not in {
        name.casefold() for name in names
    }:
        return False

    return True


def run_adaptive_loop(*, initial_text: str, original_request: str, ask: Callable[[str], Any],
                      workspace: Path | None = None, max_steps: int = 12,
                      progress: Callable[[str], None] | None = None) -> str:
    from sophyane import execution_runtime as runtime
    requested_workspace = (workspace or Path.cwd()).resolve()

    try:
        from sophyane.harness_workspace import select_workspace
        workspace = select_workspace(
            original_request,
            requested_workspace,
        )
    except Exception:
        workspace = requested_workspace

    workspace.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda _message: None)

    # Software projects commonly require several file chunks, build commands,
    # tests and repairs. Do not inherit an undersized caller budget.
    max_steps = max(max_steps, 32)

    if _browser_request(original_request):
        try:
            completed = _one_shot_browser_artifact(
                ask=ask, original_request=original_request, workspace=workspace, progress=progress
            )
            if completed:
                return completed
        except Exception as error:
            progress(f"One-shot browser generation failed: {type(error).__name__}: {error}")

    # `current` contains only the provider response that may be parsed as an
    # executable action. Repair prompts add the execution contract through
    # execution_prefix_for_repair() when another provider call is required.
    current = str(initial_text or "")

    evidence: list[str] = []
    repairs = 0
    successful_commands: set[str] = set()

    # A provider may initially return a complete multi-file Markdown project.
    # Materialize that bundle once. Subsequent iterations must inspect, build,
    # test or perform targeted repairs instead of regenerating the project.
    markdown_bundle_written = False

    # Deterministic post-generation verification is a small state machine:
    # create an isolated project environment, install dependencies with an
    # Android-friendly timeout, then run the project's own tests.
    deterministic_verification_stage = ""

    for step in range(1, max_steps + 1):
        # After the initial multi-file bundle is materialized, do not depend on
        # the provider to emit a run_command action. Sophyane owns the next
        # deterministic step: install declared dependencies and execute tests.
        if deterministic_verification_stage == "prepare":
            project_python = workspace / ".venv" / "bin" / "python"

            if project_python.is_file():
                deterministic_verification_stage = "install"
            else:
                action = {
                    "type": "run_command",
                    "command": (
                        f"{shlex.quote(sys.executable)} -m venv .venv"
                    ),
                    "timeout": 300,
                    "deterministic_post_bundle_verification": "prepare",
                }
                plan = None
                deterministic_verification_stage = "prepare_running"
                progress(
                    "Creating isolated project virtual environment"
                )

        elif deterministic_verification_stage == "install":
            project_python = workspace / ".venv" / "bin" / "python"
            requirements = workspace / "requirements.txt"

            if requirements.is_file():
                command = (
                    f"{shlex.quote(str(project_python))} "
                    "-m pip install --disable-pip-version-check "
                    "--no-input -r requirements.txt"
                )
            else:
                command = (
                    f"{shlex.quote(str(project_python))} "
                    "-m pip install --disable-pip-version-check "
                    "--no-input pytest"
                )

            action = {
                "type": "run_command",
                "command": command,
                "timeout": 900,
                "deterministic_post_bundle_verification": "install",
            }
            plan = None
            deterministic_verification_stage = "install_running"
            progress(
                "Installing project dependencies "
                "with Android-native build allowance"
            )

        elif deterministic_verification_stage == "test":
            project_python = workspace / ".venv" / "bin" / "python"

            action = {
                "type": "run_command",
                "command": (
                    f"{shlex.quote(str(project_python))} "
                    "-m pytest -q"
                ),
                "timeout": 300,
                "deterministic_post_bundle_verification": "test",
            }
            plan = None
            deterministic_verification_stage = "test_running"
            progress("Running isolated project test suite")

        else:
            plan = runtime.extract_plan(current)
            action = _selected_action(runtime, plan) if plan else None
        if not action and not markdown_bundle_written:
            try:
                from sophyane.multifile_artifact_extractor import (
                    as_batch_action,
                )

                action = as_batch_action(current)

                if action is not None:
                    children = action.get("actions") or []
                    progress(
                        "Extracted initial provider Markdown project bundle: "
                        f"{len(children)} safe file(s)"
                    )
            except Exception as error:
                progress(
                    "Markdown project extraction failed safely: "
                    f"{type(error).__name__}: {error}"
                )

        elif not action and markdown_bundle_written:
            # Do not repeatedly replace the project with fresh prose bundles.
            # Feed an explicit verification requirement into bounded repair.
            current = (
                "The initial project bundle is already materialized. "
                "Do not regenerate or resend project files. "
                "Return one executable run_command action that inspects, "
                "installs dependencies if required, or runs the relevant "
                "tests. Use actual command output for later targeted repairs.\n\n"
                + str(current or "")
            )

        if not action:
            rejected = (current or "").strip()
            prefix = rejected[:900].replace("\n", "\\n")
            progress(
                "Provider response was not an executable action "
                f"(length={len(rejected)}, prefix={prefix!r})"
            )
            evidence.append(
                f"Rejected response: length={len(rejected)} prefix={prefix!r}"
            )

            if repairs >= 5:
                return (
                    "Execution stopped safely: provider could not produce "
                    "a usable artifact.\n\n" + "\n".join(evidence)
                )

            repairs += 1
            progress(f"Requesting compact provider repair ({repairs}/5)")
            response = ask(
                _compact_repair_prompt(
                    original_request,
                    _files(workspace),
                    rejected,
                )
            )
            current = getattr(response, "text", str(response))
            continue
        action = _canonicalize_explicit_file_path(
            original_request,
            action,
        )
        kind = str(action.get("type") or "").lower()

        if (
            kind == "batch"
            and action.get("artifact_source")
            == "markdown_multifile_bundle"
        ):
            markdown_bundle_written = True
            deterministic_verification_stage = "prepare"

        # Completion aliases are normalized by _normalise_action, but keep
        # this defensive conversion for plans supplied by older adapters.
        if kind in {
            "complete",
            "completed",
            "done",
            "finish",
            "finished",
            "final",
            "success",
        }:
            action = dict(action)
            action["type"] = "message"
            kind = "message"

        if kind in {"respond", "message"} and not _files(workspace):
            current = "Premature completion: no artifact exists."
            continue
        progress(f"Step {step}/{max_steps}: preparing {kind or 'action'}")

        command_kinds = {
            "command",
            "run",
            "shell",
            "run_command",
            "bash",
            "run_interactive",
            "interactive",
            "play_demo",
        }

        command_text = (
            _command_text(action)
            if kind in command_kinds
            else ""
        )

        if (
            command_text
            and command_text in successful_commands
            and not command_text.lstrip().startswith(("echo ", "printf "))
        ):
            result = (
                "Verification already passed earlier with exit code 0: "
                f"{command_text}"
            )
            evidence.append(f"Step {step}: {result}")
            progress(result)

            return (
                "Project implementation and verification completed "
                "successfully.\n\nExecution evidence:\n"
                + "\n".join(evidence)
            )

        ok, result = _execute(runtime, action, workspace, progress)
        evidence.append(f"Step {step}: {result}")

        verification_phase = action.get(
            "deterministic_post_bundle_verification"
        )

        if verification_phase == "prepare":
            if ok:
                deterministic_verification_stage = "install"
                current = ""
                continue

            return (
                "Execution stopped safely: project virtual environment "
                "could not be created.\n\nExecution evidence:\n"
                + "\n".join(evidence)
            )

        if verification_phase == "install":
            if ok:
                deterministic_verification_stage = "test"
                current = ""
                continue

            # Installation failures are deterministic environment evidence.
            # Do not send unrelated repair prompts through generic connectors.
            return (
                "Execution stopped safely: dependency installation failed. "
                "The generated project remains preserved.\n\n"
                "Execution evidence:\n"
                + "\n".join(evidence)
            )

        if verification_phase == "test":
            if ok:
                successful_commands.add(_command_text(action))
                return (
                    "Project implementation and verification completed "
                    "successfully.\n\nWorkspace: "
                    + str(workspace)
                    + "\n\nExecution evidence:\n"
                    + "\n".join(evidence)
                )

            # A real pytest failure may now be sent for a targeted source fix.
            deterministic_verification_stage = ""
            current = _compact_repair_prompt(
                original_request,
                _files(workspace),
                result,
            )
            repairs = 0
            continue

        if _simple_file_write_request_completed(
            original_request,
            action,
            ok,
            workspace,
        ):
            return (
                "DONE\n\nExecution evidence:\n"
                + "\n".join(evidence)
            )

        if _discovery_request_completed(
            original_request,
            action,
            ok,
            result,
        ):
            return (
                "Discovery completed successfully.\n\n"
                + result
                + "\n\nExecution evidence:\n"
                + "\n".join(evidence)
            )

        if (
            command_text
            and ok
            and verification_result_is_meaningful(
                command_text,
                result,
            )
        ):
            successful_commands.add(command_text)

        # Repair attempts are consecutive-failure limits, not a lifetime
        # allowance. A successful action proves recovery and resets the budget.
        if ok:
            repairs = 0

        if not ok:
            if repairs >= 2:
                return "Execution stopped safely after bounded repair attempts.\n\n" + "\n".join(evidence)
            repairs += 1
            response = ask(_compact_repair_prompt(original_request, _files(workspace), result))
            current = getattr(response, "text", str(response))
            continue
        if kind in {"respond", "message", "open_browser", "browser"}:
            return (result or "Completed.") + "\n\nExecution evidence:\n" + "\n".join(evidence)
        response = ask(_compact_repair_prompt(original_request, _files(workspace), result))
        current = getattr(response, "text", str(response))
    return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)


def install() -> None:
    from sophyane import execution_runtime
    execution_runtime.run_structured_loop = run_adaptive_loop
