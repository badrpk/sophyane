"""Provider-driven adaptive execution for Sophyane.

Application code always comes from the configured provider. This module only adapts
model output into safe workspace artifacts, execution and mechanical verification.
"""
from __future__ import annotations

from sophyane.generation_contract import mark_raw_artifact

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



def _is_fresh_html_game_request(original_request: str) -> bool:
    """Return True when a request describes a new standalone HTML game."""

    lowered = str(original_request or "").lower()

    game_terms = (
        " game",
        "snake",
        "pong",
        "pingpong",
        "ping pong",
        "tic tac toe",
        "tictactoe",
        "breakout",
        "flappy",
        "platformer",
        "space shooter",
        "asteroids",
        "2048",
        "sudoku",
    )

    edit_terms = (
        "edit ",
        "modify ",
        "update ",
        "improve ",
        "change ",
        "fix ",
        "continue ",
        "add to ",
        "existing game",
        "current game",
    )

    return (
        any(term in lowered for term in game_terms)
        and not any(term in lowered for term in edit_terms)
    )


def _is_behavioral_html_problem(problem: str) -> bool:
    """Distinguish logic defects from document truncation."""

    lowered = str(problem or "").lower()

    behavioral_terms = (
        "unstable 180-degree reversal",
        "180-degree reversal",
        "allows immediate reversal",
        "unsafe reversal",
        "controls allow",
        "restart behavior",
        "does not restart",
        "not interactive",
        "button does not",
        "control does not",
        "keyboard control",
        "touch control",
        "collision",
        "score does not",
        "game state",
        "logic defect",
        "behavioral",
        "runtime defect",
    )

    structural_terms = (
        "missing closing",
        "no closing",
        "unterminated",
        "truncated",
        "incomplete document",
        "missing </html>",
        "missing </body>",
        "unfinished script",
        "unfinished css",
        "unexpected end",
    )

    if any(term in lowered for term in behavioral_terms):
        return True

    if any(term in lowered for term in structural_terms):
        return False

    return False


def _raw_html_prompt(original_request: str, existing: str = "") -> str:
    # A new game must replace an unrelated page in a reused workspace.
    if existing and _is_fresh_html_game_request(original_request):
        existing = ""

    if existing:
        return mark_raw_artifact(
            (
            "Rewrite this existing browser project as ONE complete self-contained index.html. "
            "Apply the requested change, preserve working features, include CSS and JavaScript inline, and output raw HTML only. "
            "No JSON, markdown, explanation, shell commands, cd, or make. Keep code compact.\n"
            f"CHANGE: {original_request[-240:]}\nEXISTING HTML:\n{existing[:1800]}"
            ),
            minimum_output_tokens=8192,
        )
    return mark_raw_artifact(
        (
        "Create ONE compact self-contained index.html for the request. Put CSS and JavaScript inline. "
        "Use no external files, images, libraries, or fonts. Output raw HTML only, beginning <!doctype html> and ending </html>. "
        "Close every script and body tag. No JSON, markdown, explanation, shell commands, cd, or make. "
        "Prefer short variable names and compact code.\n"
        f"REQUEST: {original_request[-360:]}"
        ),
        minimum_output_tokens=8192,
    )


def _html_continuation_prompt(partial: str, problem: str = "") -> str:
    if _is_behavioral_html_problem(problem):
        return mark_raw_artifact(
            (
                "Return one complete corrected self-contained index.html. "
                "Output raw HTML only, beginning with <!doctype html> and "
                "ending with </html>. Do not explain the changes. "
                "Do not return a fragment or continuation. "
                "Preserve the useful design and features from the rejected "
                "document, but correct the behavioral validation defect.\n\n"
                f"VALIDATION DEFECT:\n{problem}\n\n"
                f"REJECTED DOCUMENT:\n{partial}"
            ),
            minimum_output_tokens=8192,
        )

    tail = partial[-1600:]
    issue = f" The current structural problem is: {problem}." if problem else ""
    return mark_raw_artifact(
        (
        "Continue the unfinished index.html from exactly after its final character."
        f"{issue} Output ONLY missing JavaScript/HTML; never repeat earlier code or opening tags. "
        "Complete the current function and game loop, close every open brace, then close </script>, </body>, and </html>. "
        "End immediately after </html>. No markdown or explanation.\n"
        f"FINAL TAIL:\n{tail}"
        ),
        minimum_output_tokens=4096,
    )


def _join_html_continuation(partial: str, continuation: str) -> str:
    # FULL-DOCUMENT REPAIR:
    # Semantic corrections return a complete replacement document.
    candidate = str(continuation or "").strip()
    lowered_candidate = candidate.lower()
    doctype_position = lowered_candidate.find("<!doctype html")
    html_position = lowered_candidate.find("<html")

    start_position = (
        doctype_position
        if doctype_position >= 0
        else html_position
    )

    if start_position >= 0 and "</html>" in lowered_candidate:
        end_position = (
            lowered_candidate.rfind("</html>")
            + len("</html>")
        )
        return candidate[start_position:end_position].strip()

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


def _one_shot_browser_artifact(*, ask: Callable[[str], Any], original_request: str,
                               workspace: Path, progress: Callable[[str], None]) -> str | None:
    target = workspace / "index.html"
    existing = ""
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8")
        except Exception:
            existing = ""
    progress("Requesting one-shot provider-generated HTML edit" if existing else "Requesting one-shot provider-generated HTML artifact")
    response = ask(_raw_html_prompt(original_request, existing))
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
        response = ask(_html_continuation_prompt(partial, problem))
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


def _compact_repair_prompt(request: str, files: list[str], result: str) -> str:
    return (
        "Return one compact JSON object only. Generate real source files before commands. "
        "Use {\"files\":[{\"path\":\"relative\",\"content\":\"complete code\"}]} or one action. "
        "Never use cd or repeat user words as a command. Never append a complete file; write_file replaces it.\n"
        f"Request: {request[-320:]}\nFiles: {files[-12:]}\nLast result: {result[-450:]}"
    )


def run_adaptive_loop(*, initial_text: str, original_request: str, ask: Callable[[str], Any],
                      workspace: Path | None = None, max_steps: int = 12,
                      progress: Callable[[str], None] | None = None) -> str:
    from sophyane import execution_runtime as runtime
    workspace = (workspace or Path.cwd()).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda _message: None)

    if _browser_request(original_request):
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
