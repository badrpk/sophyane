"""Observable Sophyane terminal interface with persistent project sessions."""
from __future__ import annotations
try:
    from sophyane.native.fast_path import try_fast_path as _sophyane_try_fast_path
except Exception:
    _sophyane_try_fast_path = None

from sophyane.local_inspection import inspect_local_request

import json
import queue
import re
import sys
import select
import hashlib
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

_PENDING_TERMINAL_SUBMISSIONS: list[str] = []

def _read_atomic_submission(prompt: str, read_first=None, editor_owned: bool = False) -> str:
    """Collect one submission; settle only after multiline paste evidence."""
    reader = read_first or input
    if _PENDING_TERMINAL_SUBMISSIONS:
        first = _PENDING_TERMINAL_SUBMISSIONS.pop(0)
    else:
        first = reader(prompt)
    lines = str(first).split("\n")
    multiline = len(lines) > 1
    deadline = time.monotonic()

    def drain(initial_ready: bool = False) -> bool:
        nonlocal multiline
        changed = False
        ready = initial_ready
        while ready or select.select([sys.stdin], [], [], 0)[0]:
            ready = False
            line = sys.stdin.readline()
            if line == "":
                break
            for physical in line.rstrip("\n").split("\n"):
                if physical.strip().casefold() in {"exit", "/exit", "quit", "/quit"}:
                    _PENDING_TERMINAL_SUBMISSIONS.append(physical.strip())
                    return changed
                lines.append(physical)
                changed = True
                multiline = True
        return changed

    try:
        observed = drain()
        if multiline or observed:
            # Termux PTYs can expose one paste in delayed kernel batches.
            # Once multiline evidence exists, reset a short settling window
            # whenever bytes arrive; ordinary single-line Enter does not wait.
            deadline = time.monotonic() + 0.150
            while time.monotonic() < deadline:
                remaining = max(0.0, deadline - time.monotonic())
                ready = select.select([sys.stdin], [], [], remaining)[0]
                if not ready:
                    continue
                if drain(initial_ready=True):
                    deadline = time.monotonic() + 0.150
    except (OSError, ValueError):
        pass
    objective = "\n".join(lines)
    print(f"INPUT_PHYSICAL_LINES={len(lines)}", flush=True)
    print("LOGICAL_OBJECTIVES=1", flush=True)
    print(f"OBJECTIVE_BYTES={len(objective.encode('utf-8'))}", flush=True)
    print("ORIGINAL_OBJECTIVE_HASH=" + hashlib.sha256(objective.encode("utf-8")).hexdigest(), flush=True)
    return objective


def _clean_message(message: str) -> str:
    """Remove copied terminal prompt glyphs and harmless leading whitespace."""
    value = message.strip()
    while value.startswith(("❯", ">")):
        value = value[1:].lstrip()
    return value


def _simple_chat_reply(message: str) -> str | None:
    # SOPHYANE_PRIVATE_CONNECTOR_MANAGEMENT_PREFLIGHT
    # Credential and account-management requests must never reach memory,
    # public internet acquisition, or an LLM.
    try:
        from sophyane.private_connector_management import (
            handle_private_management,
        )

        management_reply = handle_private_management(
            message
        )

        if management_reply is not None:
            return management_reply
    except Exception as error:
        import os as _management_os

        if _management_os.environ.get(
            "SOPHYANE_DEBUG_PRIVATE_MANAGEMENT",
            "",
        ) == "1":
            return (
                "Private connector management failed safely: "
                f"{type(error).__name__}: {error}"
            )

    # SOPHYANE_SEMANTIC_DOMAIN_ROUTER_V1
    # Decide whether this is personal/private before any public-memory or
    # internet-acquisition route can see the request.
    try:
        from sophyane.personal_fact_resolver import (
            try_personal_semantic_reply,
        )

        personal_semantic_reply = (
            try_personal_semantic_reply(
                message
            )
        )

        if personal_semantic_reply is not None:
            return personal_semantic_reply
    except Exception as error:
        import os as _semantic_router_os

        if _semantic_router_os.environ.get(
            "SOPHYANE_DEBUG_SEMANTIC_ROUTER",
            "",
        ) == "1":
            return (
                "Semantic domain router failed safely: "
                f"{type(error).__name__}: {error}"
            )

    # SOPHYANE_FLYWHEEL_TUI_V1
    # SOPHYANE_NATIVE_FAST_PATH_DISPATCH
    try:
        if _sophyane_try_fast_path is not None:
            _fp = _sophyane_try_fast_path(message)
            if _fp is not None:
                return _fp.text
    except Exception:
        pass

    # SOPHYANE_CROSS_MODE_TOPIC_SITE_PREFLIGHT
    # Informational website construction is a deterministic SLI capability.
    # Run it before any local/cloud provider in every session mode.
    try:
        import os as _topic_os
        from pathlib import Path as _TopicPath

        from sophyane.code_memory.topic_site_compose import (
            is_topic_site_request,
        )
        from sophyane.code_memory.sli_rich_site_compose import (
            compose_rich_topic_site,
        )

        if is_topic_site_request(message):
            _topic_workspace = (
                _TopicPath.cwd()
                / ".sophyane-workspace"
            )

            _topic_mode = _topic_os.environ.get(
                "SOPHYANE_SESSION_MODE",
                "",
            )

            if _topic_mode == "local_llm":
                from sophyane.local_site_refinement import (
                    compose_refined_local_topic_site,
                )

                return compose_refined_local_topic_site(
                    message,
                    _topic_workspace,
                )

            # SLI Graph must retain ownership of its full lifecycle:
            #
            #   classify -> topic composition -> validation -> promotion
            #
            # Calling compose_rich_topic_site() directly here used to
            # short-circuit run_sli_graph() and therefore bypass the
            # graph-level promotion/behavior-validation gate.
            if _topic_mode == "sli_graph":
                from sophyane.sli_graph import (
                    run_sli_graph,
                )

                return run_sli_graph(
                    message,
                    workspace=_topic_workspace,
                ).report

            return compose_rich_topic_site(
                message,
                _topic_workspace,
            )
    except Exception as _topic_site_error:
        import os as _topic_os

        if _topic_os.environ.get(
            "SOPHYANE_DEBUG_TOPIC_SITE",
        ) == "1":
            return (
                "Topic-site capability failed safely: "
                f"{type(_topic_site_error).__name__}: "
                f"{_topic_site_error}"
            )

    # SOPHYANE_TUI_UNIFIED_EXECUTION_KERNEL_V1
    # The interactive TUI has its own routing path and does not necessarily
    # call SophyaneAgent.ask(). Execute grounded local capabilities here before
    # SLI classification or any provider request.
    try:
        from sophyane.unified_execution_kernel import execute_text

        kernel_reply = execute_text(
            message,
            workspace=Path.cwd(),
        )
        if kernel_reply is not None:
            return kernel_reply
    except Exception as error:
        # Keep chat/provider fallback available, but expose diagnostics when
        # explicitly requested through the environment.
        import os

        if os.environ.get("SOPHYANE_DEBUG_KERNEL") == "1":
            return (
                "Unified execution-kernel error: "
                f"{type(error).__name__}: {error}"
            )

    # SOPHYANE_SLI_CHUNK_TIER
    import os as _sophyane_os

    _sli_only = (
        _sophyane_os.environ.get(
            "SOPHYANE_SLI_ONLY",
            "",
        ) == "1"
        or _sophyane_os.environ.get(
            "SOPHYANE_SESSION_MODE",
            "",
        ) == "sli_chunks"
    )

    if _sli_only:
        try:
            from pathlib import Path as _SliPath
            from sophyane.sli_chunk_router import (
                try_sli_chunks as _sli_route,
            )

            return _sli_route(
                message,
                workspace=(
                    _SliPath.cwd()
                    / ".sophyane-workspace"
                ),
            )
        except Exception as _sli_error:
            return (
                "SLI-only routing failure: "
                f"{_sli_error}"
            )

    # SOPHYANE_NATIVE_READONLY_DISPATCH
    # SOPHYANE_PERSISTENT_MEMORY_DISPATCH
    try:
        from sophyane.memory_architecture import try_memory_reply

        memory_reply = try_memory_reply(message)
        if memory_reply is not None:
            return memory_reply
    except Exception:
        # Memory failure must not break ordinary Sophyane routing.
        pass

    try:
        from sophyane.native_readonly_capabilities import (
            try_native_readonly_reply,
        )

        native_reply = try_native_readonly_reply(
            message,
            cwd=Path.cwd(),
        )
        if native_reply is not None:
            return native_reply
    except Exception:
        # Native capability failure must never break ordinary chat routing.
        pass

    try:
        from sophyane.capability_executors import try_connector_fast_path
        _cr = try_connector_fast_path(message)
        if _cr:
            return _cr
    except Exception:
        pass
    try:
        from sophyane.native_capability import try_any_native_reply
        _native_reply = try_any_native_reply(message)
        if _native_reply:
            return _native_reply
    except Exception:
        pass

    try:
        from sophyane.capability_gap_messages import capability_gap_reply
        gap = capability_gap_reply(message)
        if gap:
            return gap
    except Exception:
        pass
    text = " ".join(message.strip().lower().split())
    if text in {"hi", "hello", "hey", "salam", "assalamualaikum", "assalamu alaikum"}:
        return "Hello! What would you like me to build, fix, research, or explain?"
    if text in {"thanks", "thank you", "thx"}:
        return "You’re welcome."
    if text in {"sophyane --version", "sophyane -v", "--version", "version"}:
        return f"Sophyane {__version__}"

    # SOPHYANE_TUI_FILESYSTEM_V20_FASTPATH
    # Filesystem capabilities previously existed only around the adaptive
    # software loop. Chat-classified local filesystem questions bypassed that
    # loop and incorrectly reached the provider.
    try:
        from sophyane.runtime_filesystem_capabilities_v20 import (
            classify_request,
            execute_capability,
            format_result,
        )

        from sophyane.harness_task_policy import (
            filesystem_only_request,
        )

        filesystem_action = (
            classify_request(message)
            if filesystem_only_request(message)
            else None
        )

        if filesystem_action is not None:
            filesystem_ok, filesystem_raw = execute_capability(
                filesystem_action,
                Path.cwd(),
                message,
            )

            if filesystem_ok:
                return format_result(filesystem_raw)

            return (
                "Filesystem capability failed safely:\n"
                + filesystem_raw
            )
    except Exception as error:
        import os

        if os.environ.get("SOPHYANE_DEBUG_FILESYSTEM") == "1":
            return (
                "Filesystem capability error: "
                f"{type(error).__name__}: {error}"
            )

    # Allow selected Sophyane utility commands to be used naturally inside
    # the interactive CLI instead of hallucinating their output through an LLM.
    normalized_command = " ".join(message.strip().split())

    if normalized_command in {
        "sophyane-mission list",
        "sophyane mission list",
        "/mission list",
        "mission list",
    }:
        try:
            from sophyane.mission_engine import MissionStore

            store = MissionStore()
            with store.connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM missions
                    ORDER BY created_at DESC
                    LIMIT 20
                    """
                ).fetchall()

            missions = [dict(row) for row in rows]

            return json.dumps(
                {
                    "ok": True,
                    "count": len(missions),
                    "missions": missions,
                },
                indent=2,
                ensure_ascii=False,
            )
        except Exception as error:
            return (
                "Could not list missions: "
                f"{type(error).__name__}: {error}"
            )

    # SOPHYANE_CAPABILITY_EXECUTOR_FASTPATH_V1
    # Grounded deterministic capabilities run before provider planning.
    try:
        from sophyane.capability_executors import execute_deterministic_text

        executor_reply = execute_deterministic_text(
            message,
            workspace=Path.cwd(),
        )
        if executor_reply is not None:
            return executor_reply
    except Exception:
        # Never break the existing adaptive/provider fallback.
        pass

    # SOPHYANE_HARNESS_EXECUTION_HINT_V1
    # Do not return a conversational answer for repository tasks that require
    # filesystem changes, commands, tests, benchmarks, or iterative repair.
    try:
        from sophyane.harness_task_policy import is_execution_request

        if is_execution_request(message):
            return None
    except Exception:
        pass

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
    # Path-only home questions. Do NOT match list/count folder intents.
    home_path_phrases = (
        "what is my home directory",
        "what is home",
        "where is home",
        "where is my home",
        "show home directory",
        "show my home directory",
        "home directory path",
        "$home",
    )
    listing_markers = (
        "list ",
        "count ",
        "how many",
        "number of",
        "folders in",
        "directories in",
        "folder in",
        "directory in",
    )
    if any(p in text for p in home_path_phrases) and not any(
        m in text for m in listing_markers
    ):
        # Exact short forms only when not listing
        if text in {"home directory", "my home directory", "my home"} or any(
            p in text for p in home_path_phrases
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



def _email_option_digit_reply(message: str) -> str | None:
    """Clarify bare 1-4 and email-integration questions."""
    t = " ".join(str(message or "").strip().lower().split())
    if t in {"1", "2", "3", "4"}:
        return (
            "Pick an email path with a full sentence, for example:\n"
            "  1) Paste the email body here.\n"
            "  2) Read workspace file mail/last.eml and count words.\n"
            "  3) Scaffold a read-only IMAP script using SOPHYANE_IMAP_USER "
            "and SOPHYANE_IMAP_APP_PASSWORD (do not paste the app password).\n"
            "Bare digits are ambiguous without that request text."
        )
    if any(
        p in t
        for p in (
            "integrate email",
            "email with sophyane",
            "options how to integrate",
            "how to integrate email",
        )
    ):
        try:
            from sophyane.capability_gap_messages import EMAIL_INTEGRATION_GUIDE
            return EMAIL_INTEGRATION_GUIDE
        except Exception:
            return (
                "Email options: paste body; local .eml in workspace; "
                "or scaffold IMAP via env SOPHYANE_IMAP_USER / SOPHYANE_IMAP_APP_PASSWORD."
            )
    return None


def _execution_requested(message: str) -> bool:
    # SOPHYANE_MAKE_USE_OF_CHAT_GUARD_V1
    _guard_text = " ".join(
        str(message or "").casefold().split()
    )

    if "make use of" in _guard_text:
        imperative_prefixes = (
            "make a ",
            "make an ",
            "make the ",
            "make file ",
            "make website ",
            "make app ",
            "make game ",
        )

        if not _guard_text.startswith(imperative_prefixes):
            return False

    # Strong repository/build requests must be resolved before narrower
    # capability classifiers are allowed to veto execution.
    try:
        from sophyane.harness_task_policy import is_execution_request

        if is_execution_request(message):
            return True
    except Exception:
        pass

    # SOPHYANE_EXPLICIT_SOURCE_FILE_EDIT_EXECUTION_V1
    #
    # An imperative mutation request naming a concrete source/config file is
    # execution authority. Resolve it before generic capability/media
    # classifiers can misread words such as "image", "asset", "banner", or
    # "style" as a non-executing media/chat request.
    #
    # Keep this deliberately narrow:
    #   Update Footer.jsx ...     -> execute
    #   Edit app.tsx ...          -> execute
    #   Fix styles.css ...        -> execute
    #   What is Footer.jsx?       -> chat
    #   Show me an image ...      -> normal media routing
    _explicit_source_edit = re.match(
        (
            r"^\s*(?:please\s+)?"
            r"(?:edit|update|modify|fix|repair|patch|change|replace|"
            r"add|remove|improve|refactor|rewrite|style)\b"
        ),
        _guard_text,
    )

    _explicit_source_file = re.search(
        (
            r"(?<![A-Za-z0-9_.-])"
            r"[A-Za-z0-9_.-]+"
            r"\.(?:"
            r"py|pyi|js|jsx|mjs|cjs|ts|tsx|"
            r"html?|css|scss|sass|less|"
            r"json|jsonc|ya?ml|toml|ini|cfg|conf|"
            r"md|mdx|sql|sh|bash|zsh|fish|"
            r"c|cc|cpp|cxx|h|hh|hpp|hxx|"
            r"java|kt|kts|rs|go|rb|php|swift|vue|svelte"
            r")"
            r"(?=$|[^A-Za-z0-9_-])"
        ),
        _guard_text,
        re.IGNORECASE,
    )

    if (
        _explicit_source_edit
        and _explicit_source_file
    ):
        return True

    # explain-tool chat short-circuit: "explain pytest" is documentation, not a test run
    _t = " ".join(str(message or "").lower().split())
    if _t.startswith(("explain ", "what is ", "what are ", "how does ", "how do ")):
        if not any(v in _t for v in (" run ", " execute ", " install ", " fix ", " write ", " create ")):
            # bare "explain X" / "what is X" stay chat even if X is a test tool name
            return False
    try:
        from sophyane.collaborative_workers import plan_workers
        from sophyane.native_capability import try_native_status_reply
        if try_native_status_reply(message):
            return False
        plan = plan_workers(message)
        if (plan.use_neuron or plan.use_nifdu) and not plan.use_llm:
            return False  # TUI should take chat/simple path → combined reply
    except Exception:
        pass
    try:
        from sophyane.capability_registry import is_execution_capability
        decision = is_execution_capability(message)
        if decision is False:
            return False
        if decision is True:
            return True
    except Exception:
        pass
    # Deterministic filesystem capabilities always execute (never chat).
    try:
        from sophyane.runtime_filesystem_capabilities_v20 import classify_request
        if classify_request(message):
            return True
    except Exception:
        pass
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
    has_file = any(term in text for term in file_terms)
    has_latest = any(term in text for term in latest_terms)

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
    def __init__(
        self,
        *,
        config: dict[str, Any],
        ask: Any,
        handle_internal: Any,
        dispatch_user_request: Any | None = None,
    ) -> None:
        self.config = config
        # `ask` is deliberately the low-level provider callback used by
        # call_provider() and structured execution refinement.
        self.ask = ask
        # Auto/Race mode instead owns the original user request at the
        # terminal boundary.  It must never be installed as `ask`.
        self.dispatch_user_request = dispatch_user_request
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

        # SOPHYANE_NATIVE_CHOICE_STATE_INIT
        # Preserve interactive selections from deterministic native replies.
        self._native_choice_context: str = ""
        self._native_choice_selected: str = ""

    @property
    def small_local(self) -> bool:
        return str(self.config.get("provider") or "").lower() in {"local_gguf"}

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
        """Build context without contaminating unrelated new requests."""
        clean_message = str(message or "").strip()

        if self.small_local:
            if continuing and self.active_request:
                return (
                    f"Project: {self.active_request[:180]}\n"
                    f"Change: {clean_message[:320]}"
                )
            return clean_message[:600]

        # Project continuations explicitly require prior project context.
        if continuing and self.active_request:
            return (
                f"Existing project request: {self.active_request[:700]}\n\n"
                f"Current requested change: {clean_message}"
            )

        # Only include chat history when the current message clearly refers
        # to something from the previous turn. Independent questions must
        # remain isolated, especially because a small local fallback may
        # overweight stale assistant/tool content.
        lowered = clean_message.casefold()
        followup_prefixes = (
            "and ",
            "also ",
            "but ",
            "so ",
            "then ",
            "continue",
            "next",
            "why ",
            "how about",
            "what about",
            "tell me more",
            "explain more",
            "explain it",
            "do it",
            "fix it",
            "change it",
            "update it",
            "that ",
            "this ",
        )
        followup_exact = {
            "yes",
            "no",
            "ok",
            "okay",
            "why",
            "how",
            "continue",
            "next",
            "more",
            "do that",
            "do it",
            "same",
        }
        reference_words = (
            " it ",
            " that ",
            " this ",
            " they ",
            " them ",
            " those ",
            " previous ",
            " above ",
            " earlier ",
            " same ",
        )

        padded = f" {lowered} "
        is_followup = (
            lowered in followup_exact
            or lowered.startswith(followup_prefixes)
            or any(word in padded for word in reference_words)
        )

        if not is_followup:
            return clean_message

        recent = self.history[-2:]
        if not recent:
            return clean_message

        context = "\n".join(
            f"{role}: {content[:700]}"
            for role, content in recent
        )
        return (
            f"Conversation context:\n{context}\n\n"
            f"Current user message: {clean_message}"
        )

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
            return _read_atomic_submission(prompt)
        except EOFError:
            raise
        except KeyboardInterrupt:
            raise

    def run(self) -> int:
        while True:
            try:
                message = _clean_message(self.read_prompt("❯ "))
                reset_semantic_request(self)
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            # SOPHYANE_EARLY_CONVERSATIONAL_INTENT_AUTHORITY_V8_1
            # Resolve retained graph and systematic capability intent
            # before quick-chat or any direct provider surface.
            from sophyane.conversational_graph_session import (
                try_conversational_graph_followup,
            )

            _sophyane_early_graph = (
                try_conversational_graph_followup(
                    self,
                    message,
                )
            )

            if _sophyane_early_graph is not None:
                self.last_raw = _sophyane_early_graph
                self.history.extend(
                    [
                        (
                            "user",
                            message[:300],
                        ),
                        (
                            "assistant",
                            _sophyane_early_graph[:500],
                        ),
                    ]
                )
                self.history = self.history[-4:]
                self.emit(
                    "Sophyane",
                    _sophyane_early_graph,
                )
                continue

            from sophyane.capability_design import (
                prepare_capability_design_request,
            )

            _sophyane_early_design_prompt = (
                prepare_capability_design_request(
                    request=message,
                    conversational_context=message,
                )
            )

            _sophyane_provider_message = (
                _sophyane_early_design_prompt
                if _sophyane_early_design_prompt is not None
                else message
            )
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

            # SOPHYANE_PRE_DISPATCH_OBJECTIVE_GATE
            from sophyane.objective_preflight import (
                preflight_original_request,
            )

            preflight_reply = preflight_original_request(
                message
            )

            if preflight_reply is not None:
                print()
                print("Sophyane")

                for preflight_line in str(
                    preflight_reply
                ).splitlines():
                    print(
                        "  " + preflight_line
                    )

                print()
                self.active_request = ""
                continue



            # SOPHYANE_NATIVE_CHOICE_STATE_DISPATCH
            normalized_choice = " ".join(message.casefold().split())

            if (
                getattr(self, "_native_choice_context", "") == "saas_agents"
                and normalized_choice in {"1", "2", "3", "4", "5", "6", "7"}
            ):
                choices = {
                    "1": (
                        "SophyaneAgent",
                        "Use it as the public customer-facing API/chat agent."
                    ),
                    "2": (
                        "Multi-agent supervisor",
                        "Use it to route complex SaaS requests, split work among "
                        "specialists, enforce worker limits, coordinate retries "
                        "and merge task-graph execution."
                    ),
                    "3": (
                        "Specialist workers",
                        "Use them for domain-specific services such as coding, "
                        "support, analysis, automation and document processing."
                    ),
                    "4": (
                        "Executor worker",
                        "Use it for validated tool calls and deterministic actions."
                    ),
                    "5": (
                        "Reviewer worker",
                        "Use it to validate and merge outputs before delivery."
                    ),
                    "6": (
                        "Native workers",
                        "Use them for fast, low-cost deterministic capabilities."
                    ),
                    "7": (
                        "LLM provider worker",
                        "Use it only when generative reasoning is required."
                    ),
                }

                name, purpose = choices[normalized_choice]
                self._native_choice_selected = name

                self.emit(
                    "Sophyane",
                    f"Selected: {name}\n{purpose}\n\n"
                    "Type `proceed` to generate the implementation plan, "
                    "or choose another number.",
                )
                continue

            if normalized_choice in {"proceed", "continue", "go ahead"}:
                selected = str(
                    getattr(self, "_native_choice_selected", "") or ""
                ).strip()

                if selected == "Multi-agent supervisor":
                    self._native_choice_context = ""
                    self._native_choice_selected = ""

                    self.emit(
                        "Sophyane",
                        "Proceeding with the Multi-agent supervisor for SaaS.\n\n"
                        "Implementation target:\n"
                        "Customer/API → SophyaneAgent → Supervisor → "
                        "Specialist workers → Reviewer → Response\n\n"
                        "The supervisor should provide tenant isolation, "
                        "authentication, quotas, task routing, bounded retries, "
                        "worker concurrency limits, audit events, usage accounting "
                        "and failure recovery. This is now the authoritative SaaS "
                        "architecture selection.",
                    )
                    continue

                if selected:
                    self.emit(
                        "Sophyane",
                        f"Proceeding with {selected} as the selected SaaS component.",
                    )
                    self._native_choice_context = ""
                    self._native_choice_selected = ""
                    continue

            # SOPHYANE_AUTO_TOP_LEVEL_DISPATCH_V1
            #
            # Auto mode owns the ORIGINAL user request here.  Do not first
            # rewrite it into "Answer directly", "Execute:", semantic prompts,
            # or structured-loop repair prompts.  Those are low-level provider
            # concerns and would recursively launch another adaptive race.
            # SOPHYANE_NIFDU_TUI_GUARDED_EXECUTION_V1
            #
            # Explicit Option 4 -> 2 sessions use NIFDU/ChatGPT
            # for intelligence only. Filesystem mutation remains
            # inside Sophyane's validated executor.
            import os as _nifdu_os

            if (
                _nifdu_os.environ.get(
                    "SOPHYANE_SESSION_MODE",
                    "",
                ).strip().lower()
                == "nifdu_llm"
            ):
                from pathlib import Path as _NifduPath

                from sophyane.nifdu_guarded_execution import (
                    NifduExecutionError,
                    execute_nifdu_file_request,
                    grounded_nifdu_python_file_read,
                    ungrounded_nifdu_browser_reference,
                    grounded_nifdu_named_file_discovery,
                    grounded_nifdu_file_followup,
                )

                # SOPHYANE_NIFDU_GROUNDED_FILE_STATE_V1
                if not hasattr(
                    self,
                    "_nifdu_grounded_file",
                ):
                    self._nifdu_grounded_file = None

                # SOPHYANE_NIFDU_NAMED_FILE_DISCOVERY_DISPATCH_V1
                _nifdu_discovery = grounded_nifdu_named_file_discovery(
                    message
                )

                if _nifdu_discovery is not None:
                    _paths = _nifdu_discovery["paths"]

                    self._nifdu_grounded_file = (
                        _paths[0]
                        if len(_paths) == 1
                        else None
                    )

                    self.last_raw = _nifdu_discovery["message"]

                    self.history.extend(
                        [
                            (
                                "user",
                                message[:300],
                            ),
                            (
                                "assistant",
                                self.last_raw[:500],
                            ),
                        ]
                    )

                    self.history = self.history[-4:]

                    self.emit(
                        "Sophyane",
                        self.last_raw,
                    )

                    continue

                # SOPHYANE_NIFDU_GROUNDED_FILE_FOLLOWUP_DISPATCH_V1
                _nifdu_followup = grounded_nifdu_file_followup(
                    message,
                    active_file=self._nifdu_grounded_file,
                )

                if _nifdu_followup is not None:
                    self.last_raw = _nifdu_followup

                    self.history.extend(
                        [
                            (
                                "user",
                                message[:300],
                            ),
                            (
                                "assistant",
                                _nifdu_followup[:500],
                            ),
                        ]
                    )

                    self.history = self.history[-4:]

                    self.emit(
                        "Sophyane",
                        _nifdu_followup,
                    )

                    continue

                # SOPHYANE_NIFDU_TUI_LOCAL_GROUNDING_DISPATCH_V1
                #
                # Explicit local file reads are resolved from the active
                # workspace before NIFDU is allowed to answer. This prevents
                # browser-LLM prose from being mistaken for filesystem state.
                #
                # SOPHYANE_NIFDU_EXPLICIT_FILE_READ_GROUNDING_V1
                _nifdu_grounded_read = grounded_nifdu_python_file_read(
                    message,
                    workspace=_NifduPath.cwd().resolve(),
                )

                if _nifdu_grounded_read is not None:
                    from sophyane.nifdu_guarded_execution import (
                        requested_python_read_filename,
                    )

                    _read_name = requested_python_read_filename(
                        message
                    )

                    if _read_name is not None:
                        _read_path = (
                            _NifduPath.cwd().resolve()
                            / _read_name
                        )

                        self._nifdu_grounded_file = (
                            _read_path.resolve()
                            if _read_path.is_file()
                            else None
                        )

                    self.last_raw = _nifdu_grounded_read

                    self.history.extend(
                        [
                            (
                                "user",
                                message[:300],
                            ),
                            (
                                "assistant",
                                _nifdu_grounded_read[:500],
                            ),
                        ]
                    )

                    self.history = self.history[-4:]

                    self.emit(
                        "Sophyane",
                        _nifdu_grounded_read,
                    )

                    continue

                # SOPHYANE_NIFDU_UNGROUNDED_BROWSER_REFERENCE_V1
                #
                # Never reinterpret model prose such as "this code" as a real
                # executable artifact. An explicit filename is required.
                _nifdu_ungrounded_browser = (
                    ungrounded_nifdu_browser_reference(
                        message,
                        workspace=_NifduPath.cwd().resolve(),
                    )
                )

                if _nifdu_ungrounded_browser is not None:
                    self.last_raw = _nifdu_ungrounded_browser

                    self.history.extend(
                        [
                            (
                                "user",
                                message[:300],
                            ),
                            (
                                "assistant",
                                _nifdu_ungrounded_browser[:500],
                            ),
                        ]
                    )

                    self.history = self.history[-4:]

                    self.emit(
                        "Sophyane",
                        _nifdu_ungrounded_browser,
                    )

                    continue

                try:
                    _nifdu_target = execute_nifdu_file_request(
                        message,
                        workspace=_NifduPath.cwd().resolve(),
                    )
                except NifduExecutionError as error:
                    self.emit(
                        "system",
                        "NIFDU proposal rejected by Sophyane's "
                        f"guarded executor: {error}",
                    )
                    continue

                if _nifdu_target is not None:
                    _nifdu_content = _nifdu_target.read_text(
                        encoding="utf-8",
                    )

                    self.last_raw = (
                        "Created guarded NIFDU file: "
                        + str(_nifdu_target)
                    )

                    self.history.extend(
                        [
                            (
                                "user",
                                message[:300],
                            ),
                            (
                                "assistant",
                                self.last_raw[:500],
                            ),
                        ]
                    )

                    self.history = self.history[-4:]

                    self.emit(
                        "Sophyane",
                        (
                            "Created "
                            + _nifdu_target.name
                            + " through the guarded NIFDU "
                            "execution path.\n\n"
                            + "Path: "
                            + str(_nifdu_target)
                            + "\n"
                            + "Contents:\n"
                            + _nifdu_content.rstrip("\n")
                        ),
                    )

                    continue

            if self.dispatch_user_request is not None:
                try:
                    response = self.dispatch_user_request(_sophyane_provider_message)
                    text = getattr(response, "text", str(response))
                    self.last_raw = text

                    # SOPHYANE_EARLY_DIRECT_RESPONSE_RETENTION_V8_1
                    from sophyane.conversational_graph_session import (
                        remember_grounded_process_context,
                    )
                    remember_grounded_process_context(
                        self,
                        self.last_raw,
                    )
                except Exception as error:  # noqa: BLE001
                    self.emit(
                        "system",
                        f"Adaptive dispatch error: {error}",
                    )
                    continue

                self.history.extend([
                    ("user", message[:300]),
                    ("assistant", text[:500]),
                ])
                self.history = self.history[-4:]
                self.emit("Sophyane", text)
                continue

            # SOPHYANE_CAPABILITY_DESIGN_BEFORE_QUICK_REPLY_V8_1
            quick = (
                None
                if _sophyane_early_design_prompt
                is not None
                else _simple_chat_reply(
                    message
                )
            )
            if quick is not None:
                # SOPHYANE_NATIVE_CHOICE_STATE_STORE
                if (
                    "Recommended Sophyane architecture for SaaS services:"
                    in quick
                ):
                    self._native_choice_context = "saas_agents"
                    self._native_choice_selected = ""

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
                # SOPHYANE_SYSTEMATIC_CAPABILITY_DESIGN_DISPATCH_V6
                from sophyane.capability_design import (
                    prepare_capability_design_request,
                )
                _sophyane_capability_design_prompt = (
                    prepare_capability_design_request(
                        request=message,
                        conversational_context=context_message,
                    )
                )
                if _sophyane_capability_design_prompt is not None:
                    request_for_model = (
                        _sophyane_capability_design_prompt
                    )
                else:
                    request_for_model = (
                        f"Answer directly. No JSON or tool action.\n{context_message}"
                    )


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

            # SOPHYANE_CONVERSATIONAL_GRAPH_LIVE_DISPATCH_V5
            from sophyane.conversational_graph_session import (
                try_conversational_graph_followup,
            )
            _sophyane_graph_followup = (
                try_conversational_graph_followup(
                    self,
                    message,
                )
            )
            if _sophyane_graph_followup is not None:
                self.last_raw = _sophyane_graph_followup
                self.history.extend([
                    ("user", message[:300]),
                    ("assistant", _sophyane_graph_followup[:500]),
                ])
                self.history = self.history[-4:]
                self.emit(
                    "Sophyane",
                    _sophyane_graph_followup,
                )
                continue
            self.progress("Thinking and planning" if executable else "Getting direct response")
            try:
                response = self.call_provider(request_for_model)
                text = getattr(response, "text", str(response))
                self.last_raw = text
                # SOPHYANE_CONVERSATIONAL_GRAPH_RESPONSE_RETENTION_V5
                from sophyane.conversational_graph_session import (
                    remember_grounded_process_context,
                )
                remember_grounded_process_context(
                    self,
                    self.last_raw,
                )
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


def _create_provider_for_observable_tui(
    config: dict[str, Any],
) -> Any:
    """Construct a provider except for an authoritative SLI-only refusal.

    The provider factory is imported here deliberately. Historically
    run_observable_tui() could resolve create_provider through its own
    local scope; this module-level helper must own that dependency.

    Only the explicit SLI-only refusal is translated to ``None``.
    Every other construction failure remains fail-closed.
    """
    from sophyane.main import (
        create_provider as authoritative_create_provider,
    )

    try:
        return authoritative_create_provider(
            config
        )

    except RuntimeError as error:
        message = str(
            error
        )

        if (
            "SLI-only session forbids LLM provider construction"
            not in message
        ):
            raise

        return None


def run_observable_tui(*, config: dict[str, Any], verbose: bool = False) -> int:
    from pathlib import Path

    from sophyane.agent import AgentResponse, SophyaneAgent
    from sophyane.logging_config import configure_logging
    from sophyane.main import create_provider, handle_internal_command
    from sophyane.memory import MemoryStore
    from sophyane.v13_cli import (
        _execution_session_mode,
        _run_adaptive_race_request,
    )

    logger = configure_logging(verbose)
    session_mode = _execution_session_mode()

    dispatch_user_request = None

    # SOPHYANE_OBSERVABLE_TUI_AUTO_TOP_LEVEL_DISPATCH_V2
    #
    # Auto owns the original user request.  Its SLI/local/cloud race workers
    # construct their own isolated capabilities/providers, so constructing a
    # conventional fallback provider here would be redundant and could
    # reintroduce startup/fallback failures before the race even begins.
    # SOPHYANE_GENERAL_VISUAL_DISPATCH_CHAIN_V3
    #
    # Deterministic grounded visual intent is handled before the existing
    # mode/provider dispatch chain. The original chain is preserved intact
    # under `else`, so unhandled requests retain identical routing.
    try:
        from pathlib import Path as _SophyaneVisualPath
        from sophyane.visual_dispatch import (
            try_general_visual_dispatch as _try_general_visual_dispatch,
        )

        _sophyane_visual_result = _try_general_visual_dispatch(
            message,
            workspace=_SophyaneVisualPath.cwd(),
        )

    except Exception:
        _sophyane_visual_result = None


    if _sophyane_visual_result is not None:
        print(
            _sophyane_visual_result[
                "response"
            ]
        )

    else:
        # SOPHYANE_GENERAL_DOCUMENT_IMPORT_CHAIN_V4
        # Explicit visual intent already had first refusal. Plain local
        # document import now gets one provider-independent opportunity
        # before the unchanged mode/provider routing chain.
        try:
            from sophyane.document_dispatch import (
                try_general_document_dispatch as _try_general_document_dispatch,
            )

            _sophyane_document_result = _try_general_document_dispatch(
                message,
                workspace=_SophyaneVisualPath.cwd(),
            )

        except Exception:
            _sophyane_document_result = None

        if _sophyane_document_result is not None:
            print(
                _sophyane_document_result[
                    "response"
                ]
            )

        else:
            # SOPHYANE_SESSION_DOCUMENT_NORMAL_PIPELINE_V1
            # Follow-up reasoning may use the most recently imported grounded
            # document, while the existing mode/provider still owns reasoning.
            try:
                from sophyane.document_session_context import (
                    augment_request_with_current_document as _augment_request_with_current_document,
                )

                message, _sophyane_session_document = (
                    _augment_request_with_current_document(
                        message,
                        require_reference=True,
                    )
                )

            except Exception:
                pass

            if session_mode == "race":
                workspace = Path.cwd().resolve()
                tui_holder = {}

                def ask(message: str) -> AgentResponse:
                    raise RuntimeError(
                        "Auto mode low-level provider callback was invoked. "
                        "Original user requests must use dispatch_user_request()."
                    )

                def dispatch_user_request(message: str) -> AgentResponse:
                    # SOPHYANE_AUTO_RACE_LEARNING_HANDOFF_V1
                    #
                    # Auto mode bypasses run_structured_loop and therefore also
                    # bypasses runtime_orchestration_patch.learning_loop. Capture
                    # the authoritative workspace transition here so every
                    # successful top-level adaptive race can be learned exactly
                    # once after verified execution has completed.
                    import time
                    import uuid

                    from sophyane.runtime_orchestration_patch import _snapshot

                    before = _snapshot(workspace)
                    started = time.monotonic()

                    result = _run_adaptive_race_request(
                        message,
                        workspace=workspace,
                        config=config,
                        progress=tui_holder["app"].progress,
                    )

                    if result.get("ok"):
                        try:
                            from sophyane.sli_learner import learn_execution
                            from sophyane.sli_schema import ensure_current_schema

                            ensure_current_schema()

                            winner = result.get("winner")
                            worker = getattr(winner, "worker", None)

                            learning_result = (
                                str(result.get("answer") or "").strip()
                                or (
                                    "Adaptive race completed successfully"
                                    + (
                                        f" via {worker}."
                                        if worker
                                        else "."
                                    )
                                    + f" Attempts: {result.get('attempts', 0)}."
                                    + f" Applied: {len(result.get('applied') or [])}."
                                )
                            )

                            learned = learn_execution(
                                trace_id=(
                                    "auto-race-"
                                    + uuid.uuid4().hex[:12]
                                ),
                                request=message,
                                workspace_before=before,
                                workspace_after=_snapshot(workspace),
                                status="succeeded",
                                reward=1.0,
                                result=learning_result,
                                elapsed_seconds=(
                                    time.monotonic() - started
                                ),
                            )

                            tui_holder["app"].progress(
                                "SLI recorded adaptive race execution "
                                f"{learned.get('trace_id')} "
                                "reward="
                                f"{float(learned.get('quality_reward', 0.0)):+.2f}"
                            )

                        except Exception as error:  # noqa: BLE001
                            tui_holder["app"].progress(
                                "SLI adaptive race recording skipped safely: "
                                f"{type(error).__name__}: {error}"
                            )
                        direct_answer = str(
                            result.get("answer") or ""
                        ).strip()

                        if direct_answer:
                            return AgentResponse(direct_answer)

                        winner = result.get("winner")
                        worker = getattr(winner, "worker", None)

                        summary = (
                            "Adaptive race completed successfully"
                            + (
                                f" via {worker}."
                                if worker
                                else "."
                            )
                            + f" Attempts: {result.get('attempts', 0)}."
                            + f" Applied: {len(result.get('applied') or [])}."
                        )
                        return AgentResponse(summary)

                    error = str(
                        result.get("error")
                        or "adaptive race produced no verified result"
                    )
                    return AgentResponse(
                        f"Adaptive race failed safely: {error}"
                    )

            elif session_mode == "sli_graph":
                # SOPHYANE_MODE2_SLI_TOP_LEVEL_AUTHORITY_V1
                #
                # Mode 2 intentionally has no LLM provider.
                # The original request therefore enters SLI Graph
                # directly instead of constructing SophyaneAgent(None).
                workspace = (
                    Path.cwd().resolve()
                    / ".sophyane-workspace"
                )

                def ask(message: str) -> AgentResponse:
                    raise RuntimeError(
                        "SLI Graph mode low-level provider callback was invoked. "
                        "Original user requests must use dispatch_user_request()."
                    )

                def dispatch_user_request(
                    message: str,
                ) -> AgentResponse:
                    from sophyane.sli_graph import (
                        run_sli_graph,
                    )

                    state = run_sli_graph(
                        message,
                        workspace=workspace,
                        progress=lambda event: app.progress(event),
                    )

                    return AgentResponse(
                        state.report
                    )

            else:
                # Explicit provider modes retain the conventional provider-backed
                # SophyaneAgent path.
                agent = SophyaneAgent(
                    _create_provider_for_observable_tui(config),
                    MemoryStore(),
                    logger,
                )
                ask = agent.ask

    app = ObservableTUI(
        config=config,
        ask=ask,
        handle_internal=handle_internal_command,
        dispatch_user_request=dispatch_user_request,
    )

    if session_mode == "race":
        tui_holder["app"] = app

    return app.run()
