"""Sophyane orchestration layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

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


SYSTEM_PROMPT = """You are Sophyane, a local agentic harness.

Your operating principles:
1. Use supplied local tool results as facts.
2. Never say you cannot access the computer when local tool output is supplied.
3. Do not claim you executed something unless Sophyane actually executed it.
4. When analyzing code, use the real repository report rather than inventing files.
5. Provide complete runnable code when requested.
6. Distinguish observed facts, inferences and recommendations.
7. Respect user confirmation for destructive or privileged operations.
8. Use persistent memories only when relevant.
9. Never invent tool capabilities.
10. For multi-step work, present: plan, executed steps, verification and remaining limitations.
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
            return AgentResponse(
                "Goodbye.",
                should_exit=True,
            )

        if kind == "tools":
            return AgentResponse(tools_description())

        if kind == "memory":
            return AgentResponse(self.memory.format_all())

        if kind == "remember":
            return AgentResponse(
                self.memory.remember(
                    selected_route.argument,
                    importance=8,
                )
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
                original_message,
                result.output,
                result.tool,
            )

        if kind == "repository":
            result = repository_information()
            return self._summarize_tool(
                original_message,
                result.output,
                result.tool,
            )

        if kind == "files":
            result = list_directory(
                selected_route.argument or "."
            )
            return self._summarize_tool(
                original_message,
                result.output,
                result.tool,
            )

        if kind == "read":
            if not selected_route.argument:
                return AgentResponse("Usage: /read <path>")

            result = read_text_file(selected_route.argument)
            return self._summarize_tool(
                original_message,
                result.output,
                result.tool,
            )

        if kind == "shell":
            if not selected_route.argument:
                return AgentResponse(
                    "Usage: /shell <safe-command>"
                )

            result = safe_shell(
                selected_route.argument,
                require_confirmation=True,
            )
            return AgentResponse(result.output)

        if kind in {
            "status",
            "providers",
            "doctor",
            "setup",
        }:
            return AgentResponse(
                f"INTERNAL_COMMAND:{kind}"
            )

        memory_context = self.memory.format_relevant(
            original_message
        )

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
                "Recent conversation:\n"
                + "\n".join(history_lines)
            )

        sections.append(
            f"Current user request:\n{original_message}"
        )

        if captured:
            sections.append(
                "New memories saved during this request:\n"
                + "\n".join(f"- {item}" for item in captured)
            )

        prompt = "\n\n".join(sections)

        try:
            text = self.provider.generate(
                prompt,
                SYSTEM_PROMPT,
            )
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

LOCAL TOOL OUTPUT:
{output}
"""

        try:
            answer = self.provider.generate(
                prompt,
                SYSTEM_PROMPT,
            )
        except ProviderError as error:
            self.logger.exception(
                "Tool summarization failed"
            )

            return AgentResponse(
                f"Local tool completed, but summarization failed: "
                f"{error}\n\n{output}"
            )

        return AgentResponse(answer)
