"""Provider-driven execution policy for the observable Sophyane TUI.

This module contains no application templates. It converts generic code/file bundles
from any configured local or frontier provider into safe workspace actions, rejects
natural-language requests masquerading as shell commands, and feeds real execution
evidence back to the provider for bounded repair.
"""
from __future__ import annotations

import json
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
        if not path or not isinstance(content, str):
            continue
        actions.append({"type": "write_file", "path": path, "content": content})
    return {"type": "batch", "actions": actions} if actions else None


def _selected_action(runtime: Any, plan: dict[str, Any]) -> dict[str, Any] | None:
    bundle = _file_bundle_action(plan)
    if bundle:
        return bundle
    return runtime.selected_action(plan)


def _command_text(action: dict[str, Any]) -> str:
    argv = action.get("argv")
    if isinstance(argv, list):
        return shlex.join(str(item) for item in argv)
    return str(action.get("command") or action.get("content") or action.get("cmd") or "").strip()


def _command_problem(action: dict[str, Any], workspace: Path) -> str:
    kind = str(action.get("type") or "").strip().lower()
    if kind not in {
        "run", "shell", "run_command", "bash", "run_interactive", "interactive", "play_demo"
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
    natural_verbs = {
        "build", "create", "develop", "design", "implement", "write", "fix", "repair",
        "make-game", "make_app", "generate",
    }
    if first.lower() in natural_verbs:
        return "natural-language build instruction was returned as a shell command"

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
    kind = str(action.get("type") or "").strip().lower()
    if kind == "batch":
        children = action.get("actions")
        if not isinstance(children, list) or not children:
            return False, "Batch action contained no file or tool actions."
        results: list[str] = []
        for index, child in enumerate(children, start=1):
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


def _generation_prompt(workspace: Path, original_request: str, broken: str, evidence: list[str]) -> str:
    existing = [str(path.relative_to(workspace)) for path in sorted(workspace.rglob("*")) if path.is_file()][:40]
    return (
        "Act as the implementation model for a coding agent. Produce the requested software, not a command that repeats "
        "the user's words. Return exactly one compact JSON object and no markdown. Prefer this generic artifact schema: "
        '{"objective":"...","success_criteria":["..."],"files":[{"path":"relative/path","content":"complete code"}]}. '
        "You may instead return one action object using write_file, append_file, mkdir, run_command, open_browser, or respond. "
        "All paths must be relative to the isolated workspace. Generate files before running commands. Never use run_interactive "
        "until a real executable or script has been created and tested. Do not return commands such as 'make snake game', "
        "'build app', or other natural-language requests. Keep each response reasonably small; continue with append_file when needed.\n\n"
        f"Workspace: {workspace}\nExisting files: {existing or ['(empty)']}\n"
        f"User request:\n{original_request}\n\n"
        f"Previous invalid response/action:\n{broken[:1600]}\n\n"
        f"Execution evidence so far:\n{chr(10).join(evidence[-6:]) or '(none)'}"
    )


def _followup_prompt(workspace: Path, original_request: str, result: str, evidence: list[str]) -> str:
    files = [str(path.relative_to(workspace)) for path in sorted(workspace.rglob("*")) if path.is_file()][:50]
    return (
        "Continue implementing and verifying the same software request. Use the real workspace state and execution result below. "
        "Return exactly one JSON object with either a generic files array or one action. Generate/edit files before commands. "
        "Use run_command only for a real compiler, interpreter, test, or project command that now exists. Never copy the user's "
        "natural-language request into a command. When all criteria are genuinely satisfied, return "
        '{"action":{"type":"respond","message":"concise completion summary with files and verification"}}.\n\n'
        f"Workspace: {workspace}\nFiles: {files}\nOriginal request:\n{original_request}\n\n"
        f"Latest execution result:\n{result}\n\nEvidence:\n{chr(10).join(evidence[-8:])}"
    )


def run_adaptive_loop(
    *,
    initial_text: str,
    original_request: str,
    ask: Callable[[str], Any],
    workspace: Path | None = None,
    max_steps: int = 12,
    progress: Callable[[str], None] | None = None,
) -> str:
    from sophyane import execution_runtime as runtime

    workspace = (workspace or Path.cwd()).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda _message: None)
    current = initial_text
    evidence: list[str] = []
    recovery_attempts = 0

    for step in range(1, max_steps + 1):
        plan = runtime.extract_plan(current)
        action = _selected_action(runtime, plan) if plan else None
        if not action:
            if recovery_attempts >= 3:
                return "Execution stopped safely: provider repeatedly returned no executable files or action.\n\n" + "\n".join(evidence)
            recovery_attempts += 1
            progress(f"Requesting provider-generated implementation bundle ({recovery_attempts}/3)")
            response = ask(_generation_prompt(workspace, original_request, current, evidence))
            current = getattr(response, "text", str(response))
            continue

        progress(f"Step {step}/{max_steps}: preparing {action.get('type', 'action')}")
        ok, result = _execute(runtime, action, workspace, progress)
        evidence.append(f"Step {step}: {result}")
        if not ok:
            if recovery_attempts >= 3:
                return "Execution stopped safely after bounded repair attempts.\n\n" + "\n".join(evidence)
            recovery_attempts += 1
            progress(f"Action rejected/failed; requesting corrected implementation ({recovery_attempts}/3)")
            response = ask(_generation_prompt(workspace, original_request, json.dumps(plan)[:1600] if plan else current, evidence))
            current = getattr(response, "text", str(response))
            continue

        recovery_attempts = 0
        kind = str(action.get("type") or "").lower()
        if kind in {"respond", "message", "open_browser", "browser"}:
            return (result or "Completed.") + "\n\nExecution evidence:\n" + "\n".join(evidence)

        progress(f"Step {step}/{max_steps}: asking provider to verify or continue")
        response = ask(_followup_prompt(workspace, original_request, result, evidence))
        current = getattr(response, "text", str(response))

    return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)


def install() -> None:
    """Install the adaptive loop before tui_v2 imports its runtime symbol."""
    from sophyane import execution_runtime

    execution_runtime.run_structured_loop = run_adaptive_loop
