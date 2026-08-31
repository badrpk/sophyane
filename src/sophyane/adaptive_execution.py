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
    text = " ".join(
        str(request or "").casefold().split()
    )

    # SOPHYANE_FULL_STACK_BROWSER_BOUNDARY_V1
    #
    # A browser frontend does not make a multi-layer software product a
    # browser-only artifact. Explicit API + persistence requirements must
    # remain in the multi-file adaptive execution loop.
    full_stack_contract = (
        "sophyane full-stack architecture contract"
        in text
    )

    api_layer = any(
        marker in text
        for marker in (
            "rest api",
            "restful api",
            "rest-style json",
            "backend api",
            "api endpoint",
            "api endpoints",
        )
    )

    persistence_layer = any(
        marker in text
        for marker in (
            "persistent database",
            "persistent local database",
            "persistent sqlite",
            "sqlite database",
            "sqlite3",
            "database file",
        )
    )

    if (
        full_stack_contract
        or (
            api_layer
            and persistence_layer
        )
    ):
        return False

    return any(
        word in text
        for word in (
            "browser",
            "website",
            "web app",
            "html",
            "game",
            "design",
            "touch controls",
        )
    )


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

    # SOPHYANE_NESTED_FILE_BUNDLE_NORMALIZATION_V1
    #
    # Providers may put a multi-file bundle inside the explicit `action`
    # envelope:
    #
    #   {"action": {"files": [...]}}
    #
    # _selected_action() passes that nested dictionary through this
    # normalizer, so recognize the same bundle shape accepted at plan level
    # before attempting scalar action normalization.
    nested_bundle = _file_bundle_action(value)
    if nested_bundle is not None:
        return nested_bundle

    # SOPHYANE_ADAPTIVE_STRING_ACTION_CANONICALIZATION_V1
    #
    # Provider schemas frequently put the operation name in `action`
    # instead of `type`. Canonicalize known executable operations before
    # the older permissive normalization logic can return the raw object.
    #
    # Unknown string actions must NOT fall through as executable objects.
    # In particular, bare `create` is ambiguous. It becomes write_file only
    # when the structure proves that a file write was intended.
    action_value = value.get("action")

    if isinstance(action_value, str):
        action_kind = action_value.strip().casefold()

        if action_kind == "create":
            file_path = str(
                value.get("path")
                or value.get("file")
                or ""
            ).strip()

            has_file_content = (
                "content" in value
                or "text" in value
            )

            if (
                file_path
                and has_file_content
            ):
                canonical = dict(value)
                canonical.pop(
                    "action",
                    None,
                )
                canonical["type"] = "write_file"
                return canonical

            # `create` could mean a directory, project, database, resource,
            # account, file, etc. Do not guess without structural evidence.
            return None

        aliases = {
            "write_file": "write_file",
            "write": "write_file",
            "create_file": "write_file",
            "append_file": "append_file",
            "append": "append_file",
            "mkdir": "mkdir",
            "make_directory": "mkdir",
            "run_command": "run_command",
            "run": "run_command",
            "shell": "run_command",
            "bash": "run_command",
            "run_interactive": "run_interactive",
            "interactive": "run_interactive",
            "open_browser": "open_browser",
            "browser": "open_browser",
            "respond": "respond",
            "response": "respond",
            "answer": "respond",
            "final_answer": "respond",
            "reply": "respond",
            "message": "respond",
        }

        canonical_kind = aliases.get(
            action_kind
        )

        if canonical_kind is None:
            return None

        canonical = dict(value)
        canonical.pop(
            "action",
            None,
        )
        canonical["type"] = canonical_kind
        return canonical

    # SOPHYANE_FILE_SHAPED_CREATE_ALIAS_V1
    #
    # Small local models commonly emit:
    #
    #   {"action":"create","path":"app.py","content":"..."}
    #
    # "create" by itself is ambiguous, but when both a concrete file path
    # and file content are present the intent is structurally equivalent to
    # write_file. Canonicalize that shape locally instead of spending another
    # provider generation on schema repair.
    action_alias = str(
        value.get("action")
        or ""
    ).strip().casefold()

    file_path = str(
        value.get("path")
        or value.get("file")
        or ""
    ).strip()

    has_file_content = (
        "content" in value
        or "text" in value
    )

    if (
        action_alias == "create"
        and file_path
        and has_file_content
    ):
        value.pop(
            "action",
            None,
        )
        value["type"] = "write_file"
        return value
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

    # SOPHYANE_EXECUTABLE_ACTION_TYPE_GATE_V1
    #
    # A dictionary is not automatically an executable action. Returning an
    # untyped object here makes _selected_action() treat provider metadata or
    # unsupported envelopes as executable merely because the dict is truthy.
    # Every normalized action crossing this boundary must identify its runtime
    # operation explicitly.
    if not str(value.get("type") or "").strip():
        return None

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

    # SOPHYANE_DIRECT_TOP_LEVEL_ACTION_V1
    #
    # Some providers return the executable action itself instead of wrapping
    # it in {"action": ...}. Accept that canonical shape directly rather than
    # relying on adapter-specific selected_action() behavior.
    direct = _normalise_action(plan)
    if direct:
        return direct

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



# SOPHYANE_SIMPLE_EMPTY_FILE_RECOVERY_V1
#
# Very small local models sometimes understand a trivial filesystem request
# correctly but emit the operation in an unsupported command-shaped schema,
# for example:
#
#   {"action":"python3 -c ...","artifact":"/tmp/test.py"}
#
# Do not execute or normalize that arbitrary command string. When the
# original user request itself is unambiguously only asking for creation of
# one empty file, recover the requested relative path deterministically and
# feed the existing guarded write_file executor instead.
_SIMPLE_EMPTY_FILE_REQUEST = re.compile(
    r"""
    ^\s*
    (?:please\s+)?
    (?:make|create)
    (?:\s+me)?
    (?:\s+a|\s+an)?
    (?:\s+new)?
    \s+file
    \s+
    (?P<path>
        (?:
            "[^"]+"
            |
            '[^']+'
            |
            [^\s]+
        )
    )
    \s*
    [.!]?
    \s*$
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def _recover_simple_empty_file_action(
    original_request: str,
    plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Recover only an unambiguous one-empty-file creation request."""

    if not isinstance(plan, dict):
        return None

    raw_action = plan.get("action")

    #
    # A valid structured action must continue through the normal executor.
    # Only malformed string-valued actions are candidates for this recovery.
    #
    if not isinstance(raw_action, str) or not raw_action.strip():
        return None

    match = _SIMPLE_EMPTY_FILE_REQUEST.fullmatch(
        str(original_request or "")
    )

    if match is None:
        return None

    requested = match.group("path").strip()

    if (
        len(requested) >= 2
        and requested[0] == requested[-1]
        and requested[0] in {"'", '"'}
    ):
        requested = requested[1:-1].strip()

    if not requested:
        return None

    candidate = Path(requested)

    #
    # Never create an absolute destination or escape the active workspace.
    #
    if candidate.is_absolute():
        return None

    if any(
        part in {"", ".", ".."}
        for part in candidate.parts
    ):
        return None

    #
    # The artifact field proves the malformed response was attempting a file
    # operation, but its destination is not trusted. The user's relative path
    # remains authoritative.
    #
    artifact = plan.get("artifact")

    if not isinstance(artifact, str) or not artifact.strip():
        return None

    return {
        "type": "write_file",
        "path": requested,
        "content": "",
        "replace": True,
        "artifact_source": "simple_empty_file_recovery",
    }



def _command_text(action: dict[str, Any]) -> str:
    argv = action.get("argv")
    if isinstance(argv, list):
        return shlex.join(str(x) for x in argv)
    return str(action.get("command") or action.get("content") or action.get("cmd") or "").strip()


# SOPHYANE_DUPLICATE_READ_ONLY_INSPECTION_V1
#
# A repeated read-only inspection may be useful evidence, but it cannot prove
# that a requested mutation happened. This classifier is intentionally scoped
# to the duplicate-command completion boundary.
def _is_read_only_inspection_command(
    command: str,
) -> bool:
    try:
        tokens = shlex.split(
            str(command or "").strip()
        )
    except ValueError:
        return False

    if not tokens:
        return False

    first = Path(
        tokens[0]
    ).name.casefold()

    if first in {
        "cat",
        "head",
        "tail",
        "sed",
        "grep",
        "egrep",
        "fgrep",
        "find",
        "ls",
        "stat",
        "wc",
        "pwd",
        "tree",
        "file",
        "readlink",
        "realpath",
    }:
        return True

    if first != "git":
        return False

    if len(tokens) < 2:
        return True

    subcommand = tokens[1].casefold()

    return subcommand in {
        "status",
        "diff",
        "show",
        "log",
        "rev-parse",
        "ls-files",
        "remote",
    }


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

        # SOPHYANE_INTENTIONAL_EMPTY_FILE_V1
        # Ordinary empty model writes remain invalid. The deterministic
        # simple-empty-file recovery is the only intentional exception.
        if (
            not content
            and action.get("artifact_source")
            != "simple_empty_file_recovery"
        ):
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


def _full_stack_initial_bundle_prompt(
    original_request: str,
) -> str:
    """Request the first bounded full-stack implementation increment.

    SOPHYANE_FULL_STACK_CONTEXT_DECOMPOSITION_V1

    SLI owns project decomposition. The provider owns only one compact,
    context-safe implementation increment at a time.

    The first increment establishes the executable backend foundation.
    Subsequent frontend, tests and documentation increments are requested
    only after the runtime has materialized and validated earlier files.
    """
    request = str(
        original_request
        or ""
    ).strip()

    return (
        "FULL-STACK IMPLEMENTATION INCREMENT 1.\n"
        "Return exactly one executable JSON action.\n"
        "No Markdown. No explanation. No multiple files.\n\n"

        "SLI owns the project plan and later increments. "
        "Your only task in this generation is backend/app.py.\n\n"

        "ACTION CONTRACT:\n"
        "{\"action\":{\"type\":\"write_file\","
        "\"path\":\"backend/app.py\","
        "\"content\":\"...complete Python source...\"}}\n\n"

        "BACKEND REQUIREMENTS:\n"
        "- Python standard library only.\n"
        "- sqlite3 persistent database.\n"
        "- ThreadingHTTPServer.\n"
        "- BaseHTTPRequestHandler.\n"
        "- Bind to 127.0.0.1 only.\n"
        "- Deterministic schema initialization.\n"
        "- Deterministic seed/demo rows.\n"
        "- GET /api/projects.\n"
        "- GET /api/tasks.\n"
        "- POST /api/tasks.\n"
        "- PUT /api/tasks/{id}.\n"
        "- DELETE /api/tasks/{id}.\n"
        "- GET /api/stats.\n"
        "- Search/filter query handling.\n"
        "- Validate required fields, status and priority.\n"
        "- Structured JSON errors with useful HTTP codes.\n"
        "- Per-request SQLite connections safe for "
        "ThreadingHTTPServer.\n"
        "- Serve static files if the static directory exists.\n\n"

        "Do not generate frontend files, tests, README, "
        "requirements.txt or prose in this turn.\n"
        "Do not use Flask, FastAPI, Django or third-party packages.\n"
        "The Python file must be syntactically complete and executable.\n\n"

        "USER REQUEST:\n"
        + request
    )



def _full_stack_next_increment_prompt(
    original_request: str,
    files: list[str],
) -> str | None:
    """Choose the next deterministic full-stack artifact.

    SOPHYANE_FULL_STACK_CONTEXT_DECOMPOSITION_V1
    """
    existing = {
        str(path).replace("\\", "/")
        for path in files
    }

    increments = (
        (
            "static/index.html",
            (
                "Create static/index.html only. "
                "Return exactly one write_file JSON action. "
                "Build a responsive task-management interface with "
                "dashboard statistics, project/task controls, forms, "
                "search/filter controls and hooks for static/app.js. "
                "Do not include JavaScript implementation inline unless "
                "required for minimal bootstrapping."
            ),
        ),
        (
            "static/app.js",
            (
                "Create static/app.js only. "
                "Return exactly one write_file JSON action. "
                "Use vanilla JavaScript fetch() against the real REST API. "
                "Implement loading, create, edit, delete, status changes, "
                "priority/due-date handling, dashboard refresh, search and "
                "filtering. No localStorage replacement for backend state."
            ),
        ),
        (
            "static/style.css",
            (
                "Create static/style.css only. "
                "Return exactly one write_file JSON action. "
                "Provide a compact responsive layout for the existing "
                "task-management frontend. No external CSS frameworks."
            ),
        ),
        (
            "tests/test_app.py",
            (
                "Create tests/test_app.py only. "
                "Return exactly one write_file JSON action. "
                "Use pytest or unittest with only available Python "
                "dependencies. Exercise backend CRUD, validation, stats, "
                "and search/filter behavior against isolated temporary "
                "storage where practical."
            ),
        ),
        (
            "README.md",
            (
                "Create README.md only. "
                "Return exactly one write_file JSON action. "
                "Document startup, test command, local URL, architecture "
                "and persistence behavior concisely."
            ),
        ),
    )

    for relative_path, instruction in increments:
        if relative_path not in existing:
            return (
                "FULL-STACK IMPLEMENTATION NEXT INCREMENT.\\n"
                "SLI owns decomposition. Implement only the requested "
                "artifact.\\n"
                "No Markdown wrapper. No prose outside the JSON action.\\n\\n"
                + instruction
                + "\\n\\nExisting project files:\\n- "
                + "\\n- ".join(sorted(existing))
                + "\\n\\nOriginal user request:\\n"
                + str(original_request or "").strip()
            )

    return None



# SOPHYANE_SINGLE_FILE_EXECUTION_VERIFICATION_V1
#
# Some small coding requests contain three explicit acceptance requirements:
#
#   1. write one Python file;
#   2. run that file;
#   3. verify an exact stdout value.
#
# A successful write, including an identical/no-op replacement, satisfies only
# the filesystem part.  Detect the remaining deterministic execution contract
# locally so the provider is not asked to rediscover the next action.
def _single_file_execution_verification(
    original_request: str,
    action: dict[str, Any],
) -> tuple[str, str] | None:
    kind = str(action.get("type") or "").strip().casefold()

    if kind not in {"write_file", "append_file"}:
        return None

    relative_path = str(
        action.get("path")
        or action.get("file")
        or ""
    ).strip()

    if (
        not relative_path
        or not relative_path.casefold().endswith(".py")
    ):
        return None

    request = str(original_request or "")

    # Require an explicit execution/verification request.  Merely asking for a
    # Python file must retain the existing simple-file completion behavior.
    execution_requested = bool(
        re.search(
            r"""
            (?:
                \bthen\s+run\b
                |
                \brun\s+(?:the\s+)?file\b
                |
                \bexecute\s+(?:the\s+)?file\b
                |
                \brun\s+it\b
                |
                \bverify\b[^\n]{0,120}\boutput\b
            )
            """,
            request,
            flags=re.I | re.X,
        )
    )

    if not execution_requested:
        return None

    expected: str | None = None

    patterns = (
        # Example:
        #
        # prints exactly:
        #
        # SOPHYANE_TEST_OK
        r"""
        \bprints?\s+exactly\s*:?
        [ \t]*(?:\r?\n)+
        [ \t]*([^\r\n]+)
        """,

        # Example:
        # output is exactly SOPHYANE_TEST_OK
        r"""
        \boutput\s+(?:is|must\s+be|should\s+be)\s+exactly
        \s*:?\s*
        ["'`]?
        ([^\r\n"'`]+?)
        ["'`]?
        (?=\s*(?:[.!]?\s*$|\r?\n))
        """,
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            request,
            flags=re.I | re.X,
        )

        if match:
            candidate = match.group(1).strip()

            # Do not accidentally capture the next instruction.
            if candidate:
                expected = candidate
                break

    if expected is None:
        return None

    command = (
        f"{shlex.quote(sys.executable)} "
        f"{shlex.quote(relative_path)}"
    )

    return command, expected


def _compact_repair_prompt(request: str, files: list[str], result: str) -> str:
    existing = ", ".join(files[-40:]) if files else "(none)"
    return (
        "ADAPTIVE EXECUTION REPAIR FOR THE CURRENT TASK. "
        "Ignore unrelated cached output and any previous-task response. "
        "Repair response serialization/schema only; preserve the exact "
        "original task semantics. Do not introduce pytest, TDD, a function "
        "signature, or another requirement unless ORIGINAL TASK requests it. "
        "A handled/ok/capability/summary/evidence object is an execution "
        "RESULT, not an executable action; never return that result shape. "
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



# SOPHYANE_FULL_STACK_SERVICE_FABRIC_CUTOVER_V1


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

    # SOPHYANE_FULL_STACK_BUNDLE_FIRST_V1
    #
    # Complex software products should not require one provider generation
    # per tiny file. If the provider already returned a multi-file project
    # bundle, materialize it immediately and move into deterministic
    # verification. Provider calls are then reserved for targeted repair.
    #
    # This preserves the general adaptive loop while reducing slow local-LLM
    # round trips on full-stack builds.
    bundle_first_full_stack = (
        "sophyane full-stack architecture contract"
        in str(original_request or "").casefold()
    )

    # SOPHYANE_FULL_STACK_INITIAL_BUNDLE_V1
    #
    # Bundle-first must be active rather than merely opportunistic.
    # The planning/approval provider output frequently contains only a small
    # first action. For a classified full-stack build, make exactly one
    # dedicated implementation call asking for the complete compact project
    # skeleton before entering the iterative repair loop.
    if bundle_first_full_stack:
        try:
            initial_bundle = ask(
                _full_stack_initial_bundle_prompt(
                    original_request
                )
            )

            candidate = getattr(
                initial_bundle,
                "text",
                str(initial_bundle),
            )

            if candidate.strip():
                current = candidate
                progress(
                    "SLI Full-Stack Bundle-First: "
                    "received dedicated initial implementation response"
                )

        except Exception as error:
            progress(
                "SLI Full-Stack Bundle-First request failed; "
                "falling back to existing provider output: "
                f"{type(error).__name__}: {error}"
            )

    evidence: list[str] = []
    repairs = 0
    successful_commands: set[str] = set()

    # SOPHYANE_VERIFIED_MUTATION_COMPLETION_STOP_V1
    #
    # Track whether this execution loop has actually changed workspace
    # artifact state. A later successful meaningful verification command may
    # terminate the request only after such a mutation has occurred.
    workspace_mutated = False

    # A provider may initially return a complete multi-file Markdown project.
    # Materialize that bundle once. Subsequent iterations must inspect, build,
    # test or perform targeted repairs instead of regenerating the project.
    markdown_bundle_written = False

    # SOPHYANE_INITIAL_BUNDLE_MATERIALIZED_V1
    #
    # Track the semantic event rather than the provider serialization.
    # A full-stack project may arrive as Markdown, {"files":[...]}, or another
    # normalized batch representation. Deterministic verification must begin
    # after any successful initial multi-file bundle, not only Markdown.
    initial_bundle_materialized = False

    # Deterministic post-generation verification is a small state machine:
    # create an isolated project environment, install dependencies with an
    # Android-friendly timeout, then run the project's own tests.
    deterministic_verification_stage = ""

    for step in range(1, max_steps + 1):
        # After the initial multi-file bundle is materialized, do not depend on
        # the provider to emit a run_command action. Sophyane owns the next
        # deterministic step: install declared dependencies and execute tests.
        if deterministic_verification_stage == "prepare":
            # SOPHYANE_FULL_STACK_STDLIB_VERIFY_V1
            #
            # A classified full-stack local product has a fixed stdlib-only
            # architecture. It must not create another virtualenv or install
            # dependencies. Verify the generated Python directly with the
            # already-running Sophyane interpreter.
            if bundle_first_full_stack:
                action = {
                    "type": "run_command",
                    "command": (
                        f"{shlex.quote(sys.executable)} -m compileall -q "
                        "backend tests"
                    ),
                    "timeout": 120,
                    "deterministic_post_bundle_verification":
                        "full_stack_syntax",
                }
                plan = None
                deterministic_verification_stage = (
                    "full_stack_syntax_running"
                )
                progress(
                    "SLI Full-Stack Verification: "
                    "checking generated Python syntax"
                )
            else:
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

        elif deterministic_verification_stage == "full_stack_test":
            action = {
                "type": "run_command",
                "command": (
                    f"{shlex.quote(sys.executable)} -m pytest -q"
                ),
                "timeout": 300,
                "deterministic_post_bundle_verification":
                    "full_stack_test",
            }
            plan = None
            deterministic_verification_stage = (
                "full_stack_test_running"
            )
            progress(
                "SLI Full-Stack Verification: "
                "running generated automated tests"
            )

        elif deterministic_verification_stage == "full_stack_fabric":
            progress(
                "SLI Full-Stack Verification: "
                "handing generated application lifecycle "
                "to Service Fabric"
            )

            from sophyane.full_stack_verification import (
                verify_full_stack_application,
            )

            ok, result = (
                verify_full_stack_application(
                    workspace,
                    progress,
                )
            )

            evidence.append(
                "Service Fabric verification:\n"
                + result
            )

            if ok:
                evidence.append(
                    "Full-stack deterministic verification passed: "
                    "syntax, tests, Service Fabric lifecycle, "
                    "frontend HTTP and grounded REST API."
                )

                return (
                    "Project implementation and verification completed "
                    "successfully.\n\nWorkspace: "
                    + str(workspace)
                    + "\n\nExecution evidence:\n"
                    + "\n".join(evidence)
                )

            progress(
                "SLI Full-Stack Verification: "
                "Service Fabric verification failed; "
                "entering targeted repair"
            )

            deterministic_verification_stage = ""

            current = _compact_repair_prompt(
                original_request,
                _files(workspace),
                result,
            )

            repairs = 0
            continue

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

            if action is None and plan is not None:
                action = _recover_simple_empty_file_action(
                    original_request,
                    plan,
                )

                if action is not None:
                    progress(
                        "Recovered simple empty-file request without "
                        "provider schema repair"
                    )
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
            # SOPHYANE_DUPLICATE_COMMAND_COMPLETION_GATE_V1
            #
            # A previously successful command is not automatically proof that
            # the user's task is complete. In particular, read-only inspection
            # commands such as sed/cat/find/grep may exit 0 repeatedly while
            # the requested source mutation has never happened.
            #
            # Only commands that the existing verification policy recognizes
            # as meaningful verification may terminate the loop here.
            synthetic_result = (
                f"Command: {command_text}\n"
                "Exit code: 0\n"
                "STDOUT:\npreviously successful\n"
                "STDERR:\n"
            )

            if (
                not _is_read_only_inspection_command(
                    command_text
                )
                and verification_result_is_meaningful(
                    command_text,
                    synthetic_result,
                )
            ):
                result = (
                    "Meaningful verification already passed earlier with "
                    f"exit code 0: {command_text}"
                )

                evidence.append(
                    f"Step {step}: {result}"
                )

                progress(result)

                return (
                    "Project implementation and verification completed "
                    "successfully.\n\nExecution evidence:\n"
                    + "\n".join(evidence)
                )

            result = (
                "Previously successful command was inspection/non-verifying; "
                "it cannot complete the task: "
                f"{command_text}"
            )

            evidence.append(
                f"Step {step}: {result}"
            )

            progress(result)

            current = _compact_repair_prompt(
                original_request,
                _files(workspace),
                result,
            )

            continue

        ok, result = _execute(runtime, action, workspace, progress)

        # SOPHYANE_PYTHON_WRITE_VALIDATION_GATE_V1
        #
        # A successful filesystem write is not enough to count as a
        # successful coding step. Small local models may emit truncated or
        # malformed Python. Validate newly written Python immediately before
        # asking the provider for another action.
        if (
            ok
            and kind in {"write_file", "append_file"}
        ):
            raw_path = str(
                action.get("path")
                or action.get("file")
                or ""
            ).strip()

            if raw_path.lower().endswith(".py"):
                candidate = (
                    workspace
                    / raw_path
                ).resolve()

                try:
                    candidate.relative_to(
                        workspace.resolve()
                    )
                except ValueError:
                    ok = False
                    result = (
                        "Python validation rejected file outside "
                        "the active workspace."
                    )
                else:
                    if candidate.is_file():
                        import py_compile

                        try:
                            py_compile.compile(
                                str(candidate),
                                doraise=True,
                            )
                        except py_compile.PyCompileError as error:
                            ok = False
                            result = (
                                "Python syntax validation failed immediately "
                                f"after writing {raw_path}.\n"
                                f"{error.msg}\n"
                                "Repair this exact file before creating "
                                "any additional project files."
                            )
                            progress(
                                "Python write validation failed: "
                                f"{raw_path}"
                            )
                        else:
                            progress(
                                "Python write validation passed: "
                                f"{raw_path}"
                            )
        evidence.append(f"Step {step}: {result}")

        # SOPHYANE_SINGLE_FILE_EXECUTION_VERIFICATION_FLOW_V1
        #
        # Do not spend another provider turn asking what follows an explicitly
        # requested Python write + run + exact-output task.  The execution
        # requirement is deterministic and can be checked immediately.
        #
        # This deliberately also runs after an identical write_file semantic
        # no-op.  A no-op may mean the file is already correct, or—as observed
        # in the live regression—that the provider is repeatedly proposing the
        # same wrong content.  Real execution distinguishes those cases.
        # SOPHYANE_SINGLETON_BATCH_EXECUTION_VERIFICATION_V1
        #
        # Provider Markdown/file bundles are normalized to a batch even when
        # they contain exactly one write_file.  For deterministic
        # "write this Python file, run it, verify exact stdout" acceptance,
        # treat that singleton child as the effective action.
        verification_action = action

        if (
            ok
            and kind == "batch"
        ):
            children = action.get("actions")

            if (
                isinstance(children, list)
                and len(children) == 1
                and isinstance(children[0], dict)
                and str(
                    children[0].get("type")
                    or ""
                ).strip().casefold()
                in {"write_file", "append_file"}
            ):
                verification_action = children[0]

        single_file_verification = (
            _single_file_execution_verification(
                original_request,
                verification_action,
            )
            if ok
            else None
        )

        if single_file_verification is not None:
            verify_command, expected_stdout = (
                single_file_verification
            )

            progress(
                "Deterministic single-file verification: "
                f"{verify_command}"
            )

            verify_action = {
                "type": "run_command",
                "command": verify_command,
                "timeout": 60,
            }

            verify_ok, verify_result = _execute(
                runtime,
                verify_action,
                workspace,
                progress,
            )

            evidence.append(
                f"Step {step} verification: {verify_result}"
            )

            actual_stdout = _command_stdout(
                verify_result
            )

            if (
                verify_ok
                and actual_stdout == expected_stdout
            ):
                progress(
                    "Deterministic single-file verification passed: "
                    f"stdout exactly matched {expected_stdout!r}"
                )

                return (
                    "Project implementation and verification completed "
                    "successfully.\n\nWorkspace: "
                    + str(workspace)
                    + "\n\nExecution evidence:\n"
                    + "\n".join(evidence)
                )

            ok = False
            result = (
                "Deterministic single-file execution verification failed.\n"
                f"Command: {verify_command}\n"
                f"Expected exact stdout: {expected_stdout!r}\n"
                f"Actual stdout: {actual_stdout!r}\n"
                "Repair the requested Python file, then it will be "
                "executed and checked again."
            )

            evidence.append(
                f"Step {step} acceptance: {result}"
            )

            progress(
                "Deterministic single-file verification failed; "
                "requesting targeted repair"
            )

        if (
            ok
            and kind in {
                "write_file",
                "append_file",
                "batch",
            }
        ):
            workspace_mutated = True

        verification_phase = action.get(
            "deterministic_post_bundle_verification"
        )

        if (
            verification_phase == "full_stack_syntax"
            and ok
        ):
            deterministic_verification_stage = (
                "full_stack_test"
            )
            progress(
                "SLI Full-Stack Verification: "
                "syntax passed"
            )

        elif (
            verification_phase == "full_stack_test"
            and ok
        ):
            deterministic_verification_stage = (
                "full_stack_fabric"
            )
            progress(
                "SLI Full-Stack Verification: "
                "tests passed; Service Fabric owns runtime verification"
            )

        elif verification_phase == "prepare":
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

            # SOPHYANE_VERIFIED_MUTATION_COMPLETION_STOP_V1
            #
            # A requested mutation followed by its first meaningful command
            # verification is already a complete execution proof. Do not ask
            # the provider to invent another verifier and then enter schema
            # repair merely to rediscover the same success.
            #
            # Full-stack bundle verification remains owned by its explicit
            # deterministic state machine and therefore does not use this
            # generic early-stop path.
            if (
                workspace_mutated
                and not deterministic_verification_stage
                and not bundle_first_full_stack
            ):
                return (
                    "Project implementation and verification completed "
                    "successfully.\n\nWorkspace: "
                    + str(workspace)
                    + "\n\nExecution evidence:\n"
                    + "\n".join(evidence)
                )

        # Repair attempts are consecutive-failure limits, not a lifetime
        # allowance. A successful action proves recovery and resets the budget.
        if ok:
            repairs = 0

            # SOPHYANE_FULL_STACK_BUNDLE_VERIFY_V1
            #
            # Once an initial full-stack multi-file bundle exists, Sophyane
            # should verify locally before asking the model what to do next.
            # SOPHYANE_JSON_BUNDLE_VERIFICATION_HANDOFF_V1
            #
            # Batch success is sufficient evidence that a normalized multi-file
            # project bundle was materialized. Do not require the source format
            # to have been Markdown.
            if (
                bundle_first_full_stack
                and kind == "batch"
            ):
                children = action.get(
                    "actions"
                )

                if (
                    isinstance(children, list)
                    and len(children) >= 2
                ):
                    initial_bundle_materialized = True

            if (
                bundle_first_full_stack
                and initial_bundle_materialized
                and not deterministic_verification_stage
            ):
                deterministic_verification_stage = "prepare"
                progress(
                    "SLI Full-Stack Verification: "
                    "initial multi-file bundle materialized; "
                    "deterministic verification owns next steps"
                )

        if not ok:
            if repairs >= 2:
                return "Execution stopped safely after bounded repair attempts.\n\n" + "\n".join(evidence)
            repairs += 1
            response = ask(_compact_repair_prompt(original_request, _files(workspace), result))
            current = getattr(response, "text", str(response))
            continue
        if kind in {"respond", "message", "open_browser", "browser"}:
            return (result or "Completed.") + "\n\nExecution evidence:\n" + "\n".join(evidence)
        # SOPHYANE_FULL_STACK_CONTEXT_DECOMPOSITION_V1
        #
        # A successful full-stack file write advances the deterministic
        # artifact manifest before asking the model for another generic action.
        # This keeps each local generation bounded to one file and prevents
        # whole-project regeneration inside a 2048-token context.
        if (
            bundle_first_full_stack
            and ok
            and kind in {"write_file", "append_file"}
        ):
            next_increment = (
                _full_stack_next_increment_prompt(
                    original_request,
                    _files(workspace),
                )
            )

            if next_increment is not None:
                progress(
                    "SLI Full-Stack Decomposition: "
                    "requesting next bounded artifact"
                )

                response = ask(
                    next_increment
                )

                current = getattr(
                    response,
                    "text",
                    str(response),
                )

                continue

            initial_bundle_materialized = True

            if not deterministic_verification_stage:
                deterministic_verification_stage = "prepare"

            progress(
                "SLI Full-Stack Decomposition: "
                "required artifact manifest complete; "
                "deterministic verification owns next steps"
            )

            current = ""
            continue

        response = ask(
            _compact_repair_prompt(
                original_request,
                _files(workspace),
                result,
            )
        )
        current = getattr(
            response,
            "text",
            str(response),
        )
    return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)


def install() -> None:
    from sophyane import execution_runtime
    execution_runtime.run_structured_loop = run_adaptive_loop
