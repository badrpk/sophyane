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
from typing import Any


@dataclass(frozen=True)
class CapabilityPlan:
    project_type: str
    language: str
    target: str
    capabilities: tuple[str, ...]
    builder: str
    confidence: float


def classify(request: str) -> CapabilityPlan:
    text = str(request or "").lower()
    language = ""
    for marker, value in (
        ("c++", "C++"), ("c#", "C#"), ("rust", "Rust"), ("python", "Python"),
        ("node.js", "Node.js"), ("javascript", "JavaScript"), ("java", "Java"),
    ):
        if marker in text:
            language = value
            break

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
        workspace_path = (workspace or Path.cwd()).resolve()
        workspace_path.mkdir(parents=True, exist_ok=True)
        progress = progress or (lambda _message: None)
        progress(
            f"SLI Capability Planner: {plan.project_type} / {plan.language or 'unspecified'} / "
            f"{plan.target} / {plan.builder}"
        )
        if plan.builder != "CPP_ANDROID_SCAFFOLD":
            return original(
                initial_text=initial_text, original_request=original_request, ask=ask,
                workspace=workspace_path, max_steps=max_steps, progress=progress,
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
