"""Provider-driven adaptive execution for Sophyane.

Application code always comes from the configured provider. This module only adapts
model output into safe workspace artifacts, execution and mechanical verification.
"""
from __future__ import annotations

import os


# SOPHYANE_VISUALIZATION_INTENT_FAST_PATH_V1
def try_visualization_intent(
    request: str,
    workspace,
):
    """Handle grounded visualization intent without provider dependence.

    This helper is intentionally separate from provider/mode routing.
    A caller may invoke it before LLM selection when the user's request
    already contains enough grounded numeric data to render deterministically.

    If semantic extraction from a PDF/file/retrieval result is required,
    ordinary Sophyane capability routing may first ground that data and then
    call the same renderer.
    """

    from pathlib import Path

    from sophyane.visualization_capability import (
        detect_visualization_intent,
        render_visualization,
        visualization_response_text,
    )

    intent = detect_visualization_intent(
        request
    )

    if not intent.requested:
        return None

    result = render_visualization(
        request=request,
        workspace=Path(
            workspace
        ),
    )

    if not bool(
        result.get(
            "handled"
        )
    ):
        #
        # Visualization intent exists, but deterministic grounding is not
        # sufficient yet. Return None so the normal Sophyane pipeline can
        # acquire/extract data instead of fabricating it.
        #
        return None

    return {
        "capability":
            "visualization",
        "handled":
            True,
        "result":
            result,
        "response":
            visualization_response_text(
                result
            ),
    }


from sophyane.environment_constraints import verification_result_is_meaningful
from sophyane.providers.base import ProviderError

import re
import shlex
import sys
import shutil
from pathlib import Path
from typing import Any, Callable


def _files(workspace: Path) -> list[str]:
    return [str(p.relative_to(workspace)) for p in sorted(workspace.rglob("*")) if p.is_file()]


def _explicit_no_edit_request(request: str) -> bool:
    text = " ".join(str(request or "").casefold().split())
    source_authorized = "source edits are explicitly authorized" in text

    global_prohibition = bool(
        re.search(
            r"\bdo not\s+(?:edit|modify|write|create)(?:\s+or\s+(?:edit|modify|write|create))*\s+"
            r"(?:(?:any|all|every)\s+)?files?\b",
            text,
        )
        or re.search(r"\bdo not\s+(?:edit|modify|write)\s+existing files?\b", text)
        or re.search(
            r"\bdo not\s+(?:edit|modify|write|create)\s+"
            r"(?:the\s+)?(?:repository|codebase|workspace|anything)\b",
            text,
        )
        or re.search(
            r"\bdo not create\b[^.!?\n]*\bor\s+(?:edit|modify|write)\b"
            r"[^.!?\n]*\bfiles?\b",
            text,
        )
    )
    if global_prohibition:
        return True

    if source_authorized:
        return False

    if "read-only" in text or "read only" in text:
        return True

    if any(marker in text for marker in ("no edits", "no writes")):
        return True

    return False


def _browser_request(request: str) -> bool:
    text = " ".join(
        str(request or "").casefold().split()
    )

    # Explicit no-edit authority outranks incidental browser vocabulary.
    if _explicit_no_edit_request(request):
        return False

    # SOPHYANE_CURRENT_TURN_REPOSITORY_AUTHORITY_V12
    #
    # Explicit repository/codebase implementation intent belongs to the
    # general software execution loop even when the same request contains
    # architecture/design language.
    #
    # Generic words such as "design" must never be sufficient by themselves
    # to convert a repository implementation request into a browser artifact.
    repository_authority = (
        any(
            marker in text
            for marker in (
                "repository",
                "codebase",
                "source code",
                "existing architecture",
                "existing project",
                "existing code",
            )
        )
        and any(
            marker in text
            for marker in (
                "implement",
                "modify",
                "repair",
                "fix",
                "update",
                "inspect",
                "change",
                "develop",
            )
        )
    )

    if repository_authority:
        return False

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

    explicit_browser_intent = any(
        marker in text
        for marker in (
            "browser",
            "website",
            "web app",
            "html",
            "frontend",
            "front-end",
            "client-side",
            "client side",
            "touch controls",
        )
    )

    # "game" is retained as historical browser intent because Sophyane's
    # browser-game path is an existing concrete capability.
    game_intent = "game" in text

    return (
        explicit_browser_intent
        or game_intent
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
    # SOPHYANE_FULL_CLOUD_TASK_CONTEXT_V1
    #
    # Never silently throw away the beginning of the immutable user request or
    # most of the artifact before asking a frontier provider to implement it.
    # Transport/provider-specific budgeting belongs at the provider-context
    # layer, not inside a task-specific prompt builder.
    if existing:
        return (
            "Rewrite this existing browser project as ONE complete self-contained index.html. "
            "Apply the requested change, preserve working features, include CSS and JavaScript inline, "
            "and output raw HTML only. No JSON, markdown, explanation, shell commands, cd, or make. "
            "Prioritize correctness, completeness, maintainability, interaction quality, responsive polish "
            "and faithful implementation of the complete customer request.\n"
            f"CHANGE:\n{original_request}\n"
            f"EXISTING HTML:\n{existing}"
        )
    return (
        "Create ONE polished responsive self-contained index.html for the complete request. "
        "Put CSS and JavaScript inline. For visual websites, high-quality HTTPS images from "
        "Unsplash, Pexels, or Pixabay are allowed when they materially improve the product; "
        "prefer meaningful imagery, strong hierarchy, typography, spacing and mobile polish. "
        "Use no external JavaScript libraries or fonts. Output raw HTML only, beginning <!doctype html> "
        "and ending </html>. Close every script and body tag. No JSON, markdown, explanation, "
        "shell commands, cd, or make. Prioritize correctness, completeness, maintainability and "
        "product quality rather than artificially minimizing source size.\n"
        f"REQUEST:\n{original_request}"
    )


def _html_continuation_prompt(partial: str, problem: str = "") -> str:
    # SOPHYANE_FULL_STRUCTURAL_RECOVERY_CONTEXT_V1
    #
    # The frontier model receives the complete preserved artifact so it can
    # resolve symbols, scopes and structures defined well before the cutoff.
    issue = f" The current structural problem is: {problem}." if problem else ""
    return (
        "Continue the unfinished index.html from exactly after its final character."
        f"{issue} The complete preserved artifact is provided below for context. "
        "Output ONLY the missing continuation; never repeat earlier code or opening tags. "
        "Close every structure that remains open and finish </script>, </body>, and </html> as required. "
        "End immediately after </html>. No markdown or explanation.\n"
        f"COMPLETE PRESERVED ARTIFACT:\n{partial}"
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

    # SOPHYANE_BROWSER_STRUCTURED_ONE_SHOT_WRITE_V1
    #
    # NIFDU may obey the runtime action contract even when this browser path
    # requested raw HTML. Accept one complete index.html write action here so
    # the artifact remains atomic instead of falling through into regenerative
    # write/append chunking.
    structured_html = None
    structured_response = False

    try:
        from sophyane import execution_runtime as runtime

        structured_plan = runtime.extract_plan(raw)
        structured_response = structured_plan is not None
        structured_action = (
            _selected_action(runtime, structured_plan)
            if structured_plan
            else None
        )

        if (
            isinstance(structured_action, dict)
            and str(
                structured_action.get("type") or ""
            ).strip().casefold() == "write_file"
            and Path(
                str(
                    structured_action.get("path")
                    or structured_action.get("file")
                    or ""
                )
            ).name.casefold() == "index.html"
            and isinstance(
                structured_action.get("content"),
                str,
            )
        ):
            structured_html = structured_action["content"]
            progress(
                "Recovered complete structured index.html from "
                "one-shot provider response"
            )
    except Exception as error:
        progress(
            "Structured one-shot browser extraction failed safely: "
            f"{type(error).__name__}: {error}"
        )

    # SOPHYANE_BROWSER_STRUCTURED_ACTION_FALLBACK_GATE_V1
    #
    # Once the response has been recognized as a runtime action, do not scan
    # its serialized JSON text for incidental embedded HTML. In particular an
    # append_file action must never be promoted into a complete one-shot file
    # merely because its content happens to contain closing HTML tags.
    if structured_html is not None:
        html = structured_html
        partial = _extract_partial_html(
            structured_html
        )
    elif structured_response:
        html = None
        partial = None
    else:
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

        if action_kind in {"inspect", "read_file"}:
            canonical = dict(value)
            path = canonical.get("path") or canonical.get("file")
            if not isinstance(path, str) or not path.strip():
                return None
            canonical["type"] = "read_file"
            canonical["path"] = path.strip()
            canonical.pop("action", None)
            canonical.pop("file", None)
            return canonical

        aliases = {
            "inspect": "read_file",
            "read_file": "read_file",
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
        "inspect": "read_file",
        "read_file": "read_file",
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

    if value.get("type") == "read_file":
        path = value.get("path") or value.get("file")
        if not isinstance(path, str) or not path.strip():
            return None
        value["path"] = path.strip()
        value.pop("file", None)

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



def _command_references_workspace_artifact(
    command: str,
    workspace: Path,
) -> bool:
    """Return whether a command names an existing workspace artifact."""
    lowered = str(command or "").casefold()
    for name in _files(workspace):
        candidate = str(name).strip()
        if candidate and candidate.casefold() in lowered:
            return True
    return False


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
def _is_process_observation_command(
    command: str,
) -> bool:
    """Return True for commands that only observe process/runtime state.

    A successful observation proves that the inspection command worked.
    It does not prove that the observed long-running task completed.
    """
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        return False

    if not parts:
        return False

    # Ignore simple wrappers that preserve observation-only semantics.
    while parts and parts[0] in {
        "env",
        "command",
    }:
        parts = parts[1:]

    if not parts:
        return False

    executable = Path(parts[0]).name

    return executable in {
        "ps",
        "pgrep",
        "pidof",
        "pstree",
        "jobs",
    }


def _is_read_only_inspection_command(
    command: str,
) -> bool:
    # SOPHYANE_PROCESS_OBSERVATION_NONTERMINAL_V1
    #
    # Process inspection can establish RUNNING / PRESENT / ABSENT state,
    # but never successful completion of the observed task.
    if _is_process_observation_command(command):
        return True
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
        "rg",
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


def _no_edit_shell_syntax_safe(command: str) -> bool:
    """Reject shell syntax capable of changing execution semantics."""
    # SOPHYANE_NO_EDIT_SHELL_SYNTAX_GUARD_V1
    value = str(command or '')
    if not value.strip():
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    if any(char in value for char in ';|&<>$`'):
        return False
    return True


def _no_edit_restricted_compound_inspection(
    command: str,
) -> bool:
    """Admit only explicitly reviewed inspection compositions."""
    # SOPHYANE_RESTRICTED_COMPOUND_INSPECTION_V1
    return str(command or "").strip() in {
        "pwd && find . -maxdepth 2 -type f -print | sort",
        "find . -maxdepth 2 -type f -print | sort",
    }


def _no_edit_find_arguments_safe(command: str) -> bool:
    """Reject execution and mutation predicates in find commands."""
    try:
        tokens = shlex.split(str(command or "").strip())
    except ValueError:
        return False

    if not tokens:
        return False

    if Path(tokens[0]).name.casefold() != "find":
        return True

    forbidden = {
        "-delete",
        "-exec",
        "-execdir",
        "-ok",
        "-okdir",
        "-fprint",
        "-fprint0",
        "-fprintf",
        "-fls",
    }

    return not any(
        token.casefold() in forbidden
        for token in tokens[1:]
    )


def _no_edit_command_allowed(command: str) -> bool:
    """Allow bounded inspection plus explicit test-suite verification."""
    if _no_edit_restricted_compound_inspection(command):
        return True
    if not _no_edit_shell_syntax_safe(command):
        return False
    if not _no_edit_find_arguments_safe(command):
        return False
    if _is_read_only_inspection_command(command):
        return True

    try:
        tokens = shlex.split(
            str(command or "").strip()
        )
    except ValueError:
        return False

    if not tokens:
        return False

    first = Path(tokens[0]).name.casefold()

    if first in {"pytest", "py.test"}:
        return True

    if (
        first.startswith("python")
        and len(tokens) >= 3
        and tokens[1] == "-m"
        and tokens[2] == "pytest"
    ):
        return True

    return False


def _explicit_read_only_cli_requested(
    request: str,
) -> bool:
    """Return True only when execution/demo of a CLI was requested."""
    normalized = " ".join(
        str(request or "").casefold().split()
    )

    return any(
        phrase in normalized
        for phrase in (
            "demonstrate the cli",
            "demo the cli",
            "run the cli",
            "execute the cli",
        )
    )


def _existing_python_cli_command(
    command: str,
    workspace: Path | None,
) -> bool:
    """Recognize a narrow invocation of an existing Python script."""
    if workspace is None:
        return False

    try:
        tokens = shlex.split(
            str(command or "").strip()
        )
    except ValueError:
        return False

    if len(tokens) < 2:
        return False

    executable = Path(tokens[0]).name.casefold()

    if not executable.startswith("python"):
        return False

    script_token = tokens[1]

    if (
        not script_token
        or script_token.startswith("-")
        or not script_token.casefold().endswith(".py")
    ):
        return False

    script = Path(script_token)

    if script.is_absolute():
        try:
            script.resolve().relative_to(
                workspace.resolve()
            )
        except (OSError, ValueError):
            return False

        candidate = script
    else:
        if ".." in script.parts:
            return False

        candidate = workspace / script

    try:
        candidate = candidate.resolve()
        candidate.relative_to(
            workspace.resolve()
        )
    except (OSError, ValueError):
        return False

    return candidate.is_file()


def _no_edit_action_problem(
    action: dict[str, Any],
    *,
    original_request: str = "",
    workspace: Path | None = None,
) -> str:
    kind = str(
        action.get("type")
        or ""
    ).casefold()

    if kind == "batch":
        children = action.get("actions")

        if not isinstance(children, list) or not children:
            return "no-edit request rejected invalid batch"

        for index, child in enumerate(children, 1):
            if not isinstance(child, dict):
                return (
                    "no-edit request rejected invalid "
                    f"batch item {index}"
                )

            problem = _no_edit_action_problem(
                child,
                original_request=original_request,
                workspace=workspace,
            )

            if problem:
                return f"batch item {index}: {problem}"

        return ""

    if kind == "read_file":
        return ""

    if kind in {
        "write_file",
        "append_file",
        "mkdir",
    }:
        return (
            "explicit no-edit request rejected "
            f"{kind}"
        )

    if kind in {
        "command",
        "run",
        "shell",
        "run_command",
        "bash",
        "run_interactive",
        "interactive",
        "play_demo",
    }:
        command = _command_text(action)

        if (
            not _no_edit_restricted_compound_inspection(command)
            and not _no_edit_shell_syntax_safe(command)
        ):
            return (
                "explicit no-edit request rejected "
                f"unsafe shell syntax: {command}"
            )

        if not _no_edit_find_arguments_safe(command):
            return (
                "explicit no-edit request rejected "
                f"unsafe find arguments: {command}"
            )

        if _no_edit_command_allowed(command):
            return ""

        # SOPHYANE_EXPLICIT_READ_ONLY_CLI_ADMISSION_V1
        if (
            _explicit_read_only_cli_requested(
                original_request
            )
            and _existing_python_cli_command(
                command,
                workspace,
            )
        ):
            return ""

        return (
            "explicit no-edit request rejected "
            f"command: {command}"
        )

    return ""


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
    if first in {
        "cd",
        "build",
        "create",
        "develop",
        "design",
        "implement",
        "write",
        "fix",
        "repair",
        "generate",
        "if",
        "for",
        "while",
        "until",
        "case",
        "select",
    }:
        return "model returned a shell recipe or natural-language instruction instead of source files"
    if first == "make" and not any((workspace / n).is_file() for n in ("Makefile", "makefile", "GNUmakefile")):
        return "make was requested before a Makefile exists"
    # Shell builtins are valid command heads even though they do not
    # necessarily have a filesystem executable discoverable by shutil.which().
    shell_builtins = {
        "command",
        "printf",
        "echo",
        "test",
        "true",
        "false",
        "pwd",
    }
    if first in shell_builtins:
        return ""

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


_DISCOVERY_NONTERMINAL_REQUEST_PATTERNS = (
    r"\b(?:build|create|implement|modify|repair|fix|refactor|update|write)\b",
    r"\b(?:run|execute)\s+(?:the\s+)?(?:tests?|pytest|regressions?|verification)\b",
    r"\bred\s*[-=]>\s*green\b",
)


def _explicit_terminal_output_satisfied(
    original_request: str,
    result: str,
) -> bool:
    """Require an explicit until-it-outputs condition before generic success."""
    request = str(original_request or "")
    match = re.search(
        r"""\buntil\s+it\s+outputs?\s+["'`]?([^\r\n"'`]+?)["'`]?
            (?=\s*(?:[.!]|\bif\b|$))""",
        request,
        flags=re.I | re.X,
    )
    if not match:
        return True

    expected = match.group(1).strip()
    if not expected:
        return True

    return expected in _command_stdout(result)


# SOPHYANE_READ_ONLY_EXECUTION_OBLIGATION_LEDGER_V1
def _read_only_execution_obligations(
    request: str,
) -> set[str]:
    """Return explicit execution obligations carried by a read-only request."""
    normalized = " ".join(
        str(request or "").casefold().split()
    )

    obligations: set[str] = set()

    # Negative instructions must not become execution obligations.
    # Remove negated spans only for positive test-intent detection;
    # preserve the original request for all other routing logic.
    positive_test_text = re.sub(
        r"\b(?:do not|don\x27t|never|must not|without)\b"
        r"[^.!?;\n]*",
        " ",
        normalized,
    )

    test_requested = (
        bool(
            re.search(
                r"\b(?:run|execute)\b[^.!?\n]*"
                r"\b(?:tests?|pytest|test suite)\b",
                positive_test_text,
            )
        )
        or "run all " in positive_test_text
        and " test" in positive_test_text
    )

    cli_requested = any(
        phrase in normalized
        for phrase in (
            "demonstrate the cli",
            "demo the cli",
            "run the cli",
            "execute the cli",
        )
    )

    if test_requested:
        obligations.add("tests")

    if cli_requested:
        obligations.add("cli")

    return obligations


def _read_only_obligations_satisfied_by_command(
    obligations: set[str],
    command: str,
) -> set[str]:
    """Return explicit obligations grounded by one successful command."""
    if not obligations:
        return set()

    try:
        tokens = shlex.split(
            str(command or "").strip()
        )
    except ValueError:
        return set()

    if not tokens:
        return set()

    lowered = [
        token.casefold()
        for token in tokens
    ]

    satisfied: set[str] = set()

    if "tests" in obligations:
        if (
            "pytest" in lowered
            or any(
                token.endswith("/pytest")
                for token in lowered
            )
            or (
                len(lowered) >= 3
                and Path(lowered[0]).name.startswith("python")
                and lowered[1] == "-m"
                and lowered[2] == "pytest"
            )
        ):
            satisfied.add("tests")

    if "cli" in obligations:
        if (
            len(tokens) >= 2
            and Path(tokens[0]).name.casefold().startswith("python")
            and not tokens[1].startswith("-")
            and tokens[1].casefold().endswith(".py")
        ):
            satisfied.add("cli")

    return satisfied


def _read_only_unsatisfied_obligations(
    required: set[str],
    satisfied: set[str],
) -> tuple[str, ...]:
    return tuple(
        sorted(required - satisfied)
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

    # Discovery words may appear inside a larger implementation request
    # (for example, "locate the existing regression test"). Such an
    # intermediate lookup must not terminate the whole adaptive task.
    if any(
        re.search(pattern, request_text)
        for pattern in _DISCOVERY_NONTERMINAL_REQUEST_PATTERNS
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
        "- Deterministic seed/demo rows appropriate to the user request.\n"
        "- Define REST-style JSON endpoints from the user's requested domain.\n"
        "- Preserve the entities, workflows and terminology in USER REQUEST.\n"
        "- Implement required create/read/update/delete behavior where requested.\n"
        "- Implement search/filter behavior where requested.\n"
        "- Validate required domain fields and values.\n"
        "- Do not invent domain entities or workflows absent from USER REQUEST.\n"
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
                "Build a responsive interface for the product described "
                "in the original user request, preserving its entities, "
                "workflows and terminology, with forms and controls required "
                "by that request plus hooks for static/app.js. "
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
                "Implement the interactions required by the original user "
                "request and the generated backend API. Preserve the user's "
                "domain entities and workflows. No localStorage replacement "
                "for backend state."
            ),
        ),
        (
            "static/style.css",
            (
                "Create static/style.css only. "
                "Return exactly one write_file JSON action. "
                "Provide a compact responsive layout for the existing "
                "frontend generated for the original user request. "
                "No external CSS frameworks."
            ),
        ),
        (
            "tests/test_app.py",
            (
                "Create tests/test_app.py only. "
                "Return exactly one write_file JSON action. "
                "Use pytest or unittest with only available Python "
                "dependencies. Exercise the backend behavior required by "
                "the original user request, including persistence, API "
                "validation and requested workflows against isolated "
                "temporary storage where practical."
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
        "Do not artificially split a file merely to keep the response small. "
        "When one file can be represented in the provider response, prefer one complete "
        "write_file action containing the coherent file rather than model-generated source chunks. "
        "Use append_file only when the task itself genuinely requires appending or when a prior "
        "verified action already established an intentional partial artifact. "
        "Create or extend only one project file per response. "
        "When all required files are ready, return exactly one run_command action. "
        "Use relative paths only and never use cd.\n"
        "EXECUTION CONTRACT:\n"
        + execution_prefix_for_repair(request)
        + "\n"
        + f"ORIGINAL TASK:\n{request}\n"
        + f"CURRENT FILES:\n{existing}\n"
        f"LAST RESPONSE OR RESULT:\n{result}\n"
        "Choose the single next unfinished action for ORIGINAL TASK only."
    )


def _read_only_continuation_prompt(request: str, evidence: str) -> str:
    return (
        "READ-ONLY REPOSITORY CONTINUATION. Return one JSON object only. "
        "Answer the ORIGINAL TASK using the grounded file observation below. "
        "Do not request or perform filesystem mutation, shell commands, or "
        "additional tools. Use exactly this final response contract: "
        '{"action":{"type":"respond","message":"user-facing answer"}}.\n'
        f"ORIGINAL TASK:\n{request}\n"
        f"GROUNDED READ EVIDENCE:\n{evidence}\n"
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
        r"""(?:
                file\s+(?:named|called)? |
                (?:make|create|write)
                (?:\s+(?:a|the))?
                (?:\s+file)?
            )
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


def _source_mutation_requires_followup(request: str) -> bool:
    """Return whether an authorized source write requires later execution."""
    normalized = " ".join(str(request or "").casefold().split())

    followup_markers = (
        "verify ",
        "test ",
        "pytest",
        "run ",
        "execute ",
        "compile",
        "build ",
        "benchmark",
        "then ",
        "after ",
    )

    return any(marker in normalized for marker in followup_markers)


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
        "verify ",
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

    requested_names = re.findall(
        r"""(?:
                file\s+(?:named|called)? |
                (?:make|create|write)
                (?:\s+(?:a|the))?
                (?:\s+file)?
            )
            \s*["'`]?([A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)["'`]?""",
        str(original_request or ""),
        flags=re.I | re.X,
    )
    if not requested_names:
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
    if target.name.casefold() not in {
        name.casefold() for name in requested_names
    }:
        return False

    return True



# SOPHYANE_FULL_STACK_SERVICE_FABRIC_CUTOVER_V1


from sophyane.rsi.supervisor import foreground as _rsi_foreground

# SOPHYANE_RSI_STRUCTURED_UNRESOLVED_V1
class _UnresolvedExecutionResult(str):
    """An unresolved runtime outcome carrying diagnostic evidence."""

    def __new__(cls, text, *, evidence):
        value = super().__new__(cls, str(text))
        value.execution_failed = True
        value.execution_failure_evidence = tuple(
            str(item)[:1000] for item in evidence[-16:]
        )
        # Preserve existing authoritative capability classification.
        for name in (
            "failure_classification",
            "capability_class",
            "failure_evidence",
        ):
            if hasattr(text, name):
                setattr(value, name, getattr(text, name))
        return value


@_rsi_foreground
class _AdaptiveFailureResult(str):
    """String-compatible unresolved result carrying authoritative failure evidence."""

    def __new__(
        cls,
        text: str,
        *,
        failure_classification: Any,
        capability_class: str,
        failure_evidence: dict[str, Any],
    ):
        value = super().__new__(cls, str(text))
        value.failure_classification = failure_classification
        value.capability_class = str(capability_class)
        value.failure_evidence = dict(failure_evidence)
        return value


def _authoritative_missing_reusable_capability_result(
    *,
    original_request: str,
    output: str,
) -> str:
    """Classify only an explicit reusable-capability gap with grounded evidence."""

    request = str(original_request or "")
    result = str(output or "")
    normalized_request = request.casefold()
    normalized_result = result.casefold()

    # Request intent alone is never enough.  Require the user to have
    # explicitly described a reusable capability that is absent.
    reusable_intent = (
        "reusable" in normalized_request
        and any(
            marker in normalized_request
            for marker in (
                "no parser",
                "no reusable implementation",
                "no implementation",
                "does not exist",
                "doesn't exist",
                "missing",
            )
        )
    )

    # Likewise, generic execution failure is never enough.  The adaptive
    # runtime must have grounded evidence that the requested executable
    # capability is actually absent.
    missing_execution_evidence = (
        "executable does not exist:" in normalized_result
    )

    if not reusable_intent or not missing_execution_evidence:
        return result

    # Extract the grounded executable identity from execution evidence.
    marker = "executable does not exist:"
    capability_name = ""

    for line in result.splitlines():
        lowered = line.casefold()
        if marker not in lowered:
            continue

        offset = lowered.index(marker) + len(marker)
        capability_name = line[offset:].strip().rstrip(".")
        if capability_name:
            break

    if not capability_name:
        return result

    from sophyane.failure_driven_capability import (
        FailureClassification,
    )

    return _AdaptiveFailureResult(
        result,
        failure_classification=(
            FailureClassification.MISSING_REUSABLE_CAPABILITY
        ),
        capability_class=f"executable.{capability_name}",
        failure_evidence={
            "kind": "missing_executable",
            "executable": capability_name,
            "execution_output": result,
            "request_declared_reusable_capability": True,
            "request_declared_missing_implementation": True,
        },
    )


from sophyane.rsi.supervisor import foreground as _admission_failure_foreground

@_admission_failure_foreground
def run_adaptive_loop(*, initial_text: str, original_request: str, ask: Callable[[str], Any],
                      workspace: Path | None = None, max_steps: int = 12,
                      progress: Callable[[str], None] | None = None,
                      operation: Any = None) -> str:
    from sophyane import execution_runtime as runtime
    # SOPHYANE_ADAPTIVE_WORKSPACE_AUTHORITY_V1
    #
    # Workspace selection belongs to the outer execution boundary. When the
    # caller supplies a workspace, it is already authoritative and must not be
    # reinterpreted from semantic request text. This is especially important
    # when higher layers append architecture/policy context whose vocabulary
    # may resemble a different project type.
    #
    # Legacy generated-project isolation remains available only when no
    # workspace was supplied by the caller.
    requested_workspace = (workspace or Path.cwd()).resolve()

    if workspace is not None:
        workspace = requested_workspace
    else:
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

    # The caller owns the execution budget. Higher-level planners may choose
    # a larger budget for complex software tasks, but an explicit max_steps
    # value must remain a hard upper bound inside this loop.
    max_steps = max(1, int(max_steps))

    # SOPHYANE_NIFDU_FULL_PRODUCT_CYCLE_V1
    #
    # In a NIFDU-backed Mode-4 session, NIFDU owns the complete browser
    # product lifecycle: initial build, visual capture, judge, repair and
    # acceptance.  Do not enter Sophyane's legacy one-shot/wrapper chain
    # afterward, because that would regenerate an already judged product.
    #
    # The first Mode-4 provider turn has already happened before this
    # adaptive loop is entered.  This branch therefore performs no
    # additional Sophyane provider-generation call.
    if (
        _browser_request(original_request)
        and os.environ.get(
            "SOPHYANE_SESSION_MODE",
            "",
        ).strip().lower()
        == "nifdu_llm"
    ):
        from sophyane import nifdu_product_supervisor

        progress(
            "Delegating browser product to NIFDU full "
            "build/capture/judge/repair cycle"
        )

        cycle = (
            nifdu_product_supervisor.run_nifdu_product_cycle(
                original_request
            )
        )

        score = cycle.get("score")
        iterations = cycle.get("iterations")
        summary = str(cycle.get("summary") or "").strip()

        if cycle.get("accepted") is not True:
            return (
                "NIFDU completed its browser-product quality "
                "cycle but the product was not accepted.\n\n"
                f"Score: {score}\n"
                f"Iterations: {iterations}\n"
                + (
                    f"Summary: {summary}\n"
                    if summary
                    else ""
                )
                + "The active Sophyane project was left unchanged."
            )

        source = Path(cycle["final_file"]).resolve()

        if not source.is_file():
            raise RuntimeError(
                "NIFDU accepted product is unavailable: "
                f"{source}"
            )

        html = source.read_text(encoding="utf-8")
        problem = _validate_html(
            html,
            original_request,
        )

        if problem:
            raise RuntimeError(
                "NIFDU accepted product failed Sophyane "
                f"structural verification: {problem}"
            )

        target = workspace / "index.html"
        temporary = workspace / ".index.html.nifdu.tmp"

        try:
            temporary.write_text(
                html,
                encoding="utf-8",
            )
            temporary.replace(target)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

        progress(
            f"Adopted accepted NIFDU product into {target} "
            f"({target.stat().st_size} bytes)"
        )

        ok, browser_result = runtime.execute_action(
            {"type": "open_browser"},
            workspace,
            progress,
        )

        if not ok:
            return (
                "NIFDU accepted the browser product, but "
                "final browser presentation failed.\n\n"
                f"Score: {score}\n"
                f"Iterations: {iterations}\n"
                f"Workspace: {workspace}\n"
                f"File: {target.name}\n\n"
                f"Execution evidence:\n{browser_result}"
            )

        return (
            "NIFDU completed and accepted the browser product.\n\n"
            f"Score: {score}\n"
            f"Iterations: {iterations}\n"
            + (
                f"Summary: {summary}\n"
                if summary
                else ""
            )
            + f"Workspace: {workspace}\n"
            f"File: {target.name}\n\n"
            "Execution evidence:\n"
            f"{browser_result}"
        )

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
    current_provider = getattr(initial_text, "provider_id", None)
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
    grounded_read_only_observation = ""
    repairs = 0
    successful_commands: set[str] = set()
    pending_no_edit_rejection = False
    pending_read_only_execution_failure = False

    read_only_required_obligations = (
        _read_only_execution_obligations(
            original_request
        )
    )
    read_only_satisfied_obligations: set[str] = set()

    # Operation is used later in this function regardless of whether the
    # caller supplied an authority classification. Import it unconditionally
    # so operation=None cannot leave the function-local name unbound.
    from sophyane.rsi.authority import Operation

    # MODE6_CLASSIFIED_READ_ONLY_ADAPTIVE_HANDOFF_V1
    # Preserve explicit no-edit parsing for legacy callers, while allowing
    # callers that already resolved repository authority to carry that
    # classification into the execution lifecycle.
    if operation is None:
        read_only_execution = _explicit_no_edit_request(original_request)
    else:
        read_only_execution = operation is Operation.READ_ONLY_OPERATION

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
            current_provider = getattr(response, "provider_id", None)
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

        if kind in {"respond", "message"} and not _files(workspace) and not read_only_execution:
            current = "Premature completion: no artifact exists."
            continue
        progress(f"Step {step}/{max_steps}: preparing {kind or 'action'}")

        if (
            operation is not None
            and str(getattr(operation, "value", operation)) == "source_mutation"
            and current_provider == "local_gguf"
        ):
            result = (
                "Execution deferred safely: local_gguf response lacks "
                "SOPHYANE_SOURCE_MUTATION authority."
            )
            evidence.append(result)
            return result + "\n\nExecution evidence:\n" + "\n".join(evidence)

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
                read_only_execution
                and grounded_read_only_observation
                and not _read_only_unsatisfied_obligations(
                    read_only_required_obligations,
                    read_only_satisfied_obligations,
                )
            ):
                # SOPHYANE_READ_ONLY_GROUNDED_DUPLICATE_COMPLETION_V1
                #
                # A successful inspection is sufficient evidence when the
                # original task is itself a read-only listing/inspection
                # request. A repeated command is provider continuation noise,
                # not evidence that another command or a mutation is needed.
                result = (
                    "Read-only repository inspection completed from grounded "
                    "evidence.\n\n"
                    + grounded_read_only_observation
                )
                evidence.append(f"Step {step}: {result}")
                progress(
                    "Read-only grounded evidence is sufficient; "
                    "finishing without another execution action"
                )
                return (
                    result
                    + "\n\nExecution evidence:\n"
                    + "\n".join(evidence)
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

        if read_only_execution:
            no_edit_problem = _no_edit_action_problem(
                action,
                original_request=original_request,
                workspace=workspace,
            )

            if no_edit_problem:
                result = (
                    "Execution stopped safely: "
                    + no_edit_problem
                    + "."
                )
                evidence.append(
                    f"Step {step}: {result}"
                )
                progress(result)
                pending_no_edit_rejection = True
                # Retry rejected commands through the selected intelligence.
                # Admission remains unchanged; writes never enter this retry.
                if (
                    kind in command_kinds
                    and repairs < 2
                    and step < max_steps
                ):
                    repairs += 1
                    response = ask(
                        "READ-ONLY ACTION RECOVERY. The runtime rejected the "
                        "previous command; it was not executed. Preserve all "
                        "no-edit restrictions. Do not repeat the rejected "
                        "command, create scripts, or request broader authority. "
                        "For file inspection or calculations over file contents, "
                        "choose read_file and use its actual returned contents "
                        "in a later final answer. If the exact requested command "
                        "has no admitted alternative, respond truthfully that "
                        "execution is blocked. Never invent results. Return "
                        "one executable JSON action, for example "
                        '{"action":{"type":"read_file","path":"relative/file"}}'
                        " or a respond action explaining the restriction.\n"
                        + "ORIGINAL TASK:\n" + original_request
                        + "\nACTUAL REJECTION:\n" + result
                    )
                    current_provider = getattr(response, "provider_id", None)
                    current = getattr(response, "text", str(response))
                    continue
                return _UnresolvedExecutionResult(
                    result
                    + "\n\nExecution evidence:\n"
                    + "\n".join(evidence),
                    evidence=evidence,
                )

        ok, result = _execute(runtime, action, workspace, progress)
        if read_only_execution and kind not in {"respond", "message"}:
            if ok:
                pending_read_only_execution_failure = False
            else:
                from sophyane.execution_runtime import VALID_ACTIONS
                from sophyane.runtime_interactive_patch import (
                    _FILESYSTEM_LATEST_ACTIONS_V13,
                )

                additional_runtime_actions = {
                    "analyse_log",
                    "analyze",
                    "verify_result",
                    "check_result",
                    "batch",
                }

                action_supported = kind in (
                    VALID_ACTIONS
                    | _FILESYSTEM_LATEST_ACTIONS_V13
                    | additional_runtime_actions
                )

                if action_supported:
                    pending_read_only_execution_failure = True
        if ok and kind not in {"respond", "message"}:
            pending_no_edit_rejection = False

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
                            current_source = candidate.read_text(
                                encoding="utf-8",
                                errors="replace",
                            )
                            max_repair_source_chars = 12000
                            if len(current_source) > max_repair_source_chars:
                                current_source = (
                                    current_source[:max_repair_source_chars]
                                    + "\n...[current target truncated]..."
                                )
                            result = (
                                "Python syntax validation failed immediately "
                                f"after writing {raw_path}.\n"
                                f"{error.msg}\n"
                                "Repair this exact file before creating "
                                "any additional project files.\n"
                                "CURRENT TARGET CONTENT:\n"
                                f"{current_source}"
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

        if (
            read_only_execution
            and ok
            and command_text
        ):
            read_only_satisfied_obligations.update(
                _read_only_obligations_satisfied_by_command(
                    read_only_required_obligations,
                    command_text,
                )
            )

        if (
            read_only_execution
            and ok
            and command_text
            and _is_read_only_inspection_command(command_text)
        ):
            grounded_read_only_observation = result
            # Remember the successful observation so a provider that repeats
            # it enters the grounded read-only completion path above instead
            # of executing or repairing the same command again.
            successful_commands.add(command_text)

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
            # The next phase is deterministic. Do not fall through to the
            # generic provider continuation at the bottom of this iteration.
            continue

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
            # Service Fabric now owns grounded runtime verification; no
            # additional model decision is required between these phases.
            continue

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

        # SOPHYANE_TARGETED_PATCH_COMPLETION_STOP_V1
        #
        # targeted_patch is itself a bounded, exact-one-match repository
        # mutation. execute_action() returns success only after the atomic
        # replacement has completed. Do not require another provider turn
        # merely to decide whether this already-completed edit is finished.
        if kind == "targeted_patch" and ok:
            return (
                "Targeted repository patch completed successfully."
                "\n\nWorkspace: "
                + str(workspace)
                + "\n\nExecution evidence:\n"
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
                and _explicit_terminal_output_satisfied(
                    original_request,
                    result,
                )
                and (
                    repairs == 0
                    or _command_references_workspace_artifact(
                        command_text,
                        workspace,
                    )
                )
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
                return _UnresolvedExecutionResult(
                    "Execution stopped safely after bounded repair attempts.\n\n"
                    + "\n".join(evidence),
                    evidence=evidence,
                )
            repairs += 1
            response = ask(_compact_repair_prompt(original_request, _files(workspace), result))
            current_provider = getattr(response, "provider_id", None)
            current = getattr(response, "text", str(response))
            continue
        if read_only_execution and ok and kind == "read_file":
            progress("Read-only observation completed; requesting final answer")
            try:
                response = ask(
                    _read_only_continuation_prompt(
                        original_request,
                        result,
                    )
                )
            except ProviderError:
                progress(
                    "Read-only continuation provider unavailable; "
                    "returning grounded observation"
                )
                return (
                    "Final response provider unavailable after successful "
                    "read-only repository observation.\n\n"
                    + result
                )
            current_provider = getattr(response, "provider_id", None)
            current = getattr(response, "text", str(response))

            # SOPHYANE_READONLY_FINAL_STEP_RESPONSE_V1
            # The final observation has already consumed the last
            # executable step. Accept only a completion message here.
            # Never execute another provider action beyond max_steps.
            if step >= max_steps:
                final_message = ""
                try:
                    import json
                    completion_payload = json.loads(current)
                    if isinstance(completion_payload, dict):
                        completion_action = completion_payload.get(
                            "action",
                            completion_payload,
                        )
                        if isinstance(completion_action, dict):
                            completion_kind = str(
                                completion_action.get("type")
                                or completion_action.get("action")
                                or ""
                            ).casefold()
                            if completion_kind in {"respond", "message"}:
                                final_message = str(
                                    completion_action.get("message") or ""
                                ).strip()
                except (TypeError, ValueError):
                    pass

                outstanding = _read_only_unsatisfied_obligations(
                    read_only_required_obligations,
                    read_only_satisfied_obligations,
                )

                if (
                    final_message
                    and not outstanding
                    and not pending_no_edit_rejection
                ):
                    return (
                        final_message
                        + "\n\nExecution evidence:\n"
                        + "\n".join(evidence)
                    )

                return _UnresolvedExecutionResult(
                    "Stopped after bounded execution loop. "
                    "The provider did not supply an admissible final "
                    "answer after the last read-only observation.\n\n"
                    + "\n".join(evidence),
                    evidence=evidence,
                )

            continue

        if (
            read_only_execution
            and command_text
            and ok
            and _is_read_only_inspection_command(command_text)
        ):
            progress("Read-only observation completed; requesting final answer")
            try:
                response = ask(
                    _read_only_continuation_prompt(
                        original_request,
                        result,
                    )
                )
            except ProviderError:
                progress(
                    "Read-only continuation provider unavailable; "
                    "returning grounded observation"
                )
                return (
                    "Final response provider unavailable after successful "
                    "read-only repository observation.\n\n"
                    + result
                )
            current_provider = getattr(response, "provider_id", None)
            current = getattr(response, "text", str(response))

            # SOPHYANE_READONLY_FINAL_STEP_RESPONSE_V1
            # The final observation has already consumed the last
            # executable step. Accept only a completion message here.
            # Never execute another provider action beyond max_steps.
            if step >= max_steps:
                final_message = ""
                try:
                    import json
                    completion_payload = json.loads(current)
                    if isinstance(completion_payload, dict):
                        completion_action = completion_payload.get(
                            "action",
                            completion_payload,
                        )
                        if isinstance(completion_action, dict):
                            completion_kind = str(
                                completion_action.get("type")
                                or completion_action.get("action")
                                or ""
                            ).casefold()
                            if completion_kind in {"respond", "message"}:
                                final_message = str(
                                    completion_action.get("message") or ""
                                ).strip()
                except (TypeError, ValueError):
                    pass

                outstanding = _read_only_unsatisfied_obligations(
                    read_only_required_obligations,
                    read_only_satisfied_obligations,
                )

                if (
                    final_message
                    and not outstanding
                    and not pending_no_edit_rejection
                ):
                    return (
                        final_message
                        + "\n\nExecution evidence:\n"
                        + "\n".join(evidence)
                    )

                return _UnresolvedExecutionResult(
                    "Stopped after bounded execution loop. "
                    "The provider did not supply an admissible final "
                    "answer after the last read-only observation.\n\n"
                    + "\n".join(evidence),
                    evidence=evidence,
                )

            continue
        if kind in {"respond", "message", "open_browser", "browser"}:
            unsatisfied_read_only_obligations = (
                _read_only_unsatisfied_obligations(
                    read_only_required_obligations,
                    read_only_satisfied_obligations,
                )
                if read_only_execution
                else ()
            )

            if (
                kind in {"respond", "message"}
                and unsatisfied_read_only_obligations
            ):
                pending = ", ".join(
                    unsatisfied_read_only_obligations
                )

                result = (
                    "Premature read-only completion rejected: "
                    "required execution obligations remain: "
                    + pending
                    + "."
                )

                evidence.append(
                    f"Step {step}: {result}"
                )
                progress(result)

                if step >= max_steps:
                    return _UnresolvedExecutionResult(
                        result
                        + "\n\nExecution evidence:\n"
                        + "\n".join(evidence),
                        evidence=evidence,
                    )

                response = ask(
                    "READ-ONLY EXECUTION OBLIGATIONS REMAIN. "
                    "Do not claim completion yet. "
                    "Return the next executable JSON action needed to "
                    "satisfy the original request. "
                    "Do not modify files and do not invent execution results. "
                    "Outstanding obligations: "
                    + pending
                    + ".\nORIGINAL TASK:\n"
                    + original_request
                    + "\nGROUNDED EXECUTION EVIDENCE:\n"
                    + "\n".join(evidence[-8:])
                )

                current_provider = getattr(
                    response,
                    "provider_id",
                    None,
                )
                current = getattr(
                    response,
                    "text",
                    str(response),
                )
                continue

            provider_final_message = (
                str(action.get("message") or "").strip()
                if kind in {"respond", "message"}
                else ""
            )

            if (
                read_only_execution
                and grounded_read_only_observation
                and not unsatisfied_read_only_obligations
                and not pending_no_edit_rejection
                and (
                    (
                        provider_final_message
                        or str(result or "").strip()
                    ).casefold() == "no implementation target was specified"
                    or (
                        any(
                            phrase in (
                                provider_final_message
                                or str(result or "")
                            ).casefold()
                            for phrase in (
                                "cannot implement anything",
                                "nothing to implement",
                                "what feature you want me to build",
                            )
                        )
                        and read_only_execution
                    )
                )
            ):
                return (
                    "Read-only repository inspection completed.\n\n"
                    "Grounded execution evidence:\n"
                    + grounded_read_only_observation
                )

            if (
                read_only_execution
                and pending_read_only_execution_failure
                and kind in {"respond", "message"}
            ):
                return _UnresolvedExecutionResult(
                    "Read-only execution remains incomplete after a failed "
                    "action; a provider completion message cannot establish "
                    "successful recovery.\n\nExecution evidence:\n"
                    + "\n".join(evidence),
                    evidence=evidence,
                )

            final_result = provider_final_message or result or "Completed."
            final = final_result + "\n\nExecution evidence:\n" + "\n".join(evidence)
            if pending_no_edit_rejection:
                return _UnresolvedExecutionResult(final, evidence=evidence)
            return final
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

        # SOPHYANE_SOURCE_MUTATION_CONDITIONAL_COMPLETION_V1
        #
        # A bare authorized source edit is complete after the successful
        # filesystem mutation. Compound requests that explicitly require
        # verification/execution must continue through the normal adaptive
        # lifecycle and may terminate only after that evidence succeeds.
        if (
            operation is Operation.SOPHYANE_SOURCE_MUTATION
            and ok
            and kind in {"write_file", "append_file"}
            and not _source_mutation_requires_followup(original_request)
        ):
            return (
                (result or "Completed.")
                + "\n\nExecution evidence:\n"
                + "\n".join(evidence)
            )

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
    unresolved = (
        "Stopped after bounded execution loop.\n\n"
        + "\n".join(evidence)
    )
    return _UnresolvedExecutionResult(
        _authoritative_missing_reusable_capability_result(
            original_request=original_request,
            output=unresolved,
        ),
        evidence=evidence,
    )


def install() -> None:
    from sophyane import execution_runtime
    execution_runtime.run_structured_loop = run_adaptive_loop


# Scoped no-edit constraints must not cancel explicitly authorized source repair.


# Correct scoped no-edit parsing while preserving global safety prohibitions.
