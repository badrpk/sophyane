"""Provider-driven adaptive execution for Sophyane.

Application code always comes from the configured local/frontier provider. This module
only adapts model output into safe workspace artifacts, execution and verification.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
from pathlib import Path
from typing import Any, Callable


def _files(workspace: Path) -> list[str]:
    return [str(p.relative_to(workspace)) for p in sorted(workspace.rglob("*")) if p.is_file()]


def _browser_request(request: str) -> bool:
    text = request.lower()
    return any(word in text for word in ("browser", "website", "web app", "html", "game"))


def _extract_html(text: str) -> str | None:
    value = text.strip()
    fenced = re.search(r"```(?:html)?\s*(<!doctype html.*?</html>)\s*```", value, re.I | re.S)
    if fenced:
        value = fenced.group(1).strip()
    else:
        start = value.lower().find("<!doctype html")
        if start < 0:
            start = value.lower().find("<html")
        end = value.lower().rfind("</html>")
        if start >= 0 and end > start:
            value = value[start : end + len("</html>")]
    lower = value.lower()
    if ("<!doctype html" in lower or "<html" in lower) and "</html>" in lower:
        return value
    return None


def _raw_html_prompt(original_request: str) -> str:
    # Deliberately tiny for 1B–2B local models and 1024-token contexts.
    return (
        "Create the requested browser project as ONE complete self-contained index.html. "
        "Include all CSS and JavaScript inside the file. Make it functional and mobile-friendly. "
        "Output raw HTML only, starting with <!doctype html> and ending with </html>. "
        "No JSON, markdown, explanation, shell commands, cd, make, or filenames.\n\n"
        f"REQUEST: {original_request[-500:]}"
    )


def _one_shot_browser_artifact(*, ask: Callable[[str], Any], original_request: str,
                               workspace: Path, progress: Callable[[str], None]) -> str | None:
    progress("Requesting one-shot provider-generated HTML artifact")
    response = ask(_raw_html_prompt(original_request))
    raw = getattr(response, "text", str(response))
    html = _extract_html(raw)
    if html is None:
        return None
    lower = html.lower()
    if "game" in original_request.lower() and "<script" not in lower:
        return None
    target = workspace / "index.html"
    target.write_text(html, encoding="utf-8")
    progress(f"Wrote {target} ({target.stat().st_size} bytes)")
    if target.stat().st_size < 300 or "<body" not in lower:
        return None
    from sophyane import execution_runtime as runtime
    progress("Browser artifact passed structural verification; opening demo")
    ok, result = runtime.execute_action({"type": "open_browser"}, workspace, progress)
    if not ok:
        return None
    return (
        "Created and opened the provider-generated browser project.\n\n"
        f"Workspace: {workspace}\nFile: index.html\n\nExecution evidence:\n"
        f"- index.html exists ({target.stat().st_size} bytes)\n- HTML structure verified\n- {result}"
    )


def _file_bundle_action(plan: dict[str, Any]) -> dict[str, Any] | None:
    files = plan.get("files")
    if not isinstance(files, list) or not files:
        return None
    actions = []
    for item in files:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("file") or "").strip()
            content = item.get("content")
            if path and isinstance(content, str):
                actions.append({"type": "write_file", "path": path, "content": content})
    return {"type": "batch", "actions": actions} if actions else None


def _selected_action(runtime: Any, plan: dict[str, Any]) -> dict[str, Any] | None:
    return _file_bundle_action(plan) or runtime.selected_action(plan)


def _command_text(action: dict[str, Any]) -> str:
    argv = action.get("argv")
    if isinstance(argv, list):
        return shlex.join(str(x) for x in argv)
    return str(action.get("command") or action.get("content") or action.get("cmd") or "").strip()


def _command_problem(action: dict[str, Any], workspace: Path) -> str:
    kind = str(action.get("type") or "").lower()
    if kind not in {"run", "shell", "run_command", "bash", "run_interactive", "interactive", "play_demo"}:
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


def _execute(runtime: Any, action: dict[str, Any], workspace: Path,
             progress: Callable[[str], None]) -> tuple[bool, str]:
    if str(action.get("type") or "").lower() == "batch":
        children = action.get("actions")
        if not isinstance(children, list) or not children:
            return False, "Batch action contained no actions."
        results = []
        for i, child in enumerate(children, 1):
            if not isinstance(child, dict):
                return False, f"Batch item {i} is invalid."
            progress(f"Batch {i}/{len(children)}: {child.get('type', 'action')}")
            ok, result = _execute(runtime, child, workspace, progress)
            results.append(f"Batch {i}: {result}")
            if not ok:
                return False, "\n".join(results)
        return True, "\n".join(results)
    problem = _command_problem(action, workspace)
    if problem:
        return False, f"Rejected unsafe/invalid command action: {problem}."
    return runtime.execute_action(action, workspace, progress)


def _compact_repair_prompt(request: str, files: list[str], result: str) -> str:
    return (
        "Return one compact JSON object only. Generate real source files before commands. "
        "Use {\"files\":[{\"path\":\"relative\",\"content\":\"complete code\"}]} or one action. "
        "Never use cd or repeat the user's words as a command.\n"
        f"Request: {request[-500:]}\nFiles: {files[-20:]}\nLast result: {result[-700:]}"
    )


def run_adaptive_loop(*, initial_text: str, original_request: str, ask: Callable[[str], Any],
                      workspace: Path | None = None, max_steps: int = 12,
                      progress: Callable[[str], None] | None = None) -> str:
    from sophyane import execution_runtime as runtime
    workspace = (workspace or Path.cwd()).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda _message: None)

    # Small local models perform far better with one raw-artifact request than several
    # nested JSON planning/repair calls. Games default to a portable browser artifact.
    if _browser_request(original_request) and not (workspace / "index.html").exists():
        try:
            completed = _one_shot_browser_artifact(
                ask=ask, original_request=original_request, workspace=workspace, progress=progress
            )
            if completed:
                return completed
        except Exception as error:
            progress(f"One-shot browser generation failed: {type(error).__name__}: {error}")

    current = initial_text
    evidence: list[str] = []
    repairs = 0
    for step in range(1, max_steps + 1):
        plan = runtime.extract_plan(current)
        action = _selected_action(runtime, plan) if plan else None
        if not action:
            if repairs >= 2:
                return "Execution stopped safely: provider could not produce a usable artifact.\n\n" + "\n".join(evidence)
            repairs += 1
            progress(f"Requesting compact provider repair ({repairs}/2)")
            response = ask(_compact_repair_prompt(original_request, _files(workspace), current))
            current = getattr(response, "text", str(response))
            continue
        kind = str(action.get("type") or "").lower()
        if kind in {"respond", "message"} and not _files(workspace):
            current = "Premature completion: no artifact exists."
            continue
        progress(f"Step {step}/{max_steps}: preparing {kind or 'action'}")
        ok, result = _execute(runtime, action, workspace, progress)
        evidence.append(f"Step {step}: {result}")
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
