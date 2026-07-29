"""Observable Sophyane terminal interface with persistent project sessions."""
from __future__ import annotations
from sophyane.local_inspection import inspect_local_request

import json
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from sophyane.runtime_semantic_instruction import reset_semantic_request

from sophyane.execution_runtime import extract_plan, run_structured_loop, selected_action
from sophyane.version import __version__



# SOPHYANE_RUNTIME_BOOTSTRAP_V6
from .request_intercepts import (
    install_input_capture as _sophyane_install_input_capture,
    print_startup_ontology_once as _sophyane_print_startup_ontology_once,
)

_sophyane_install_input_capture()
_sophyane_print_startup_ontology_once()

def _clean_message(message: str) -> str:
    """Remove copied terminal prompt glyphs and harmless leading whitespace."""
    value = message.strip()
    while value.startswith(("❯", ">")):
        value = value[1:].lstrip()
    return value


def _simple_chat_reply(message: str) -> str | None:
    text = " ".join(message.strip().lower().split())
    if text in {"hi", "hello", "hey", "salam", "assalamualaikum", "assalamu alaikum"}:
        return "Hello! What would you like me to build, fix, research, or explain?"
    if text in {"thanks", "thank you", "thx"}:
        return "You’re welcome."
    if text in {"sophyane --version", "sophyane -v", "--version", "version"}:
        return f"Sophyane {__version__}"

    inspection_reply = inspect_local_request(message)
    if inspection_reply is not None:
        return inspection_reply
    if any(
        phrase in text
        for phrase in (
            "python version",
            "version of python",
            "which python",
            "python is installed",
            "installed python",
            "what version of python",
        )
    ):
        import sys
        return f"Python {sys.version.split()[0]} ({sys.executable})"

    # Lightweight PATH lookups: locate X / where is X / which X
    # Also handles "Which git is being used?" by taking the first token.
    for prefix in ("locate ", "where is ", "which "):
        if text.startswith(prefix):
            import shutil
            rest = text[len(prefix):].strip(" .?")
            name = rest.split()[0] if rest else ""
            name = name.strip(" .?!,")
            if name and name.replace("-", "").replace("_", "").isalnum():
                found = shutil.which(name)
                if found:
                    return f"{name}: {found}"
                return f"{name}: not found on PATH"
            break

    # Simple environment inspect
    # Identity / OS / shell / home
    if any(p in text for p in ("what shell", "which shell", "shell am i", "my shell")):
        import os
        return f"shell: {os.environ.get('SHELL', 'unknown')}"
    if text in {"who am i", "whoami", "who am i?", "whoami?"}:
        import os
        return f"user: {os.environ.get('USER') or os.environ.get('USERNAME') or 'unknown'}"
    if any(
        p in text
        for p in (
            "what operating system",
            "which os",
            "what os",
            "operating system is this",
            "what platform",
        )
    ):
        import platform
        return (
            f"OS: {platform.system()} {platform.release()} "
            f"({platform.platform()})"
        )
    if any(
        p in text
        for p in (
            "what architecture",
            "machine architecture",
            "cpu architecture",
            "what arch",
        )
    ):
        import platform
        return f"arch: {platform.machine()} ({platform.processor() or 'n/a'})"
    if any(
        p in text
        for p in (
            "home directory",
            "my home",
            "what is home",
            "where is home",
            "$home",
        )
    ):
        from pathlib import Path as P
        return f"home: {P.home()}"

    if text in {"show path", "show path.", "print path", "what is path", "what is my path"}:
        import os
        return f"PATH={os.environ.get('PATH', '')}"
    if any(
        p in text
        for p in (
            "current working directory",
            "working directory",
            "what is cwd",
            "show cwd",
            "where am i",
        )
    ):
        import os
        return f"cwd: {os.getcwd()}"

    return None



def _pure_media_request(message: str) -> bool:
    """
    Identify standalone visual-media creation requests.

    These requests should be answered through a media-capable conversational
    route rather than being treated as requests to build source-code
    artifacts.

    Explicit requests for applications, websites, code, HTML, SVG, canvas,
    scripts, generators, editors, APIs, or repositories remain software
    execution requests.
    """

    text = " ".join(str(message or "").lower().split())

    if not text:
        return False

    media_phrases = (
        "portrait",
        "illustration",
        "drawing",
        "sketch",
        "painting",
        "photograph",
        "photo",
        "picture",
        "image",
        "wallpaper",
        "poster",
        "logo",
        "avatar",
        "character art",
        "concept art",
        "digital art",
        "cover art",
        "album cover",
        "book cover",
        "flyer",
        "banner",
        "thumbnail",
        "sticker",
        "emoji",
        "meme",
        "infographic",
        "render",
        "watercolor",
        "oil painting",
        "cartoon",
        "anime",
    )

    implementation_phrases = (
        "website",
        "web page",
        "webpage",
        "web app",
        "application",
        "mobile app",
        "desktop app",
        "android app",
        "ios app",
        "html",
        "css",
        "javascript",
        "typescript",
        "python",
        "source code",
        "write code",
        "code that",
        "script",
        "program",
        "canvas",
        "svg",
        "three.js",
        "react",
        "vue",
        "flutter",
        "gui",
        "api",
        "endpoint",
        "repository",
        "project files",
        "browser game",
        "image generator",
        "portrait generator",
        "logo generator",
        "image editor",
        "photo editor",
        "drawing app",
        "editing tool",
        "command line tool",
        "cli tool",
    )

    has_media_subject = any(
        phrase in text
        for phrase in media_phrases
    )

    requests_implementation = any(
        phrase in text
        for phrase in implementation_phrases
    )

    return has_media_subject and not requests_implementation


def _execution_requested(message: str) -> bool:
    text = " ".join(message.lower().split())

    # Standalone media creation is not a software build request.
    if _pure_media_request(message):
        return False

    # Read-only local-environment inspection still requires execution.
    inspection_patterns = (
        r"^\s*locate\b",
        r"^\s*which\b",
        r"\bwhere\s+is\b",
        r"^\s*find\b",
        r"\bshow\s+(?:me\s+)?(?:the\s+)?path\b",
        r"\bexecutable\b",
        r"\bcommand\s+path\b",
    )

    inspection_targets = (
        "python",
        "python3",
        "pytest",
        "pip",
        "pip3",
        "git",
        "node",
        "npm",
        "java",
        "javac",
        "gcc",
        "g++",
        "clang",
        "cargo",
        "rustc",
        "go",
        "docker",
        "podman",
        "cmake",
        "make",
        "bash",
        "zsh",
        "fish",
        "shell",
        "executable",
        "command",
    )

    if (
        any(re.search(pattern, text) for pattern in inspection_patterns)
        and any(target in text for target in inspection_targets)
    ):
        return True

    advice = (
        "what should", "which project", "project should", "ideas", "recommend",
        "suggest", "explain", "tell me about", "what is", "how does", "can i",
        "temperature", "weather", "meaning of", "assess quality", "show code",
        "show json", "interesting information",
    )
    if any(marker in text for marker in advice):
        return False
    # Imperative build/edit verbs are execution even when preceded by a benchmark number.
    if re.match(
        r"^\s*(?:\d+[.)]\s+)?(?:build|make|create|design|develop|implement|write|fix|repair|patch|compile|run|test|deploy|open|continue|resume|convert|install|integrate|optimi[sz]e|audit|profile|monitor|simulate|demonstrate|execute|add|remove|change|update|improve|style|reopen|replace|modify)\b",
        text,
    ):
        return True
    actions = (
        r"\bbuild\b", r"\bmake\b", r"\bcreate\b", r"\bdesign\b", r"\bdevelop\b",
        r"\bimplement\b", r"\bwrite\b", r"\bfix\b", r"\brepair\b", r"\bpatch\b",
        r"\bcompile\b", r"\brun\b", r"\btest\b", r"\bre-test\b", r"\bdeploy\b",
        r"\bopen\b", r"\bshow\b.*\bdemo\b", r"\bcontinue\b", r"\bresume\b",
        r"\bconvert\b", r"\binstall\b", r"\bintegrate\b", r"\boptimi[sz]e\b",
        r"\baudit\b", r"\bprofile\b", r"\bmonitor\b", r"\bsimulate\b",
        r"\bdemonstrate\b", r"\bexecute\b", r"\bstart building\b",
        r"\badd\b", r"\bremove\b", r"\bchange\b", r"\bupdate\b", r"\bimprove\b",
        r"\bstyle\b", r"\breopen\b", r"\breplace\b", r"\bmodify\b",
    )
    return any(re.search(pattern, text) for pattern in actions)


def _explicit_new_benchmark(message: str) -> bool:
    """Numbered benchmark prompts are independent unless they say same project."""
    text = message.lower()
    return bool(re.match(r"^\s*\d+[.)]\s+", message)) and not any(
        marker in text for marker in ("same project", "continue", "existing project", "reuse")
    )


def _project_continuation(message: str, has_project: bool) -> bool:
    if not has_project or _explicit_new_benchmark(message):
        return False
    text = " ".join(message.lower().split())
    continuation_verbs = (
        "add ", "remove ", "change ", "update ", "improve ", "make the design",
        "style ", "reopen", "test it", "run it", "open it", "fix it", "modify ",
    )
    if text.startswith(continuation_verbs):
        return True
    markers = (
        "above", "previous", "same project", "this project", "this in", "it in browser",
        "open output", "open demo", "browser demo", "show it", "continue", "resume",
        "compile it", "giving error", "has error", "of this", "create icon", "add icon",
        "this software", "this app", "must survive", "full integration", "working prototype",
    )
    return any(marker in text for marker in markers)


def _render_nonexecuting_response(text: str) -> str:
    plan = extract_plan(text)
    if not plan:
        return text.strip()
    action = selected_action(plan)
    if isinstance(action, dict):
        kind = str(action.get("type") or action.get("action") or "").lower()
        if kind in {"respond", "message"}:
            return str(action.get("message") or action.get("content") or "").strip()
    for key in ("answer", "response", "message", "content"):
        value = plan.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(plan.get("objective") or "I could not produce a direct answer.").strip()




def _is_latest_file_inspection_request(message: str) -> bool:
    """Recognize requests asking for the most recently changed user file."""
    text = " ".join(str(message).lower().split())

    file_terms = (
        "file",
        "files",
    )
    latest_terms = (
        "last amendment",
        "latest amendment",
        "last amended",
        "latest amended",
        "last modified",
        "latest modified",
        "modified most recently",
        "changed most recently",
        "most recently changed",
        "most recently modified",
        "newest file",
        "latest file",
    )
    machine_terms = (
        "computer",
        "machine",
        "system",
        "home",
        "my files",
        "my computer",
    )

    has_file = any(term in text for term in file_terms)
    has_latest = any(term in text for term in latest_terms)
    has_machine = any(term in text for term in machine_terms)

    # The original wording contains "file", "computer", "last", and
    # "amendment", so recognize that natural-language form as well.
    amendment_form = (
        has_file
        and "amendment" in text
        and any(term in text for term in ("last", "latest", "recent"))
    )

    # Explicit latest/newest-file wording is sufficient by itself.
    # Machine terms improve confidence but are not mandatory.
    return has_file and (has_latest or amendment_form)


def _latest_user_file_report() -> str:
    """Return real evidence for the newest accessible regular user file."""
    import datetime
    import os

    root = Path.home().resolve()

    # Ignore volatile caches and Sophyane's own runtime state so merely asking
    # the question does not make a generated log become the newest user file.
    ignored_names = {
        ".cache",
        "__pycache__",
        ".npm",
        ".cargo",
        ".rustup",
        ".local",
        ".ollama",
        "node_modules",
        ".venv",
        "venv",
    }

    ignored_parts = {
        ".git",
        "__pycache__",
        "node_modules",
    }

    newest_path = None
    newest_stat = None
    scanned = 0
    denied = 0

    def onerror(_error):
        nonlocal denied
        denied += 1

    for current, directories, filenames in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=onerror,
    ):
        current_path = Path(current)

        directories[:] = [
            name
            for name in directories
            if name not in ignored_names
            and name not in ignored_parts
            and not name.endswith(
                (
                    ".bak",
                    ".backup",
                )
            )
        ]

        for filename in filenames:
            candidate = current_path / filename

            if any(part in ignored_parts for part in candidate.parts):
                continue

            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue

                stat = candidate.stat()
                scanned += 1
            except (OSError, PermissionError):
                denied += 1
                continue

            if newest_stat is None or stat.st_mtime_ns > newest_stat.st_mtime_ns:
                newest_path = candidate
                newest_stat = stat

    if newest_path is None or newest_stat is None:
        return (
            "No accessible regular file was found under "
            f"{root}.\n"
            f"Unreadable entries: {denied}"
        )

    modified = datetime.datetime.fromtimestamp(
        newest_stat.st_mtime
    ).astimezone()

    return (
        "Most recently modified accessible user file:\n"
        f"Path: {newest_path}\n"
        f"Modified: {modified.isoformat(timespec='seconds')}\n"
        f"Size: {newest_stat.st_size} bytes\n"
        f"Search root: {root}\n"
        f"Regular files inspected: {scanned}\n"
        f"Unreadable entries skipped: {denied}"
    )


def _sophyane_latest_file_request(message: str) -> bool:
    """Detect requests for the most recently modified file."""
    text = " ".join(str(message).lower().split())

    if "file" not in text:
        return False

    phrases = (
        "last amendment",
        "latest amendment",
        "last amended",
        "latest amended",
        "last modified",
        "latest modified",
        "modified most recently",
        "changed most recently",
        "most recently changed",
        "most recently modified",
        "newest file",
        "latest file",
    )

    amendment_wording = (
        "amendment" in text
        and any(word in text for word in ("last", "latest", "recent"))
    )

    return any(phrase in text for phrase in phrases) or amendment_wording


def _sophyane_latest_file_result() -> str:
    """Perform a deterministic read-only scan of the user's home."""
    import datetime
    import os

    root = Path.home().resolve()

    ignored_directories = {
        ".cache",
        ".git",
        ".npm",
        ".cargo",
        ".rustup",
        ".ollama",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
    }

    ignored_suffixes = (
        ".pyc",
        ".pyo",
        ".swp",
        ".tmp",
    )

    newest_path = None
    newest_stat = None
    inspected = 0
    skipped = 0

    def onerror(_error):
        nonlocal skipped
        skipped += 1

    for current, directories, filenames in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=onerror,
    ):
        directories[:] = [
            name
            for name in directories
            if name not in ignored_directories
        ]

        current_path = Path(current)

        for filename in filenames:
            if filename.endswith(ignored_suffixes):
                continue

            candidate = current_path / filename

            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue

                stat = candidate.stat()
                inspected += 1
            except (OSError, PermissionError):
                skipped += 1
                continue

            if newest_stat is None or stat.st_mtime_ns > newest_stat.st_mtime_ns:
                newest_path = candidate
                newest_stat = stat

    if newest_path is None or newest_stat is None:
        return (
            "No accessible regular file was found.\n"
            f"Search root: {root}\n"
            f"Unreadable entries skipped: {skipped}"
        )

    modified = datetime.datetime.fromtimestamp(
        newest_stat.st_mtime
    ).astimezone()

    return (
        "Most recently modified accessible user file:\n"
        f"Path: {newest_path}\n"
        f"Modified: {modified.isoformat(timespec='seconds')}\n"
        f"Size: {newest_stat.st_size} bytes\n"
        f"Search root: {root}\n"
        f"Files inspected: {inspected}\n"
        f"Unreadable entries skipped: {skipped}"
    )


class ObservableTUI:
    def __init__(self, *, config: dict[str, Any], ask: Any, handle_internal: Any) -> None:
        self.config = config
        self.ask = ask
        self.handle_internal = handle_internal
        self.active_workspace: Path | None = None
        self.active_request = ""
        self.project_requirements: list[str] = []
        self.history: list[tuple[str, str]] = []
        self.last_raw = ""
        self.last_prompt = ""
        self.last_elapsed = 0.0
        self.last_mode = "none"
        self.trace = False

    @property
    def small_local(self) -> bool:
        return str(self.config.get("provider") or "").lower() in {"local_gguf", "ollama"}

    def emit(self, role: str, text: str) -> None:
        print(f"\n{role}\n  " + text.replace("\n", "\n  ") + "\n", flush=True)

    def progress(self, text: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {text}", file=sys.stderr, flush=True)

    def call_provider(self, message: str, *, timeout: int = 60) -> Any:
        results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
        started = time.monotonic()
        self.last_prompt = message

        def worker() -> None:
            try:
                results.put(("ok", self.ask(message)))
            except Exception as error:  # noqa: BLE001
                results.put(("error", error))

        threading.Thread(target=worker, daemon=True).start()
        next_update = 5
        while True:
            try:
                status, value = results.get(timeout=1)
                self.last_elapsed = time.monotonic() - started
                if status == "error":
                    raise value
                return value
            except queue.Empty:
                elapsed = int(time.monotonic() - started)
                if elapsed >= next_update:
                    self.progress(f"Waiting for {self.config.get('provider')} response ({elapsed}s)")
                    next_update += 5
                if elapsed >= timeout:
                    raise TimeoutError(f"{self.config.get('provider')} did not respond within {timeout}s.")

    def _new_workspace(self) -> Path:
        workspace = Path.home() / ".sophyane" / "workspaces" / f"task-{int(time.time())}"
        workspace.mkdir(parents=True, exist_ok=True)
        self.active_workspace = workspace
        self.progress(f"Workspace: {workspace}")
        return workspace

    def _workspace_for(self, continuing: bool) -> Path:
        if continuing and self.active_workspace:
            self.progress(f"Reusing workspace: {self.active_workspace}")
            return self.active_workspace
        return self._new_workspace()

    def _context_prompt(self, message: str, *, continuing: bool) -> str:
        if self.small_local:
            if continuing and self.active_request:
                return f"Project: {self.active_request[:180]}\nChange: {message[:320]}"
            return message[:600]
        recent = self.history[-2:]
        if not recent:
            return message
        context = "\n".join(f"{role}: {content[:700]}" for role, content in recent)
        return f"Conversation context:\n{context}\n\nCurrent user message: {message}"

    def _inspect(self) -> str:
        plan = extract_plan(self.last_raw)
        lines = [
            f"Mode: {self.last_mode}",
            f"Provider/model: {self.config.get('provider')} / {self.config.get('model')}",
            f"Provider time: {self.last_elapsed:.2f}s",
            f"Active workspace: {self.active_workspace or 'none'}",
            f"Project requirements: {len(self.project_requirements)}",
            "", "Prompt sent to model:", self.last_prompt or "(none)",
            "", "Raw model response:", self.last_raw or "(none)",
        ]
        if plan:
            lines.extend(["", "Parsed JSON plan:", json.dumps(plan, indent=2, ensure_ascii=False)])
        if self.active_workspace and self.active_workspace.exists():
            files = [p for p in sorted(self.active_workspace.rglob("*")) if p.is_file()]
            lines.extend(["", "Workspace files:"])
            for path in files[:30]:
                lines.append(f"- {path.relative_to(self.active_workspace)} ({path.stat().st_size} bytes)")
        return "\n".join(lines)


    def read_prompt(self, prompt: str = "❯ ") -> str:
        """Read one interactive user prompt."""
        try:
            return input(prompt)
        except EOFError:
            raise
        except KeyboardInterrupt:
            raise

    def run(self) -> int:
        print(f"\n◆ Sophyane {__version__}")
        print(f"provider {self.config.get('provider')}  model {self.config.get('model')}")
        print("Projects keep one workspace across follow-up edits. /new starts a fresh project. /inspect shows raw plan and files. /quit exits.\n")
        while True:
            try:
                message = _clean_message(self.read_prompt("❯ "))
                reset_semantic_request(self)
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not message:
                continue
            normalized = " ".join(message.lower().split())
            if normalized in {"exit", "quit", "/quit", "/exit", "ecit"}:
                print("Goodbye.")
                return 0
            if normalized == "/new":
                self.active_workspace = None
                self.active_request = ""
                self.project_requirements.clear()
                self.history.clear()
                self.emit("system", "Project session cleared. The next build request will use a new workspace.")
                continue
            if normalized == "/inspect":
                self.emit("inspection", self._inspect())
                continue
            if normalized == "/trace":
                self.trace = not self.trace
                self.emit("system", f"Raw response trace {'enabled' if self.trace else 'disabled'}.")
                continue
            if message.startswith("/"):
                command = message[1:].split()[0]
                if command in {"setup", "status", "providers", "doctor"}:
                    text, self.config = self.handle_internal(command, self.config)
                    self.emit("system", text)
                    continue

            self.emit("You", message)
            quick = _simple_chat_reply(message)
            if quick is not None:
                self.emit("Sophyane", quick)
                continue

            has_project = bool(self.active_request and self.active_workspace)
            continuing = _project_continuation(message, has_project)
            executable = _execution_requested(message) or continuing
            if _explicit_new_benchmark(message):
                continuing = False
            context_message = self._context_prompt(message, continuing=continuing)

            if executable:
                self.last_mode = "execution"
                if continuing:
                    self.project_requirements.append(message)
                    request_for_model = (
                        f"Continue existing project. {context_message}\n"
                        "Return one compact JSON action using relative paths. Modify existing files; do not start over."
                    )
                else:
                    self.active_request = message
                    self.project_requirements = [message]
                    request_for_model = (
                        f"Execute: {context_message}\n"
                        "Return one compact JSON action or artifact. Use relative paths and verify real output."
                    )
            else:
                self.last_mode = "chat"
                request_for_model = f"Answer directly. No JSON or tool action.\n{context_message}"


# SOPHYANE_SEMANTIC_FILESYSTEM_V13
            if (
                executable
                and _is_latest_file_inspection_request(message)
            ):
                self.last_mode = "execution"
                self.active_request = message
                self.project_requirements = [message]

                request_for_model = f"""ORIGINAL USER REQUEST:
{message}

SLI SEMANTIC ONTOLOGY:
- domain: filesystem
- intent: inspect_file_metadata
- operation: latest_modified_regular_file
- capability: filesystem.latest_modified
- scope: active_workspace
- access_mode: read_only
- mutation_allowed: false
- network_required: false
- browser_required: false
- project_generation_required: false

AVAILABLE GROUNDED ACTION:
{{
  "type": "filesystem.latest_modified",
  "scope": "workspace",
  "include_hidden": false,
  "evidence_required": [
    "absolute_path",
    "relative_path",
    "mtime_ns",
    "modified_iso",
    "size_bytes"
  ]
}}

Interpret the ORIGINAL USER REQUEST semantically.

If it requests the latest, last, newest, most recently edited,
modified, changed, updated, or amended file, return exactly one
compact JSON action using `filesystem.latest_modified`.

Do not return run_command.
Do not run ls, find, pytest, unittest, compilation, browser actions,
or project generation for this read-only metadata query.
Do not invent a filename.
The runtime will execute the action deterministically and SLI will
validate the returned filesystem evidence.
"""

            self.progress("Thinking and planning" if executable else "Getting direct response")
            try:
                response = self.call_provider(request_for_model)
                text = getattr(response, "text", str(response))
                self.last_raw = text
            except Exception as error:  # noqa: BLE001
                self.emit("system", f"Error: {error}")
                continue

            if self.trace:
                self.emit("raw model response", text)

            if executable:
                self.progress("Execution request received; entering adaptive runtime")
                try:
                    workspace = self._workspace_for(continuing)
                    # SOPHYANE_CANONICAL_ACTIVE_REQUEST
                    # SOPHYANE_USE_CANONICAL_REQUEST_SNAPSHOT
                    # The semantic layer preserves live keyboard instructions
                    # in a dedicated snapshot because active_request can be
                    # reset or replaced during provider refinement.
                    snapshot = str(
                        getattr(
                            self,
                            "_sophyane_canonical_request_snapshot",
                            "",
                        )
                        or ""
                    ).strip()

                    active_request = str(
                        getattr(self, "active_request", "")
                        or ""
                    ).strip()

                    # Prevent a snapshot from a previous turn being reused.
                    if (
                        snapshot
                        and message.casefold() in snapshot.casefold()
                    ):
                        canonical_request = snapshot
                    elif (
                        active_request
                        and message.casefold()
                        in active_request.casefold()
                    ):
                        canonical_request = active_request
                    else:
                        canonical_request = message.strip()

                    # SOPHYANE_TRACE_CANONICAL_BEFORE_STRUCTURED_LOOP

                    text = run_structured_loop(
                        initial_text=text,
                        original_request=canonical_request,
                        ask=lambda prompt: self.call_provider(prompt),
                        workspace=workspace,
                        max_steps=8 if self.small_local else 16,
                        progress=self.progress,
                    )
                except Exception as error:  # noqa: BLE001
                    text = f"Execution loop failed safely: {error}"
            else:
                text = _render_nonexecuting_response(text)

            self.history.extend([("user", message[:300]), ("assistant", text[:500])])
            self.history = self.history[-4:]
            self.emit("Sophyane", text)


def run_observable_tui(*, config: dict[str, Any], verbose: bool = False) -> int:
    from sophyane.agent import SophyaneAgent
    from sophyane.logging_config import configure_logging
    from sophyane.main import create_provider, handle_internal_command
    from sophyane.memory import MemoryStore

    logger = configure_logging(verbose)
    agent = SophyaneAgent(create_provider(config), MemoryStore(), logger)
    return ObservableTUI(config=config, ask=agent.ask, handle_internal=handle_internal_command).run()


