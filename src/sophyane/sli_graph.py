"""Sophyane SLI Graph — no LLM, recursion-safe, evidence-gated."""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

Progress = Callable[[str], None]
_GRAPH_DEPTH = 0


def _p(progress: Progress | None) -> Progress:
    return progress or (lambda _m: None)


# SOPHYANE_SLI_GRAPH_EXISTING_BROWSER_FAST_PATH_V1
def _existing_artifact_browser_request(request: str) -> bool:
    """Recognize commands that operate only on the current browser artifact.

    These requests must never trigger SLI retrieval or acquisition. They are
    control-plane operations on an already generated project.
    """

    text = " ".join(
        str(request or "").casefold().split()
    )

    exact = {
        "open this in browser",
        "open it in browser",
        "open in browser",
        "open this",
        "open it",
        "open output",
        "open the output",
        "open demo",
        "open the demo",
        "open website",
        "open the website",
        "open site",
        "open the site",
        "preview this",
        "preview it",
        "preview output",
        "preview the output",
        "preview website",
        "preview the website",
        "show it",
        "show this in browser",
        "show it in browser",
        "reopen it",
        "reopen this",
        "reopen in browser",
    }

    if text in exact:
        return True

    # Accept natural variants only when the browser target is explicit.
    if text.startswith(
        (
            "open ",
            "reopen ",
            "preview ",
            "show ",
        )
    ) and "browser" in text:
        return True

    return False


def _workspace_snapshot(
    workspace: Path,
) -> dict[str, Any]:
    """Capture bounded artifact evidence for SLI outcome learning."""
    root = Path(workspace)

    sample: list[dict[str, Any]] = []
    total_bytes = 0
    file_count = 0

    if not root.is_dir():
        return {
            "files": 0,
            "bytes": 0,
            "sample": [],
        }

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        try:
            relative = path.relative_to(root)
            size = path.stat().st_size
        except (OSError, ValueError):
            continue

        file_count += 1
        total_bytes += size

        if len(sample) < 80:
            sample.append(
                {
                    "path": str(relative),
                    "bytes": size,
                }
            )

    return {
        "files": file_count,
        "bytes": total_bytes,
        "sample": sample,
    }


@dataclass
class SLIState:
    request: str
    workspace: str
    route: str = ""
    report: str = ""
    success: bool = False
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    promoted: bool = False
    chunks_added: int = 0
    seconds: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def log(self, msg: str) -> None:
        self.trace.append(msg)


# SOPHYANE_LOCAL_SOFTWARE_ARTIFACT_ROUTE_V1
def _is_software_artifact_request(request: str) -> bool:
    """Recognize constructive non-browser code/software requests.

    SLI Graph has browser-oriented internet acquisition. Requests for source
    code, code snippets, libraries, APIs, CLIs, replay systems, concurrency
    tooling, etc. must never enter that browser acquisition path.
    """

    text = " ".join(
        str(request or "").casefold().split()
    )

    if not text:
        return False

    # Explicit browser/UI products remain owned by product/browser routing.
    browser_targets = (
        "website",
        "web site",
        "webpage",
        "web page",
        "web app",
        "browser app",
        "browser application",
        "html page",
        "landing page",
        "dashboard",
    )

    if any(target in text for target in browser_targets):
        return False

    constructive = any(
        token in text
        for token in (
            "build ",
            "create ",
            "develop ",
            "design ",
            "generate ",
            "implement ",
            "produce ",
            "provide ",
            "write ",
            "give me ",
            "show ",
        )
    )

    code_request = any(
        cue in text
        for cue in (
            "code snippet",
            "complete code",
            "source code",
            "python code",
            "c++ code",
            "cpp code",
            "code example",
            "implementation example",
            "working example",
            "executable example",
            "python script",
            "c++ implementation",
            "cpp implementation",
            "python implementation",
        )
    )

    software_target = any(
        cue in text
        for cue in (
            "rest api",
            "api backend",
            "backend",
            "openapi",
            "json schema",
            "client sdk",
            "command line",
            " cli",
            "library",
            "module",
            "package",
            "daemon",
            "operations agent",
            "operation agent",
            "process monitoring",
            "service monitoring",
            "monitor services",
            "port conflict",
            "port conflicts",
            "developer tool",
            "automation tool",
            "execution journal",
            "execution journaling",
            "deterministic replay",
            "replay system",
            "race condition",
            "thread interleaving",
            "thread interleavings",
            "threading",
            "async api",
            "concurrency",
        )
    )

    # Informational questions should remain memory/internet knowledge queries.
    informational_prefixes = (
        "what is ",
        "what are ",
        "explain ",
        "tell me about ",
        "describe ",
        "how does ",
        "how do ",
        "why ",
    )

    informational = text.startswith(informational_prefixes)

    if informational and not code_request:
        return False

    return bool(
        code_request
        or (constructive and software_target)
    )



# SOPHYANE_GENERAL_KNOWLEDGE_ROUTE_V1

def _is_browser_product_request(request: str) -> bool:
    """Recognize explicit construction of browser-delivered products."""
    text = " ".join(
        str(request or "").casefold().split()
    )

    if not text:
        return False

    constructive = any(
        text.startswith(prefix)
        or f" {prefix}" in text
        for prefix in (
            "build ",
            "create ",
            "make ",
            "develop ",
            "design ",
            "generate ",
            "implement ",
            "produce ",
        )
    )

    browser_target = any(
        cue in text
        for cue in (
            "website",
            "web site",
            "webpage",
            "web page",
            "web app",
            "browser app",
            "browser application",
            "html",
            "index.html",
            "landing page",
            "dashboard",
            "visualizer",
        )
    )

    return bool(
        constructive
        and browser_target
    )


def _is_general_knowledge_request(request: str) -> bool:
    """Recognize non-constructive factual/explanatory questions."""
    text = " ".join(
        str(request or "").casefold().split()
    )

    if not text:
        return False

    if _is_browser_product_request(text):
        return False

    if _is_software_artifact_request(text):
        return False

    prefixes = (
        "what is ",
        "what are ",
        "what was ",
        "who is ",
        "who was ",
        "who invented ",
        "when ",
        "where ",
        "why ",
        "how does ",
        "how do ",
        "explain ",
        "describe ",
        "tell me about ",
        "compare ",
        "define ",
    )

    return text.startswith(
        prefixes
    )


def try_grounded_knowledge(
    state: SLIState,
    progress: Progress,
) -> SLIState:
    """Produce a textual grounded answer without artifact or LLM authority."""
    if (
        state.success
        or state.meta.get("terminal")
        or state.meta.get("private")
    ):
        return state

    progress(
        "SLI-graph: grounded textual knowledge retrieval"
    )

    try:
        from sophyane.web_intel import (
            grounded_answer_from_search,
            normalize_knowledge_query,
            web_search,
        )

        retrieval_query = normalize_knowledge_query(
            state.request
        )

        search = web_search(
            retrieval_query
        )

        answer = grounded_answer_from_search(
            state.request,
            search,
        ).strip()

        if answer:
            state.report = (
                answer
                + "\n\n"
                + "Success: True\n"
                + "Artifact construction used: False\n"
                + "LLM used: False\n"
            )
            state.success = True
            state.meta["terminal"] = True
            state.meta["grounded_text_answer"] = True
            state.log(
                "grounded-knowledge success=True"
            )
            return state

        state.report = (
            "SLI-only mode could not obtain grounded textual evidence "
            "for this knowledge request.\n"
            "Success: False\n"
            "Artifact construction used: False\n"
            "LLM used: False\n"
        )
        state.meta["terminal"] = True
        state.log(
            "grounded-knowledge success=False"
        )

    except Exception as error:
        state.errors.append(
            "grounded-knowledge:"
            + f"{type(error).__name__}: {error}"
        )
        state.report = (
            "SLI-only grounded knowledge retrieval failed safely.\n"
            f"Error: {type(error).__name__}: {error}\n"
            "Success: False\n"
            "Artifact construction used: False\n"
            "LLM used: False\n"
        )
        state.meta["terminal"] = True

    return state


def classify(state: SLIState, progress: Progress) -> SLIState:
    q = (state.request or "").lower()
    progress(f"SLI-graph: classify «{state.request[:80]}»")

    # Private-account operations must never fall through to public
    # repository acquisition or reusable SLI memory.
    try:
        from sophyane.sli_personal_connector import (
            is_personal_connector_request,
        )

        if is_personal_connector_request(state.request):
            state.route = "personal_connector"
            state.meta["private"] = True
            state.log("route=personal_connector")
            progress("SLI-graph: private-data boundary activated")
            return state
    except Exception as error:
        state.errors.append(f"classify-personal:{error}")

    if any(
        key in q
        for key in (
            "website on",
            "website about",
            "website for",
            "webpage about",
            "webpage on",
            "informational site",
            "site on ",
            "site about ",
        )
    ):
        state.route = "topic_site"
    else:
        try:
            from sophyane.email_platform_deployment import (
                is_email_platform_request,
            )
            from sophyane.sli_harness_orchestrator import (
                is_harness_execution_request,
            )

            if is_email_platform_request(
                state.request
            ):
                state.route = "email_platform"

            elif is_harness_execution_request(
                state.request
            ):
                state.route = "harness_execution"

            # Generic constructive non-browser software must outrank
            # historical product/python heuristics such as "client",
            # "implement " and "fastapi".
            elif _is_browser_product_request(
                state.request
            ):
                state.route = "product_app"

            elif _is_general_knowledge_request(
                state.request
            ):
                state.route = "general_knowledge"

            elif _is_software_artifact_request(
                state.request
            ):
                # SOPHYANE_LOCAL_SOFTWARE_ARTIFACT_ROUTE_V1
                # Non-browser code generation must never fall into
                # HTML/index.html acquisition.
                state.route = "software_artifact"

            elif (
                any(
                    term in q
                    for term in (
                        "make",
                        "create",
                        "build",
                        "develop",
                        "generate",
                        "implement",
                        "design",
                    )
                )
                and any(
                    term in q
                    for term in (
                        "email service",
                        "email app",
                        "mail app",
                        "mail service",
                        "gmail",
                        "webmail",
                        "web app",
                        "browser app",
                        "dashboard",
                        "workspace",
                        "platform",
                        "client",
                    )
                )
            ):
                state.route = "product_app"

            elif any(
                key in q
                for key in (
                    "python file",
                    "audit_chain",
                    "append_event",
                    "verify_chain",
                    "safe_members",
                    "implement ",
                    "fastapi",
                    "policy_engine",
                )
            ):
                state.route = "python_harness"

            elif any(key in q for key in ("ping pong", "pong", "snake", "game", "canvas")):
                state.route = "action_or_internet"
            elif any(key in q for key in ("missing word", "missing letter", "quiz", "cloze")):
                state.route = "language_or_internet"
            else:
                state.route = "memory_then_internet"
        except Exception as error:
            state.errors.append(f"classify-harness:{error}")
            state.route = "memory_then_internet"

    progress(f"SLI-graph: route={state.route}")
    state.log(f"route={state.route}")
    return state



def _ok(state: SLIState) -> None:
    """Accept success only from an explicit validated success report."""

    state.success = "success: true" in (state.report or "").lower()
    workspace = Path(state.workspace)
    if workspace.is_dir():
        state.files = [str(path) for path in workspace.rglob("*") if path.is_file()]



def try_personal_connector(
    state: SLIState,
    progress: Progress,
) -> SLIState:
    """Execute a private connector request without public fallback."""

    progress("SLI-graph: fail-closed personal connector")

    try:
        from sophyane.sli_personal_connector import (
            run_personal_connector,
        )

        state.report = str(
            run_personal_connector(
                state.request,
                Path(state.workspace),
                progress=progress,
            )
            or ""
        )

        _ok(state)
        state.meta["terminal"] = True
        state.meta["promotion_blocked"] = True
        state.log(
            f"personal-connector success={state.success}"
        )

    except Exception as error:
        state.errors.append(
            f"personal-connector:{error}"
        )
        state.meta["terminal"] = True
        state.meta["promotion_blocked"] = True
        state.report = (
            "Sophyane private connector\n"
            "Connector available: False\n"
            f"Reason: {error}\n"
            "Internet fallback: blocked\n"
            "Memory promotion: blocked\n"
            "Success: False"
        )
        progress(
            f"SLI-graph private connector error: {error}"
        )

    return state


def try_email_platform(
    state: SLIState,
    progress: Progress,
) -> SLIState:
    """Execute only the dedicated self-hosted mail deployment domain."""
    if (
        state.success
        or state.meta.get(
            "terminal"
        )
    ):
        return state

    progress(
        "SLI-graph: dedicated self-hosted email platform"
    )

    try:
        from sophyane.email_platform_deployment import (
            run_email_platform_deployment,
        )

        state.report = str(
            run_email_platform_deployment(
                state.request,
                Path(
                    state.workspace
                ),
                progress=progress,
            )
            or ""
        )

        _ok(
            state
        )

    except Exception as error:
        state.errors.append(
            "email-platform:"
            + f"{type(error).__name__}: {error}"
        )

        state.report = (
            "Nifdu self-hosted email platform\n"
            "Handled: True\n"
            f"Error: {type(error).__name__}: {error}\n"
            "Success: False"
        )

    # Deployment is an external side-effect domain.
    # Do not fall through into repository acquisition,
    # topic-site composition or learning.
    state.meta[
        "terminal"
    ] = True

    state.meta[
        "promotion_blocked"
    ] = True

    state.meta[
        "deployment_domain"
    ] = "self_hosted_email"

    state.log(
        "email-platform "
        f"success={state.success}"
    )

    return state


def try_harness_execution(state: SLIState, progress: Progress) -> SLIState:
    if state.success:
        return state

    progress("SLI-graph: evidence-gated unified harness")
    try:
        from sophyane.sli_harness_orchestrator import run_harness_execution

        state.report = str(
            run_harness_execution(
                state.request,
                Path(state.workspace),
                progress=progress,
            )
            or ""
        )
        _ok(state)
        state.log(f"harness success={state.success}")
    except Exception as error:
        state.errors.append(f"harness:{error}")
        progress(f"SLI-graph harness error: {error}")
    return state


def try_memory_router(state: SLIState, progress: Progress) -> SLIState:
    if state.success or state.meta.get("terminal"):
        return state

    progress("SLI-graph: memory/router (no re-entry)")
    previous = os.environ.get("SOPHYANE_SLI_GRAPH")
    os.environ["SOPHYANE_SLI_GRAPH"] = "0"
    try:
        module = __import__("sophyane.sli_chunk_router", fromlist=["*"])
        function = getattr(module, "_sli_try_chunks_before_graph", None) or module.try_sli_chunks
        state.report = str(
            function(
                state.request,
                workspace=Path(state.workspace),
                progress=progress,
            )
            or ""
        )
        _ok(state)
        state.log(f"router success={state.success}")
    except Exception as error:
        state.errors.append(f"router:{error}")
        progress(f"SLI-graph router error: {error}")
    finally:
        if previous is None:
            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
        else:
            os.environ["SOPHYANE_SLI_GRAPH"] = previous
    return state


def try_topic(state: SLIState, progress: Progress) -> SLIState:
    if state.success or state.meta.get("terminal"):
        return state

    progress("SLI-graph: rich topic-site orchestration")
    try:
        rich = __import__("sophyane.code_memory.sli_rich_site_compose", fromlist=["*"])
        is_topic = getattr(rich, "is_topic_site_request", lambda _request: True)
        if not is_topic(state.request):
            return state
        function = getattr(rich, "compose_rich_topic_site", None)
        if function is not None:
            output = function(state.request, Path(state.workspace), progress=progress)
            state.report = str(output[0] if isinstance(output, tuple) else output or "")
            _ok(state)
            state.log(f"rich-topic success={state.success}")
            if state.success:
                return state
    except Exception as error:
        state.errors.append(f"rich-topic:{error}")
        progress(f"SLI-graph rich topic error: {error}; using safe topic fallback")

    try:
        module = __import__("sophyane.code_memory.topic_site_compose", fromlist=["*"])
        is_topic = getattr(module, "is_topic_site_request", lambda _request: True)
        if not is_topic(state.request):
            return state
        function = getattr(module, "compose_topic_site", None) or getattr(module, "handle_topic_site", None)
        if function is None:
            return try_memory_router(state, progress)
        try:
            output = function(state.request, Path(state.workspace), progress=progress)
        except TypeError:
            output = function(state.request, workspace=Path(state.workspace), progress=progress)
        state.report = str(output[0] if isinstance(output, tuple) else output or "")
        _ok(state)
        state.log(f"topic-fallback success={state.success}")
    except Exception as error:
        state.errors.append(f"topic:{error}")
        progress(f"SLI-graph topic fallback error: {error}")
    return state


def try_python_harness(state: SLIState, progress: Progress) -> SLIState:
    if state.success or state.meta.get("terminal"):
        return state

    progress("SLI-graph: python harness")
    try:
        from sophyane.code_memory.python_harness_compose import (
            compose_python_harness_request,
        )

        try:
            output = compose_python_harness_request(
                state.request,
                Path(state.workspace),
                progress=progress,
            )
        except TypeError:
            output = compose_python_harness_request(
                state.request,
                workspace=Path(state.workspace),
                progress=progress,
            )
        state.report = str(output[0] if isinstance(output, tuple) else output or "")
        _ok(state)
        state.log(f"python success={state.success}")
    except Exception as error:
        state.errors.append(f"python:{error}")
        progress(f"SLI-graph python error: {error}")
    return state


def try_internet(state: SLIState, progress: Progress) -> SLIState:
    if (
        state.success
        or state.meta.get("terminal")
        or state.meta.get("private")
    ):
        if state.meta.get("private"):
            progress(
                "SLI-graph: public acquisition blocked "
                "by private-data boundary"
            )
        return state

    progress("SLI-graph: internet acquire")
    try:
        from sophyane.code_memory.internet_acquire import acquire_and_build

        try:
            report = acquire_and_build(
                state.request,
                workspace=Path(state.workspace),
                progress=progress,
            )
        except TypeError:
            report = acquire_and_build(state.request, Path(state.workspace), progress)
        state.report = str(report or "")
        _ok(state)
        state.log(f"internet success={state.success}")
    except Exception as error:
        state.errors.append(f"internet:{error}")
        progress(f"SLI-graph internet error: {error}")
    return state




def try_product_reuse(
    state: SLIState,
    progress: Progress,
) -> SLIState:
    """Use browser-component memory then strict acquisition.

    Product requests must not be reinterpreted as informational
    topic-site requests while attempting reuse.
    """
    if (
        state.success
        or state.meta.get("terminal")
        or state.meta.get("private")
    ):
        return state

    workspace = Path(
        state.workspace
    )

    progress(
        "SLI-graph: product browser-memory reuse"
    )

    try:
        from sophyane.code_memory.intelligent_compose import (
            compose_browser_request,
        )
        from sophyane.code_memory.store import (
            ChunkStore,
        )

        report, _used = compose_browser_request(
            state.request,
            workspace,
            ChunkStore(),
            progress=progress,
        )

        state.report = str(
            report
            or ""
        )

        _ok(
            state
        )

        state.log(
            "product-memory "
            f"success={state.success}"
        )

    except Exception as error:
        state.errors.append(
            "product-memory:"
            + f"{type(error).__name__}: {error}"
        )

        progress(
            "SLI-graph product browser-memory miss: "
            f"{type(error).__name__}: {error}"
        )

    if state.success:
        return state

    progress(
        "SLI-graph: strict product internet acquisition"
    )

    try:
        from sophyane.code_memory.internet_acquire import (
            acquire_and_build,
        )

        try:
            report = acquire_and_build(
                state.request,
                workspace=workspace,
                progress=progress,
            )

        except TypeError:
            report = acquire_and_build(
                state.request,
                workspace,
                progress,
            )

        state.report = str(
            report
            or ""
        )

        _ok(
            state
        )

        state.log(
            "product-acquisition "
            f"success={state.success}"
        )

    except Exception as error:
        state.errors.append(
            "product-acquisition:"
            + f"{type(error).__name__}: {error}"
        )

        progress(
            "SLI-graph strict product acquisition error: "
            f"{type(error).__name__}: {error}"
        )

    return state


def try_product_app(
    state: SLIState,
    progress: Progress,
) -> SLIState:
    """Recover constructive product requests after strict SLI reuse fails."""
    if (
        state.success
        or state.meta.get("terminal")
        or state.meta.get("private")
    ):
        return state

    progress(
        "SLI-graph: acquisition miss; "
        "switching to bounded local product synthesis"
    )

    acquisition_report = str(
        state.report
        or ""
    )

    try:
        from sophyane.code_memory.sli_product_app_compose import (
            compose_product_app,
        )

        state.report = str(
            compose_product_app(
                state.request,
                Path(
                    state.workspace
                ),
                progress=progress,
                acquisition_report=acquisition_report,
            )
            or ""
        )

        _ok(
            state
        )

        state.meta[
            "product_generation_attempted"
        ] = True

        state.meta[
            "product_generation_success"
        ] = bool(
            state.success
        )

        state.log(
            "product-generation "
            f"success={state.success}"
        )

    except Exception as error:
        state.errors.append(
            "product-generation:"
            + f"{type(error).__name__}: {error}"
        )

        progress(
            "SLI-graph product synthesis failed safely: "
            f"{type(error).__name__}: {error}"
        )

    return state


def validate_and_promote(state: SLIState, progress: Progress) -> SLIState:
    if (
        state.meta.get("private")
        or state.meta.get("promotion_blocked")
    ):
        progress(
            "SLI-graph: promotion blocked for "
            "private connector route"
        )
        state.promoted = False
        state.chunks_added = 0
        return state

    if not state.success:
        return state

    progress("SLI-graph: promote")
    try:
        from sophyane.code_memory.promote_success import (
            is_success_report,
            promote_workspace,
        )

        report = state.report
        if not is_success_report(report):
            state.errors.append("promotion-blocked: report is not a validated success report")
            progress("SLI-graph: promotion blocked; success report was not validated")
            return state

        result = promote_workspace(
            Path(state.workspace),
            request=state.request,
            source="promote:sli_graph",
            report=report,
            progress=progress,
        )
        state.promoted = bool(result.get("ok"))
        state.chunks_added = int(result.get("chunks_added") or 0)

        if not state.promoted:
            reason = str(
                result.get("reason")
                or "promotion rejected"
            ).strip()

            state.errors.append(
                "promotion-blocked: "
                + reason
            )

            state.meta[
                "promotion_reason"
            ] = reason
    except Exception as error:
        state.errors.append(f"promote:{error}")
        progress(f"SLI-graph promote error: {error}")
    return state


def run_sli_graph(
    request: str,
    workspace: Path | str | None = None,
    *,
    progress: Progress | None = None,
    max_retries: int = 2,
) -> SLIState:
    global _GRAPH_DEPTH
    progress = _p(progress)

    if _GRAPH_DEPTH > 0:
        progress("SLI-graph: blocked recursive entry")
        state = SLIState(request=request, workspace=str(workspace or "."))
        state.report = "Success: False\nrecursive-entry-blocked\n"
        state.errors.append("recursive-entry-blocked")
        return state

    _GRAPH_DEPTH += 1
    started = time.perf_counter()
    try:
        root = Path(workspace or (Path.cwd() / ".sophyane-workspace"))
        root.mkdir(parents=True, exist_ok=True)
        state = SLIState(request=request, workspace=str(root))

        # SOPHYANE_SLI_GRAPH_EXISTING_BROWSER_FAST_PATH_V1
        #
        # Opening or previewing the current product is a control operation,
        # not a retrieval task. Resolve it before classify(), memory search,
        # internet acquisition, promotion, or learning.
        if _existing_artifact_browser_request(request):
            state.route = "existing_artifact_browser"

            artifact = root / "index.html"

            if not artifact.is_file():
                state.success = False
                state.report = (
                    "Success: False\n"
                    "Browser launch blocked: the current workspace has no "
                    "index.html artifact.\n"
                    "SLI retrieval used: False\n"
                    "Internet acquisition used: False\n"
                    "LLM used: False\n"
                )
                state.seconds = round(
                    time.perf_counter() - started,
                    3,
                )
                state.meta["terminal"] = True
                state.log(
                    "existing-browser-fast-path artifact-missing"
                )
                return state

            try:
                from sophyane.browser_runtime_v2 import (
                    open_verified_browser,
                )

                opened, evidence = open_verified_browser(
                    root,
                    progress,
                )

            except Exception as error:
                opened = False
                evidence = (
                    "Browser fast-path error: "
                    f"{type(error).__name__}: {error}"
                )

            state.success = bool(opened)
            state.files = ["index.html"]
            state.seconds = round(
                time.perf_counter() - started,
                3,
            )
            state.meta["terminal"] = True
            state.meta["browser_fast_path"] = True

            state.report = (
                f"Success: {state.success}\n"
                f"Artifact: {artifact}\n"
                f"{evidence}\n"
                "SLI retrieval used: False\n"
                "Internet acquisition used: False\n"
                "LLM used: False\n"
                "SLI-graph route: existing_artifact_browser; "
                f"seconds: {state.seconds}; "
                "promoted: False; chunks_added: 0\n"
            )

            state.log(
                "existing-browser-fast-path "
                f"success={state.success}"
            )

            return state

        state = classify(state, progress)

        learning_routes = {
            "topic_site",
            "product_app",
        }

        learning_before = (
            _workspace_snapshot(root)
            if state.route in learning_routes
            else None
        )

        pipelines = {
            "personal_connector": [try_personal_connector],
            "topic_site": [try_topic, try_memory_router, try_internet],
            "email_platform": [
                try_email_platform,
            ],
            "harness_execution": [
                try_harness_execution,
                try_python_harness,
                try_memory_router,
                try_internet,
            ],
            "python_harness": [try_python_harness, try_harness_execution, try_memory_router],
            "language_or_internet": [try_memory_router, try_internet],
            "action_or_internet": [try_memory_router, try_internet],
            "product_app": [
                try_product_reuse,
                try_product_app,
            ],
            # SOPHYANE_LOCAL_SOFTWARE_ARTIFACT_ROUTE_V1
            #
            # internet_acquire is browser/index.html oriented. Generic
            # software/code requests may reuse grounded SLI memory here,
            # but must never call browser acquisition.
            "software_artifact": [
                try_memory_router,
            ],
            "general_knowledge": [
                try_grounded_knowledge,
            ],
            "memory_then_internet": [try_memory_router, try_internet],
        }
        steps = pipelines.get(
            state.route,
            [try_memory_router, try_internet],
        )

        attempts = (
            1
            if state.route == "personal_connector"
            else max(1, max_retries)
        )

        for attempt in range(attempts):
            progress(
                f"SLI-graph: attempt "
                f"{attempt + 1}/{attempts}"
            )

            for step in steps:
                state = step(state, progress)

                if (
                    state.success
                    or state.meta.get("terminal")
                ):
                    break

            if (
                state.success
                or state.meta.get("terminal")
            ):
                break

        # SOPHYANE_TERMINAL_TEXT_PROMOTION_BYPASS_V1
        #
        # A completed textual knowledge response is not a workspace
        # artifact and therefore has nothing to validate or promote.
        # Product/software routes retain the existing promotion gate.
        terminal_text = (
            state.route == "general_knowledge"
            and state.meta.get("terminal")
            and state.meta.get("grounded_text_answer")
        )

        if not terminal_text:
            state = validate_and_promote(
                state,
                progress,
            )

        state.seconds = round(time.perf_counter() - started, 3)
        if state.report and "SLI-graph route:" not in state.report:
            state.report = (
                state.report.rstrip()
                + f"\nSLI-graph route: {state.route}; seconds: {state.seconds}; "
                f"promoted: {state.promoted}; chunks_added: {state.chunks_added}\n"
            )

        if (
            state.route in learning_routes
            and learning_before is not None
        ):
            try:
                from sophyane.sli_learner import (
                    learn_execution,
                )
                from sophyane.sli_schema import (
                    ensure_current_schema,
                )

                ensure_current_schema()

                learning_succeeded = (
                    state.success
                    if state.route == "product_app"
                    else (
                        state.success
                        and state.promoted
                    )
                )

                learning_status = (
                    "succeeded"
                    if learning_succeeded
                    else "failed"
                )

                learning_error = "\n".join(
                    state.errors
                )

                trace_prefix = (
                    state.route.replace(
                        "_",
                        "-",
                    )
                    + "-"
                )

                learned = learn_execution(
                    trace_id=(
                        trace_prefix
                        + uuid.uuid4().hex[:12]
                    ),
                    request=state.request,
                    workspace_before=learning_before,
                    workspace_after=_workspace_snapshot(root),
                    status=learning_status,
                    reward=(
                        1.0
                        if learning_status == "succeeded"
                        else -1.0
                    ),
                    result=state.report,
                    elapsed_seconds=state.seconds,
                    error=learning_error,
                )

                state.meta[
                    "learning"
                ] = learned

                progress(
                    "SLI-graph learned "
                    f"{state.route} outcome "
                    f"reward="
                    f"{float(learned.get('quality_reward', 0.0)):+.2f}"
                )

            except Exception as error:
                state.errors.append(
                    f"{state.route}-learning:"
                    + f"{type(error).__name__}: {error}"
                )

                progress(
                    "SLI-graph "
                    f"{state.route} learning "
                    "skipped safely: "
                    f"{type(error).__name__}: {error}"
                )

        progress(f"SLI-graph done success={state.success} in {state.seconds}s")
        return state
    finally:
        _GRAPH_DEPTH = max(0, _GRAPH_DEPTH - 1)



def try_sli_graph(message: str, workspace=None, progress=None) -> str | None:
    return run_sli_graph(message, workspace=workspace, progress=progress).report
