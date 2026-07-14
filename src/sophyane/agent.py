"""Sophyane orchestration layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sophyane.autonomous_builder import (
    run_inventory_workflow,
    supports_request as supports_autonomous_build,
)
from sophyane.memory import MemoryStore
from sophyane.providers.base import Provider, ProviderError
from sophyane.router import Route, route
from sophyane.tools import (
    list_directory,
    read_text_file,
    repository_information,
    safe_shell,
    system_information,
    tools_description,
)


SYSTEM_PROMPT = """You are Sophyane, a local agentic software harness.

Operating rules:
1. Use supplied local tool results as facts.
2. Never claim you lack computer access when local tool output is supplied.
3. Never claim that you created, executed, tested, patched, deployed, or verified anything unless a real tool result proves it.
4. Before multi-step work, extract explicit acceptance criteria from the request and track every criterion to completion.
5. Make reasonable, clearly stated assumptions when details are missing. Do not replace a solvable task with a questionnaire.
6. Inspect available tools and the environment before describing limitations. State only the specific unavailable operation, then use the best available fallback.
7. For software requests, distinguish artifact types correctly: backend/API, CLI, library, mobile, and browser UI are different. Never satisfy a REST API request by generating only index.html.
8. For repository analysis, identify the actual project root and exclude caches, virtual environments, package registries, build output, node_modules, and generated artifacts unless explicitly requested.
9. For failures, use a bounded repair loop: execute, capture exact command/output/exit code, diagnose, apply the smallest safe fix, rerun, and stop only on verified success or a documented blocker.
10. Evidence is mandatory for completion claims. Include commands, exit codes, test counts, relevant file paths, endpoint checks, or other concrete proof.
11. Do not mark a task complete while any mandatory acceptance criterion is unverified.
12. Respect confirmation requirements for destructive, privileged, financial, or externally visible actions.
13. Use persistent memories only when relevant and never invent tool capabilities.
14. Keep capability notices brief. Do not repeatedly recite generic AI limitations.
15. For multi-step work, report: assumptions, acceptance criteria, executed steps, evidence, verification, and remaining limitations.
"""


@dataclass
class AgentResponse:
    text: str
    should_exit: bool = False


class SophyaneAgent:
    def __init__(
        self,
        provider: Provider,
        memory: MemoryStore,
        logger: logging.Logger,
    ) -> None:
        self.provider = provider
        self.memory = memory
        self.logger = logger

    def ask(self, message: str) -> AgentResponse:
        message = message.strip()

        if not message:
            return AgentResponse("Please enter a request.")

        # v11 invariant: supported autonomous workflows run before normal
        # conversational routing. This prevents the LLM from replacing real
        # execution with plans or code snippets.
        if supports_autonomous_build(message):
            self.memory.record_message("user", message)
            try:
                result = run_inventory_workflow(message)
            except Exception as error:
                self.logger.exception("Autonomous software workflow failed")
                result = (
                    "Autonomous workflow failed without claiming success: "
                    f"{error}"
                )
            self.memory.record_message("assistant", result)
            return AgentResponse(result)

        self.memory.record_message("user", message)
        captured = self.memory.auto_capture(message)
        selected_route = route(message)

        try:
            response = self._execute_route(
                selected_route,
                original_message=message,
                captured=captured,
            )
        except Exception as error:
            self.logger.exception("Agent execution failed")
            response = AgentResponse(
                f"Sophyane encountered an error: {error}\n"
                "Run /doctor and inspect ~/.sophyane/logs/sophyane.log."
            )

        self.memory.record_message("assistant", response.text)
        return response

    def _execute_route(
        self,
        selected_route: Route,
        original_message: str,
        captured: list[str],
    ) -> AgentResponse:
        kind = selected_route.kind

        if kind == "exit":
            return AgentResponse("Goodbye.", should_exit=True)

        if kind == "tools":
            return AgentResponse(tools_description())

        if kind == "memory":
            return AgentResponse(self.memory.format_all())

        if kind == "remember":
            return AgentResponse(
                self.memory.remember(selected_route.argument, importance=8)
            )

        if kind == "forget":
            try:
                memory_id = int(selected_route.argument)
            except ValueError:
                return AgentResponse("Usage: /forget <memory-id>")
            deleted = self.memory.forget(memory_id)
            return AgentResponse(
                f"Memory {memory_id} deleted."
                if deleted
                else f"Memory {memory_id} not found."
            )

        if kind == "system":
            result = system_information()
            return self._summarize_tool(
                original_message, result.output, result.tool
            )

        if kind == "repository":
            result = repository_information()
            return self._summarize_tool(
                original_message, result.output, result.tool
            )

        if kind == "files":
            result = list_directory(selected_route.argument or ".")
            return self._summarize_tool(
                original_message, result.output, result.tool
            )

        if kind == "read":
            if not selected_route.argument:
                return AgentResponse("Usage: /read <path>")
            result = read_text_file(selected_route.argument)
            return self._summarize_tool(
                original_message, result.output, result.tool
            )

        if kind == "shell":
            if not selected_route.argument:
                return AgentResponse("Usage: /shell <safe-command>")
            result = safe_shell(
                selected_route.argument,
                require_confirmation=True,
            )
            return AgentResponse(result.output)

        if kind in {"status", "providers", "doctor", "setup"}:
            return AgentResponse(f"INTERNAL_COMMAND:{kind}")

        memory_context = self.memory.format_relevant(original_message)
        recent = self.memory.recent_messages(limit=6)
        history_lines = [
            f"{item['role']}: {item['content']}"
            for item in recent[:-1]
        ]

        sections = []
        if memory_context:
            sections.append(memory_context)
        if history_lines:
            sections.append(
                "Recent conversation:\n" + "\n".join(history_lines)
            )
        sections.append(f"Current user request:\n{original_message}")
        if captured:
            sections.append(
                "New memories saved during this request:\n"
                + "\n".join(f"- {item}" for item in captured)
            )

        prompt = "\n\n".join(sections)
        try:
            text = self.provider.generate(prompt, SYSTEM_PROMPT)
        except ProviderError:
            self.logger.exception("Provider generation failed")
            raise
        return AgentResponse(text)

    def _summarize_tool(
        self,
        request: str,
        output: str,
        tool_name: str,
    ) -> AgentResponse:
        prompt = f"""The user requested:

{request}

Sophyane executed the local tool named "{tool_name}".

Analyze the real output below. Do not say you lack access.
Do not invent facts. Highlight errors and practical next steps.
Do not claim completion unless the output proves every requested criterion.

LOCAL TOOL OUTPUT:
{output}
"""
        try:
            answer = self.provider.generate(prompt, SYSTEM_PROMPT)
        except ProviderError as error:
            self.logger.exception("Tool summarization failed")
            return AgentResponse(
                "Local tool completed, but summarization failed: "
                f"{error}\n\n{output}"
            )
        return AgentResponse(answer)
