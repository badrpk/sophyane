"""Provider-driven adaptive execution for the observable Sophyane TUI.

No application templates live here. Any configured local or frontier provider supplies
code as generic file bundles, raw artifacts, or actions; this layer safely writes, runs,
verifies and repairs those artifacts inside an isolated workspace.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
from pathlib import Path
from typing import Any, Callable


def _file_bundle_action(plan: dict[str, Any]) -> dict[str, Any] | None:
    files = plan.get("files")
    if not isinstance(files, list) or not files:
        return None
    actions: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            continue
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
        return shlex.join(str(item) for item in argv)
    return str(action.get("command") or action.get("content") or action.get("cmd") or "").strip()


def _command_problem(action: dict[str, Any], workspace: Path) -> str:
    kind = str(action.get("type") or "").strip().lower()
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
    if first.lower() in {"build", "create", "develop", "design", "implement", "write", "fix", "repair", "generate"}:
        return "natural-language build instruction was returned as a shell command"
    if first == "cd":
        return "changing directories is unnecessary; commands already run inside the isolated workspace"
    if first == "make" and not any((workspace / name).is_file() for name in ("Makefile", "makefile", "GNUmakefile")):
        return "make was requested before a Makefile exists; generate project files first"
    executable = Path(first)
    exists = executable.is_file() if executable.is_absolute() else (workspace / executable).is_file()
    if not exists and shutil.which(first) is None:
        return f"executable does not exist: {first}"
    if kind in {"run_interactive", "interactive", "play_demo"} and not any(workspace.iterdir()):
        return "interactive launch was requested before any project artifact was created"
    return ""


def _execute(runtime: Any, action: dict[str, Any], workspace: Path, progress: Callable[[str], None]) -> tuple[bool, str]:
    if str(action.get("type") or "").lower() == "batch":
        children = action.get("actions")
        if not isinstance(children, list) or not children:
            return False, "Batch action contained no file or tool actions."
        results: list[str] = []
        for index, child in enumerate(children, 1):
            if not isinstance(child, dict):
                return False, f"Batch item {index} is not an action object."
            progress(f"Batch {index}/{len(children)}: {child.get('type', 'action')}")
            ok, result = _execute(runtime, child, workspace, progress)
            results.append(f"Batch {index}: {result}")
            if not ok:
                return False, "\n".join(results)
        return True, "\n".join(results)
    problem = _command_problem(action, workspace)
    if problem:
        return False, f"Rejected unsafe/invalid command action: {problem}."
    return runtime.execute_action(action, workspace, progress)


def _files(workspace: Path) -> list[str]:
    return [str(path.relative_to(workspace)) for path in sorted(workspace.rglob("*")) if path.is_file()]


def _browser_request(request: str) -> bool:
    lowered = request.lower()
    return any(marker in lowered for marker in ("browser", "website", "web app", "web game", "html", "show demo"))


def _extract_html(text: str) -> str | None:
    value = text.strip()
    fenced = re.search(r"```(?:html)?\s*(<!doctype html[\s\S]*?</html>)\s*```", value, re.I)
    if fenced:
        value = fenced.group(1).strip()
    else:
        start = value.lower().find("<!doctype html")
        if start < 0:
            start = value.lower().find("<html")
        end = value.lower().rfind("</html>")
        if start >= 0 and end > start:
            value = value[start : end + len("</html>")].strip()
    lowered = value.lower()
    if len(value) >= 300 and ("<!doctype html" in lowered or "<html" in lowered) and "</html>" in lowered:
        return value
    return None


def _raw_browser_prompt(original_request: str) -> str:
    return (
        "Create the complete requested browser application. Return ONLY the full contents of one self-contained index.html file. "
        "Do not return JSON, markdown fences, explanations, shell commands, cd, make, or installation instructions. Include all "
        "HTML, CSS, and JavaScript inline. The result must be immediately usable in a modern mobile browser and include sensible "
        "touch controls when interaction is required. Implement the user's request completely.\n\n"
        f"USER REQUEST:\n{original_request}"
    )


def _browser_artifact_problem(workspace: Path, original_request: str) -> str:
    target = workspace / "index.html"
    if not target.is_file():
        return "index.html does not exist"
    try:
        content = target.read_text(encoding="utf-8")
    except Exception as error:
        return f"index.html cannot be read: {error}"
    lowered = content.lower()
    if len(content) < 300:
        return "index.html is too small to be a complete application"
    if "<html" not in lowered or "</html>" not in lowered:
        return "index.html is not a complete HTML document"
    if "game" in original_request.lower() and "<script" not in lowered:
        return "game request has no JavaScript implementation"
    return ""


def _completion_problem(original_request: str, workspace: Path, evidence: list[str]) -> str:
    files = _files(workspace)
    meaningful = [name for name in files if Path(name).name.lower() not in {"makefile", "readme.md", "readme.txt"}]
    request = original_request.lower()
    if not meaningful:
        return "no meaningful software artifact exists; a Makefile or README alone is not the requested deliverable"
    if _browser_request(original_request):
        browser_problem = _browser_artifact_problem(workspace, original_request)
        if browser_problem:
            return browser_problem
    if "game" in request and not any(Path(name).suffix.lower() in {".html", ".js", ".py", ".cpp", ".c", ".java", ".rs"} for name in meaningful):
        return "game source or browser artifact is missing"
    verified = any("Exit code: 0" in item or "Browser command:" in item or "Browser open requested" in item for item in evidence)
    if not verified:
        return "no successful test, interpreter, compiler, health check, or browser launch evidence exists"
    return ""


def _generation_prompt(workspace: Path, original_request: str, broken: str, evidence: list[str]) -> str:
    return (
        "Act as the implementation model for a coding agent. Produce the requested software, not a command that repeats "
        "the user's words. Return exactly one compact JSON object and no markdown. Prefer: "
        '{"objective":"...","success_criteria":["..."],"files":[{"path":"relative/path","content":"complete code"}]}. '
        "You may instead return one action using write_file, append_file, mkdir, run_command, open_browser, or respond. "
        "Generate meaningful source/application files before build metadata or commands. Never use cd. A Makefile or README alone "
        "never satisfies an application request. Never claim completion without a successful real test/run/browser result. "
        "All paths must be relative. Never return natural-language commands such as 'make snake game'.\n\n"
        f"Workspace: {workspace}\nExisting files: {_files(workspace) or ['(empty)']}\n"
        f"User request:\n{original_request}\n\nPrevious invalid response/action:\n{broken[:1800]}\n\n"
        f"Evidence:\n{chr(10).join(evidence[-8:]) or '(none)'}"
    )


def _followup_prompt(workspace: Path, original_request: str, result: str, evidence: list[str]) -> str:
    return (
        "Continue implementing and mechanically verifying the same software request. Return exactly one JSON object with "
        "either a files array or one action. Generate/edit meaningful source files before commands. Never use cd. Use run_command "
        "only for a real compiler, interpreter, test, health check, or project command. Use open_browser only after index.html exists. "
        "Do not use respond until the requested deliverable exists and verification succeeded. A Makefile or README alone is not "
        "completion. Never copy the user's natural-language request into a command.\n\n"
        f"Workspace: {workspace}\nFiles: {_files(workspace)}\nOriginal request:\n{original_request}\n\n"
        f"Latest result:\n{result}\n\nEvidence:\n{chr(10).join(evidence[-10:])}"
    )


def run_adaptive_loop(*, initial_text: str, original_request: str, ask: Callable[[str], Any], workspace: Path | None = None,
                      max_steps: int = 12, progress: Callable[[str], None] | None = None) -> str:
    from sophyane import execution_runtime as runtime
    workspace = (workspace or Path.cwd()).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda _message: None)
    current = initial_text
    evidence: list[str] = []
    repairs = 0
    raw_browser_attempted = False

    for step in range(1, max_steps + 1):
        plan = runtime.extract_plan(current)
        action = _selected_action(runtime, plan) if plan else None

        if not action and _browser_request(original_request) and not (workspace / "index.html").exists() and not raw_browser_attempted:
            raw_browser_attempted = True
            progress("Requesting raw provider-generated browser artifact")
            response = ask(_raw_browser_prompt(original_request))
            raw = getattr(response, "text", str(response))
            html = _extract_html(raw)
            if html:
                current = json.dumps({"files": [{"path": "index.html", "content": html}]}, ensure_ascii=False)
                continue
            current = raw

        if not action:
            if repairs >= 4:
                return "Execution stopped safely: provider repeatedly returned no executable files or action.\n\n" + "\n".join(evidence)
            repairs += 1
            progress(f"Requesting provider-generated implementation bundle ({repairs}/4)")
            response = ask(_generation_prompt(workspace, original_request, current, evidence))
            current = getattr(response, "text", str(response))
            continue

        kind = str(action.get("type") or "").lower()
        if kind in {"respond", "message"}:
            problem = _completion_problem(original_request, workspace, evidence)
            if problem:
                repairs += 1
                progress(f"Rejecting unverified completion: {problem}")
                response = ask(_generation_prompt(workspace, original_request, f"Premature completion rejected: {problem}", evidence))
                current = getattr(response, "text", str(response))
                continue

        progress(f"Step {step}/{max_steps}: preparing {action.get('type', 'action')}")
        ok, result = _execute(runtime, action, workspace, progress)
        evidence.append(f"Step {step}: {result}")
        if not ok:
            if _browser_request(original_request) and not (workspace / "index.html").exists() and not raw_browser_attempted:
                raw_browser_attempted = True
                progress("Structured action failed; requesting raw provider-generated browser artifact")
                response = ask(_raw_browser_prompt(original_request))
                raw = getattr(response, "text", str(response))
                html = _extract_html(raw)
                current = json.dumps({"files": [{"path": "index.html", "content": html}]}, ensure_ascii=False) if html else raw
                continue
            if repairs >= 4:
                return "Execution stopped safely after bounded repair attempts.\n\n" + "\n".join(evidence)
            repairs += 1
            progress(f"Action rejected/failed; requesting corrected implementation ({repairs}/4)")
            response = ask(_generation_prompt(workspace, original_request, json.dumps(plan)[:1800] if plan else current, evidence))
            current = getattr(response, "text", str(response))
            continue

        if _browser_request(original_request) and (workspace / "index.html").is_file():
            problem = _browser_artifact_problem(workspace, original_request)
            if not problem:
                progress("Browser artifact passed structural verification; opening demo")
                opened, browser_result = _execute(runtime, {"type": "open_browser"}, workspace, progress)
                evidence.append(f"Browser verification: {browser_result}")
                if opened:
                    return "Browser application generated, structurally verified, and opened.\n\nExecution evidence:\n" + "\n".join(evidence)
            else:
                evidence.append(f"Browser structural verification failed: {problem}")

        if kind in {"respond", "message", "open_browser", "browser"}:
            return (result or "Completed.") + "\n\nExecution evidence:\n" + "\n".join(evidence)

        progress(f"Step {step}/{max_steps}: asking provider to verify or continue")
        response = ask(_followup_prompt(workspace, original_request, result, evidence))
        current = getattr(response, "text", str(response))

    return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)


def install() -> None:
    from sophyane import execution_runtime
    execution_runtime.run_structured_loop = run_adaptive_loop
