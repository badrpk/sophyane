"""Deterministic capability planning and bounded software scaffolding for SLI.

SLI classifies executable software requests before the adaptive provider loop. The
planner freezes language, target and requested capabilities, then selects a safe
builder. LLMs may later improve bounded files, but they are not required to create
the initial usable project.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class CapabilityPlan:
    project_type: str
    language: str
    target: str
    capabilities: tuple[str, ...]
    builder: str
    confidence: float


# SOPHYANE_FILESYSTEM_PLANNER_V16
def _latest_modified_file_request(request: str) -> bool:
    """Recognize a semantic request for the latest modified file."""
    text = " ".join(
        str(request or "").lower().split()
    )

    file_objects = (
        "file",
        "files",
        "document",
        "documents",
    )

    recency_terms = (
        "last",
        "latest",
        "newest",
        "most recent",
        "most recently",
        "recently",
    )

    modification_terms = (
        "amended",
        "amendment",
        "modified",
        "changed",
        "edited",
        "updated",
        "touched",
        "worked on",
    )

    question_terms = (
        "what",
        "which",
        "show",
        "find",
        "tell",
        "identify",
        "locate",
    )

    has_file = any(
        term in text
        for term in file_objects
    )

    has_recency = any(
        term in text
        for term in recency_terms
    )

    has_modification = any(
        term in text
        for term in modification_terms
    )

    has_question = any(
        term in text
        for term in question_terms
    )

    return (
        has_file
        and has_recency
        and (
            has_modification
            or has_question
        )
    )


def classify(request: str) -> CapabilityPlan:
    text = str(request or "").lower()

    # SOPHYANE_FILESYSTEM_PLANNER_V16
    if _latest_modified_file_request(request):
        return CapabilityPlan(
            "filesystem_inspection",
            "",
            "active workspace",
            ("filesystem.latest_modified",),
            "FILESYSTEM_LATEST_MODIFIED",
            0.99,
        )

    language = ""
    for marker, value in (
        ("c++", "C++"), ("c#", "C#"), ("rust", "Rust"), ("python", "Python"),
        ("node.js", "Node.js"), ("javascript", "JavaScript"), ("java", "Java"),
    ):
        if marker in text:
            language = value
            break

    # SOPHYANE_FULL_STACK_PRODUCT_CLASSIFIER_V1
    #
    # A request describing both browser-facing UI and server/data
    # capabilities is a web software product, not an unspecified
    # "portable desktop" task. Freeze that architecture before an LLM
    # worker is consulted so the provider cannot silently turn a SaaS
    # request into Swing, a CLI, or a static HTML mock-up.
    web_surface = any(
        marker in text
        for marker in (
            "saas",
            "web frontend",
            "web application",
            "web app",
            "browser frontend",
            "responsive frontend",
            "responsive web",
        )
    )

    api_surface = any(
        marker in text
        for marker in (
            "rest api",
            "restful api",
            "api endpoint",
            "api endpoints",
            "backend api",
        )
    )

    persistent_surface = any(
        marker in text
        for marker in (
            "persistent database",
            "database",
            "sqlite",
            "postgres",
            "postgresql",
            "mysql",
            "persistence",
        )
    )

    test_surface = any(
        marker in text
        for marker in (
            "automated tests",
            "test suite",
            "pytest",
            "unit tests",
            "integration tests",
        )
    )

    crud_surface = any(
        marker in text
        for marker in (
            "create/edit/delete",
            "create, edit and delete",
            "create edit delete",
            "crud",
        )
    )

    full_stack_score = sum(
        (
            web_surface,
            api_surface,
            persistent_surface,
            test_surface,
            crud_surface,
        )
    )

    if (
        "saas" in text
        or full_stack_score >= 3
    ):
        full_stack_caps: list[str] = []

        if web_surface:
            full_stack_caps.append(
                "responsive_web_frontend"
            )

        if api_surface:
            full_stack_caps.append(
                "rest_api"
            )

        if persistent_surface:
            full_stack_caps.append(
                "persistent_database"
            )

        if crud_surface:
            full_stack_caps.append(
                "crud"
            )

        if any(
            marker in text
            for marker in (
                "validation",
                "error handling",
                "input validation",
            )
        ):
            full_stack_caps.append(
                "validation"
            )

        if test_surface:
            full_stack_caps.append(
                "automated_tests"
            )

        if any(
            marker in text
            for marker in (
                "dashboard",
                "statistics",
                "analytics",
            )
        ):
            full_stack_caps.append(
                "dashboard"
            )

        if any(
            marker in text
            for marker in (
                "search",
                "filter",
                "filtering",
            )
        ):
            full_stack_caps.append(
                "search_filtering"
            )

        # When the user did not dictate a language, use Python as the
        # portable local-service baseline. Python + sqlite3 are suitable
        # for Termux and do not imply Maven/Gradle/Node availability.
        if not language:
            language = "Python"

        return CapabilityPlan(
            "full_stack_web_application",
            language,
            "local web application",
            tuple(
                dict.fromkeys(
                    full_stack_caps
                )
            ),
            "FULL_STACK_PROVIDER_BOUNDED",
            0.98,
        )

    if any(x in text for x in ("android", "phone", "mobile")):
        target = "Android phone"
    elif "windows" in text:
        target = "Windows"
    elif any(x in text for x in ("linux", "termux")):
        target = "Linux/Termux"
    else:
        target = "portable desktop"

    caps: list[str] = []
    if any(x in text for x in ("email", "emails", "gmail", "imap")):
        caps.append("email_access")
    if any(x in text for x in ("reply", "respond")):
        caps.append("automatic_reply")
    if any(x in text for x in ("oauth", "login", "authenticate")) or "email_access" in caps:
        caps.append("oauth_authentication")
    if any(x in text for x in ("background", "automatic", "automatically")):
        caps.append("background_processing")

    if language == "C++" and target == "Android phone":
        return CapabilityPlan("native_mobile_software", language, target, tuple(dict.fromkeys(caps)), "CPP_ANDROID_SCAFFOLD", 0.98)
    if language:
        return CapabilityPlan("software_project", language, target, tuple(dict.fromkeys(caps)), "PROVIDER_BOUNDED", 0.9)
    return CapabilityPlan("general_task", language, target, tuple(dict.fromkeys(caps)), "PROVIDER_BOUNDED", 0.55)


def _cpp_android_files(plan: CapabilityPlan) -> dict[str, str]:
    capabilities = ", ".join(plan.capabilities) or "none"
    readme = f"""# SLI Android Email Assistant Scaffold

Target: {plan.target}
Language: {plan.language}
Capabilities: {capabilities}

This is a safe native C++ core scaffold for an Android email assistant. Android UI,
OAuth consent and background scheduling must be connected through a thin Kotlin/Java
host because Android does not expose those platform APIs directly to standalone C++.

Security rules:
- Never store an email password.
- Use OAuth 2.0 tokens from the Android host.
- Keep automatic replies disabled until the user explicitly enables a rule.
- Start in dry-run mode and log the reply that would be sent.

Build the native core with CMake. Integrate `EmailAssistant` through JNI from an
Android Studio project. The generated core intentionally does not send mail until a
real authenticated adapter is supplied.
"""
    cmake = """cmake_minimum_required(VERSION 3.22)
project(sli_email_assistant LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
add_library(sli_email_assistant STATIC src/email_assistant.cpp)
target_include_directories(sli_email_assistant PUBLIC include)
add_executable(sli_email_assistant_demo src/main.cpp)
target_link_libraries(sli_email_assistant_demo PRIVATE sli_email_assistant)
"""
    header = """#pragma once
#include <string>

struct EmailMessage {
    std::string id;
    std::string sender;
    std::string subject;
    std::string body;
};

struct ReplyDecision {
    bool should_reply{false};
    std::string reply_text;
    std::string reason;
};

class EmailAssistant {
public:
    ReplyDecision evaluate(const EmailMessage& message) const;
};
"""
    source = """#include \"email_assistant.hpp\"
#include <algorithm>
#include <cctype>

ReplyDecision EmailAssistant::evaluate(const EmailMessage& message) const {
    std::string subject = message.subject;
    std::transform(subject.begin(), subject.end(), subject.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    if (subject.find(\"urgent\") != std::string::npos) {
        return {true, \"Thank you for your message. I have received it and will respond shortly.\", \"urgent subject rule\"};
    }
    return {false, \"\", \"no approved reply rule matched\"};
}
"""
    main = """#include \"email_assistant.hpp\"
#include <iostream>

int main() {
    EmailAssistant assistant;
    EmailMessage sample{\"demo-1\", \"sender@example.com\", \"Urgent request\", \"Please confirm receipt.\"};
    const auto result = assistant.evaluate(sample);
    std::cout << \"Dry run: \" << (result.should_reply ? result.reply_text : result.reason) << '\\n';
    return 0;
}
"""
    config = json.dumps({
        "dry_run": True,
        "automatic_reply_enabled": False,
        "provider": "gmail_or_imap_via_android_host",
        "oauth_required": True,
    }, indent=2) + "\n"
    return {
        "README.md": readme,
        "CMakeLists.txt": cmake,
        "include/email_assistant.hpp": header,
        "src/email_assistant.cpp": source,
        "src/main.cpp": main,
        "config.example.json": config,
    }


def install_sli_capability_planner() -> None:
    from sophyane import adaptive_execution

    if getattr(adaptive_execution, "_sli_capability_planner_installed", False):
        return
    original = adaptive_execution.run_adaptive_loop

    def run(*, initial_text: str, original_request: str, ask: Any, workspace: Path | None = None,
            max_steps: int = 12, progress: Any = None) -> str:
        plan = classify(original_request)
        progress = progress or (lambda _message: None)

        # The complete request is available at this layer. Prefer an explicit
        # absolute workspace path. Semantic refinement may remove path
        # separators, so fall back to the process launch directory when the
        # request still clearly requires the current workspace.
        match = re.search(
            r"(?:work exclusively inside|work inside|workspace(?: is|:)?|"
            r"current working directory(?: is|:)?)\s*[`\"']?"
            r"(/[A-Za-z0-9_./~+@%=-]+)",
            original_request,
            flags=re.IGNORECASE,
        )

        if match:
            raw_path = match.group(1).rstrip("`\"'.,;:")
            workspace_path = Path(raw_path).expanduser().resolve()
            progress(
                f"Using explicitly requested workspace: {workspace_path}"
            )
        else:
            normalized_request = " ".join(
                original_request.lower().split()
            )
            workspace_markers = (
                "work exclusively inside",
                "work inside",
                "current working directory",
                "in the current directory",
                "inside the workspace",
            )

            if any(
                marker in normalized_request
                for marker in workspace_markers
            ):
                workspace_path = Path.cwd().resolve()
                progress(
                    "Explicit workspace path was unavailable after semantic "
                    f"refinement; using caller directory: {workspace_path}"
                )
            else:
                workspace_path = (
                    workspace or Path.cwd()
                ).resolve()

        workspace_path.mkdir(parents=True, exist_ok=True)
        progress(
            f"SLI Capability Planner: {plan.project_type} / {plan.language or 'unspecified'} / "
            f"{plan.target} / {plan.builder}"
        )
        # SOPHYANE_FILESYSTEM_PLANNER_V16
        if plan.builder == "FILESYSTEM_LATEST_MODIFIED":
            from sophyane import execution_runtime as runtime

            progress(
                "SLI Ontology: filesystem / "
                "inspect_file_metadata / "
                "filesystem.latest_modified"
            )

            progress(
                "SLI Capability Binding: provider interpretation "
                "accepted; deterministic runtime owns execution"
            )

            action = {
                "type": "filesystem.latest_modified",
                "scope": "workspace",
                "access_mode": "read_only",
                "original_request": original_request,
                "provider_interpretation": str(
                    initial_text or ""
                ),
            }

            ok, evidence = runtime.execute_action(
                action,
                workspace_path,
                progress,
            )

            if not ok:
                progress(
                    "SLI Validation: grounded filesystem "
                    "evidence rejected"
                )
                return (
                    "Filesystem inspection failed.\n\n"
                    + str(evidence)
                )

            progress(
                "SLI Validation: grounded filesystem "
                "evidence accepted"
            )

            try:
                payload = json.loads(
                    str(evidence)
                )
            except json.JSONDecodeError:
                return (
                    "The latest-file capability completed, "
                    "but its evidence was not valid JSON.\n\n"
                    + str(evidence)
                )

            relative_path = str(
                payload.get("relative_path")
                or payload.get("absolute_path")
                or "<unknown>"
            )

            modified = str(
                payload.get("modified_iso")
                or "<unknown>"
            )

            size = payload.get(
                "size_bytes",
                "<unknown>",
            )

            candidate_count = payload.get(
                "candidate_count",
                "<unknown>",
            )

            return (
                "Most recently amended file:\n"
                f"{relative_path}\n\n"
                f"Modified: {modified}\n"
                f"Size: {size} bytes\n"
                f"Files inspected: {candidate_count}\n\n"
                "Grounding evidence:\n"
                "- Read directly from filesystem metadata\n"
                "- Verified as an existing regular file\n"
                "- Verified inside the active workspace\n"
                "- No mutation performed\n"
                "- No browser opened\n"
                "- No shell command selected by the provider"
            )

        if plan.builder == "FULL_STACK_PROVIDER_BOUNDED":
            # SOPHYANE_FULL_STACK_RUNTIME_CONTRACT_V1
            #
            # SLI owns architecture. The provider is an implementation worker.
            # The local Termux baseline intentionally depends only on Python
            # stdlib + sqlite3 + browser JavaScript + pytest.
            #
            # This prevents provider drift into Swing/Maven/Gradle, static-only
            # HTML, or a fake in-memory backend when the request requires a
            # persistent full-stack local product.
            contract = (
                "\n\n"
                "=== SOPHYANE FULL-STACK ARCHITECTURE CONTRACT ===\n"
                "SLI has classified this request as a full-stack local web application.\n"
                "You are an implementation worker inside this fixed architecture.\n\n"

                "REQUIRED STACK:\n"
                "- Python 3 standard library for the backend.\n"
                "- Python sqlite3 module for persistent storage.\n"
                "- http.server BaseHTTPRequestHandler or ThreadingHTTPServer for HTTP.\n"
                "- HTML/CSS/vanilla JavaScript responsive frontend.\n"
                "- pytest or Python unittest for automated tests.\n"
                "- Bind application only to 127.0.0.1.\n\n"

                "REQUIRED PRODUCT STRUCTURE:\n"
                "- Multiple project files, not one giant file.\n"
                "- A real backend server.\n"
                "- A real persistent SQLite database file.\n"
                "- REST-style JSON endpoints.\n"
                "- Frontend must call the backend API.\n"
                "- Seed/demo data must be inserted deterministically.\n"
                "- Input validation and useful JSON errors are required.\n"
                "- Tests must exercise backend behavior.\n"
                "- The application must actually be run locally.\n"
                "- API behavior must be mechanically verified.\n"
                "- Frontend must be mechanically browser/HTTP verified.\n\n"

                "FORBIDDEN ARCHITECTURE DRIFT:\n"
                "- Do not use Java, Swing, Maven, Gradle, Android, Electron, or desktop GUI frameworks.\n"
                "- Do not require Flask, FastAPI, Django, Uvicorn, npm packages, or external Python packages.\n"
                "- Do not satisfy the request with only index.html.\n"
                "- Do not use an in-memory-only database when persistence is requested.\n"
                "- Do not replace the requested REST API with frontend-only localStorage.\n"
                "- Do not return prose when an executable action is required.\n\n"

                "ACTION PROTOCOL:\n"
                "- Return exactly one executable JSON action at a time.\n"
                "- Use only relative paths inside the active workspace.\n"
                "- Use write_file for a new complete file.\n"
                "- Use append_file only for a genuine continuation.\n"
                "- Use run_command to run tests or start/verify the application.\n"
                "- Never invoke unavailable tools such as mvn or gradle.\n"
                "- Keep working until files, database, tests, API and frontend are verified.\n"
                "=== END FULL-STACK ARCHITECTURE CONTRACT ===\n"
            )

            # SOPHYANE_FULL_STACK_CONTRACT_CHANNEL_FIX_V1
            #
            # initial_text is already-generated provider output. It is parsed
            # by adaptive_execution as an executable action/artifact and must
            # therefore remain byte-for-byte provider output. Appending the
            # architecture contract here corrupts otherwise parseable JSON.
            #
            # original_request, on the other hand, is instruction context used
            # by repair/follow-up provider prompts, so the fixed architecture
            # contract belongs there.
            bounded_initial = str(
                initial_text or ""
            )

            bounded_request = (
                str(original_request or "")
                + contract
            )

            progress(
                "SLI Full-Stack Contract: "
                "Python stdlib + sqlite3 + HTTP + browser frontend + tests"
            )

            return original(
                initial_text=bounded_initial,
                original_request=bounded_request,
                ask=ask,
                workspace=workspace_path,
                max_steps=max(max_steps, 32),
                progress=progress,
            )

        if plan.builder != "CPP_ANDROID_SCAFFOLD":
            return original(
                initial_text=initial_text,
                original_request=original_request,
                ask=ask,
                workspace=workspace_path,
                max_steps=max_steps,
                progress=progress,
            )

        files = _cpp_android_files(plan)
        for relative, content in files.items():
            target = workspace_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        evidence = [f"- wrote {path} ({len(content.encode('utf-8'))} bytes)" for path, content in files.items()]
        ledger = workspace_path / ".sophyane-capability-plan.json"
        ledger.write_text(json.dumps({"ts": time.time(), **asdict(plan)}, indent=2), encoding="utf-8")
        return (
            "SLI created a safe C++ Android email-assistant scaffold without depending on provider-generated project JSON.\n\n"
            f"Workspace: {workspace_path}\nBuilder: {plan.builder}\n"
            "The native core is dry-run by default. OAuth, Gmail/IMAP access and Android background work remain explicit host integrations.\n\n"
            "Execution evidence:\n" + "\n".join(evidence) + "\n- capability ledger written"
        )

    adaptive_execution.run_adaptive_loop = run
    adaptive_execution._sli_capability_planner_installed = True
