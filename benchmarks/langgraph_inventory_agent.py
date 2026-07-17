#!/usr/bin/env python3
"""Agentic LangGraph benchmark: build and mechanically verify a C++ SQLite CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

WORKSPACE = Path.cwd().resolve()
MAX_OUTPUT = 16_000
PROMPT = """Create a production-ready C++17 inventory-management CLI using SQLite.
It must support adding products, purchasing stock, recording sales, preventing
negative inventory, calculating daily profit, and generating a low-stock report.
Create actual files in the current workspace, compile the program, run automated
tests, repair failures, and continue until every test passes or a concrete blocker
is proven. Do not return example code or descriptive instructions."""

SYSTEM = """You are an autonomous coding agent operating inside one workspace.
Use tools to inspect and modify real files. Continue using tools until the project
configures, compiles, and passes CTest. Never fabricate tool calls, files, command
outputs, exit codes, or test results. Do not stop with a plan or code blocks.
Use C++17, SQLite prepared statements, transactions for stock mutations, CMake,
and meaningful automated tests. The external verifier will reject incomplete work
and return its exact evidence for another repair round."""


def workspace_path(relative: str) -> Path:
    candidate = (WORKSPACE / relative).resolve()
    try:
        candidate.relative_to(WORKSPACE)
    except ValueError as error:
        raise ValueError(f"path escapes workspace: {relative}") from error
    return candidate


@tool
def list_files() -> str:
    """List relevant project files in the current workspace."""
    files: list[str] = []
    excluded = {".git", ".venv", ".langgraph-venv", "__pycache__", "build"}
    for path in WORKSPACE.rglob("*"):
        if any(part in excluded for part in path.relative_to(WORKSPACE).parts):
            continue
        if path.is_file():
            files.append(str(path.relative_to(WORKSPACE)))
    return "\n".join(sorted(files)[:1000]) or "<empty workspace>"


@tool
def read_file(path: str) -> str:
    """Read one UTF-8 project file relative to the workspace."""
    target = workspace_path(path)
    if not target.is_file():
        return f"ERROR: file not found: {path}"
    if target.stat().st_size > 200_000:
        return f"ERROR: file too large: {path}"
    return target.read_text(encoding="utf-8", errors="replace")


@tool
def write_file(path: str, content: str) -> str:
    """Create or completely replace one project file in the workspace."""
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"WROTE {path} ({len(content.encode('utf-8'))} bytes)"


@tool
def run_command(argv: list[str]) -> str:
    """Run an allowlisted build/test command without a shell."""
    if not argv:
        return "ERROR: empty argv"
    allowed = {"cmake", "ctest", "g++", "c++", "make", "ninja"}
    executable = Path(argv[0]).name
    if executable not in allowed:
        return f"ERROR: executable not allowed: {executable}"
    try:
        completed = subprocess.run(
            argv,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"ERROR: {type(error).__name__}: {error}"
    output = (
        f"$ {' '.join(argv)}\n"
        f"exit_code={completed.returncode}\n"
        f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    )
    return output[-MAX_OUTPUT:]


TOOLS = [list_files, read_file, write_file, run_command]


class BuildState(MessagesState):
    verification_attempts: int
    verified: bool
    verification_evidence: str


def load_key() -> None:
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return
    path = Path.home() / ".config" / "sophyane" / "secrets.json"
    try:
        key = str(json.loads(path.read_text(encoding="utf-8"))["gemini"]).strip()
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise SystemExit(
            "No Gemini key found. Export GOOGLE_API_KEY or configure Sophyane."
        ) from error
    os.environ["GOOGLE_API_KEY"] = key


load_key()
model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.1,
    max_tokens=8192,
).bind_tools(TOOLS)


def agent_node(state: BuildState) -> dict[str, Any]:
    response = model.invoke([SystemMessage(content=SYSTEM), *state["messages"]])
    return {"messages": [response]}


def route_after_agent(state: BuildState) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "verify"


def mechanical_verification() -> tuple[bool, str]:
    commands = [
        ["cmake", "-S", ".", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
        ["cmake", "--build", "build", "--parallel", "2"],
        ["ctest", "--test-dir", "build", "--output-on-failure"],
    ]
    evidence: list[str] = []
    passed = True
    for argv in commands:
        try:
            completed = subprocess.run(
                argv,
                cwd=WORKSPACE,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            item = (
                f"$ {' '.join(argv)}\nexit_code={completed.returncode}\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
            evidence.append(item[-MAX_OUTPUT:])
            if completed.returncode != 0:
                passed = False
                break
            if argv[0] == "ctest" and (
                "100% tests passed" not in completed.stdout
                or "No tests were found" in completed.stdout
            ):
                passed = False
        except (OSError, subprocess.TimeoutExpired) as error:
            evidence.append(f"$ {' '.join(argv)}\nERROR: {error}")
            passed = False
            break
    return passed, "\n\n".join(evidence)


def verify_node(state: BuildState) -> dict[str, Any]:
    passed, evidence = mechanical_verification()
    attempt = int(state.get("verification_attempts", 0)) + 1
    update: dict[str, Any] = {
        "verification_attempts": attempt,
        "verified": passed,
        "verification_evidence": evidence,
    }
    if not passed and attempt < 6:
        update["messages"] = [
            HumanMessage(
                content=(
                    "MECHANICAL VERIFICATION FAILED. Continue repairing the real "
                    "workspace using tools. Do not explain; act. Evidence:\n" + evidence
                )
            )
        ]
    return update


def route_after_verify(state: BuildState) -> str:
    if state.get("verified") or int(state.get("verification_attempts", 0)) >= 6:
        return END
    return "agent"


graph_builder = StateGraph(BuildState)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", ToolNode(TOOLS))
graph_builder.add_node("verify", verify_node)
graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges(
    "agent", route_after_agent, {"tools": "tools", "verify": "verify"}
)
graph_builder.add_edge("tools", "agent")
graph_builder.add_conditional_edges(
    "verify", route_after_verify, {"agent": "agent", END: END}
)
graph = graph_builder.compile()

print(f"LANGGRAPH_WORKSPACE={WORKSPACE}", flush=True)
result = graph.invoke(
    {
        "messages": [HumanMessage(content=PROMPT)],
        "verification_attempts": 0,
        "verified": False,
        "verification_evidence": "",
    },
    {"recursion_limit": 100},
)

print(f"VERIFIED={str(bool(result.get('verified'))).lower()}")
print(f"VERIFICATION_ATTEMPTS={result.get('verification_attempts', 0)}")
print("VERIFICATION_EVIDENCE_BEGIN")
print(result.get("verification_evidence", ""))
print("VERIFICATION_EVIDENCE_END")
raise SystemExit(0 if result.get("verified") else 2)
