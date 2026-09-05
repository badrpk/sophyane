"""Sophyane orchestration layer."""

from __future__ import annotations

# --- sophyane native fast-path hook ---
try:
    from sophyane.native.fast_path import try_fast_path as _sophyane_try_fast_path
except Exception:
    _sophyane_try_fast_path = None
# --- end fast-path import ---


import logging
import os
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

# Compact system prompt for tiny local models (llama.cpp GGUF on low-RAM hosts).
LOCAL_CHAT_SYSTEM_PROMPT = (
    "You are Sophyane, a helpful local AI assistant. "
    "Answer clearly and briefly. Do not invent tool runs or file edits. "
    "If you lack information, say so."
)


@dataclass
class AgentResponse:
    text: str
    should_exit: bool = False


def _needs_local_graph(request: str) -> bool:
    text = " ".join(str(request or "").lower().split())
    return len(text) >= 180 or sum(
        marker in text
        for marker in ("design", "debug", "architecture", "implement", "code", "review", "multiple", "requirements")
    ) >= 2


def _local_graph_answer(provider: Provider, request: str) -> str | None:
    """Decompose difficult local work under the existing Mode-3 TXQ policy."""
    from sophyane.mode3_meta_rsi import choose_txq_policy
    from sophyane.readonly_task_graph import ReadonlyGraphNode, execute_readonly_task_graph

    policy = choose_txq_policy(request)
    roles = [
        ("analyst", "Extract concrete requirements and constraints"),
        ("solver", "Develop a technically correct solution"),
        ("critic", "Identify edge cases, failure modes, and tests"),
    ]
    if policy.decomposition_depth >= 2:
        roles.extend([
            ("security", "Review security, safety, and permission concerns"),
            ("performance", "Review complexity, resource limits, and scalability"),
        ])
    if policy.decomposition_depth >= 3:
        roles.extend([
            ("integration", "Review integration boundaries and operational behavior"),
            ("verification", "Define deterministic checks that would prove correctness"),
        ])

    outputs: dict[str, str] = {}
    prompt_limit = max(1200, min(policy.context_budget_chars // max(1, len(roles)), 5000))

    def worker(name: str, instruction: str):
        def run():
            text = provider.generate(
                f"{instruction}. Return concise evidence; do not edit files.\n\nREQUEST:\n{request[:policy.context_budget_chars]}",
                LOCAL_CHAT_SYSTEM_PROMPT,
            )
            outputs[name] = str(text).strip()[:prompt_limit]
            return {"ok": bool(outputs[name]), "text": outputs[name]}
        return run

    nodes = [ReadonlyGraphNode(name, worker(name, instruction)) for name, instruction in roles]

    def aggregate():
        evidence = "\n\n".join(f"{name.upper()}:\n{outputs.get(name, '')}" for name, _ in roles)
        text = provider.generate(
            "Synthesize a direct answer to the original request from the verified substep evidence. "
            "Resolve contradictions conservatively, include correct code when requested, and do not mention orchestration. "
            "Do not edit files.\n\n"
            f"ORIGINAL REQUEST:\n{request}\n\n{evidence}",
            LOCAL_CHAT_SYSTEM_PROMPT,
        )
        answer = str(text).strip()[:policy.context_budget_chars]
        outputs["aggregate"] = answer
        return {"ok": bool(answer), "text": answer}

    nodes.append(ReadonlyGraphNode("aggregate", aggregate, tuple(name for name, _ in roles)))

    def verify():
        draft = outputs.get("aggregate", "")
        text = provider.generate(
            "Verify and correct this draft answer against the original request. Return only the final user-facing answer; "
            "preserve correct details, remove unsupported claims, and do not edit files.\n\n"
            f"REQUEST:\n{request}\n\nDRAFT:\n{draft}",
            LOCAL_CHAT_SYSTEM_PROMPT,
        )
        answer = str(text).strip()[:policy.context_budget_chars]
        return {"ok": bool(answer), "text": answer}

    nodes.append(ReadonlyGraphNode("verify", verify, ("aggregate",)))
    result = execute_readonly_task_graph(
        nodes,
        max_workers=min(5, max(2, policy.decomposition_depth + 2)),
        deadline_seconds=float(max(60, min(180, policy.wall_time_budget_sec))),
    )
    if not result.get("ok"):
        return None
    for node in result.get("nodes", []):
        if node.get("node_id") == "verify":
            return str(node.get("text") or "").strip() or None
    return None


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
        # Mode 2.5 already has an SLI-grounded request envelope. Do not let
        # broad connector heuristics reinterpret that envelope as an action
        # (for example, treating a test-plan phrase as a calendar request).
        hybrid_mode = os.environ.get("SOPHYANE_SESSION_MODE") == "sli_local_hybrid"
        if not hybrid_mode:
            try:
                from sophyane.capability_executors import try_connector_fast_path
                _cr = try_connector_fast_path(message)
                if _cr:
                    return AgentResponse(_cr)
            except Exception:
                pass
        message = message.strip()

        if not message:
            return AgentResponse("Please enter a request.")
        if hybrid_mode:
            try:
                graph_answer = _local_graph_answer(self.provider, message)
                if graph_answer:
                    return AgentResponse(graph_answer)
            except Exception:
                pass
        if not hybrid_mode:
            try:
                from sophyane.native_capability import try_any_native_reply
                _native = try_any_native_reply(message)
            except Exception:
                _native = None
            if _native:
                # SOPHYANE_NATIVE_CONVERSATION_CONTINUITY_V1
                #
                # A successful native answer is still a conversational turn.
                # Persist both sides before returning so the next provider-backed
                # request receives the same recent context as any LLM response.
                self.memory.record_message(
                    "user",
                    message,
                )
                self.memory.record_message(
                    "assistant",
                    str(_native),
                )
                return AgentResponse(_native)

        if not hybrid_mode:
            try:
                from sophyane.capability_gap_messages import capability_gap_reply
                gap = capability_gap_reply(message)
                if gap:
                    return AgentResponse(gap)
            except Exception:
                pass

        # SOPHYANE_UNIFIED_EXECUTION_KERNEL_V1
        # One typed execution kernel owns deterministic local actions before
        # provider planning. Existing deterministic capabilities remain
        # registered inside the kernel for compatibility.
        try:
            from sophyane.unified_execution_kernel import execute_text

            kernel_reply = execute_text(message)
            if kernel_reply is not None:
                # SOPHYANE_KERNEL_CONVERSATION_CONTINUITY_V1
                #
                # Deterministic kernel answers participate in the same
                # conversation as later provider-backed turns.
                self.memory.record_message(
                    "user",
                    message,
                )
                self.memory.record_message(
                    "assistant",
                    str(kernel_reply),
                )
                return AgentResponse(kernel_reply)
        except Exception:
            # Preserve existing routing if a kernel capability fails to load.
            pass

        # SOPHYANE_CAPABILITY_EXECUTOR_FASTPATH_V1
        # Run available deterministic capabilities without spending provider
        # tokens or entering the adaptive software-build loop.
        try:
            from sophyane.capability_executors import execute_deterministic_text

            executor_reply = execute_deterministic_text(message)
            if executor_reply is not None:
                return AgentResponse(executor_reply)
        except Exception:
            # Existing routing remains the safe fallback.
            pass

        # Persistent timer ticks must not pollute conversation memory or call LLMs.
        if message.lower() in {"/daemon-tick", "daemon-tick", "/daemon"}:
            from sophyane.daemon_runtime import run_daemon_tick

            return AgentResponse(run_daemon_tick().to_text())

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

        if kind == "daemon":
            from sophyane.daemon_runtime import run_daemon_tick

            report = run_daemon_tick()
            return AgentResponse(report.to_text())

        if kind in {"status", "providers", "doctor", "setup"}:
            return AgentResponse(f"INTERNAL_COMMAND:{kind}")

        # Bound prompt size only when the provider currently serving the request
        # is genuinely local. A cloud-first fallback chain may contain local
        # providers without making the active Gemini/OpenAI request local.
        def provider_id(value: object) -> str:
            if isinstance(value, str):
                return value.strip().lower()
            metadata = getattr(value, "metadata", None)
            return str(
                getattr(metadata, "provider_id", "")
                or getattr(value, "provider_id", "")
                or ""
            ).strip().lower()

        active_provider = (
            provider_id(getattr(self.provider, "last_provider", ""))
            or provider_id(getattr(self.provider, "primary", ""))
            or provider_id(self.provider)
        )
        local_mode = active_provider == "local_gguf"

        if local_mode:
            # Skip bulky memory dumps — they drown 0.5B–1B models.
            sections = [f"User: {original_message}"]
            prompt = "\n".join(sections)
            system = LOCAL_CHAT_SYSTEM_PROMPT
        else:
            memory_context = self.memory.format_relevant(original_message)
            if len(memory_context) > 1200:
                memory_context = memory_context[:1200] + "\n…"
            recent = self.memory.recent_messages(limit=4)
            history_lines = []
            for item in recent[:-1]:
                content = str(item.get("content") or "")
                if len(content) > 400:
                    content = content[:400] + "…"
                history_lines.append(f"{item['role']}: {content}")

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
            if len(prompt) > 6000:
                prompt = prompt[-6000:]
            system = (
                SYSTEM_PROMPT
                + "\n\nSOPHYANE_RESPONSE_MODE: CHAT"
                + "\nReturn a direct user-facing answer."
                + "\nDo not return planner JSON or executable action JSON."
            )
        if local_mode and _needs_local_graph(original_message):
            try:
                graph_answer = _local_graph_answer(self.provider, original_message)
                if graph_answer:
                    return AgentResponse(graph_answer)
            except Exception:
                # Graph assistance is advisory; preserve the normal local path.
                pass

        try:
            text = self.provider.generate(prompt, system)
        except ProviderError as error:
            message = str(error).strip().lower()
            expected_cancellation = (
                "provider generation cancelled" in message
                or "local generation cancelled" in message
            )
            if expected_cancellation:
                self.logger.info(
                    "Provider generation cancelled for live steering: %s",
                    error,
                )
                return AgentResponse("")
            self.logger.exception("Provider generation failed")
            chain = getattr(self.provider, "chain", None)
            chain_note = (
                f"\nTried providers: {' -> '.join(chain)}"
                if chain
                else ""
            )
            return AgentResponse(
                "Sophyane could not reach any working LLM provider.\n"
                f"{error}{chain_note}\n"
                "Fix: configure a llama.cpp GGUF runtime and start llama-server, "
                "then run /doctor."
            )
        return AgentResponse(text)


    def _summarize_tool(
        self,
        request: str,
        output: str,
        tool_name: str,
    ) -> AgentResponse:
        # Bound potentially enormous local tool/project dumps before model summarization or fallback propagation.
        output = _bounded_tool_context(output)
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


# SOPHYANE_TOOL_SUMMARY_BOUND_V1
def _bounded_tool_context(
    value: object,
    *,
    limit: int = 24000,
) -> str:
    """Bound tool output before it can re-enter model/action context."""
    text = str(
        value
        if value is not None
        else ""
    )

    if len(text) <= limit:
        return text

    head = max(
        1000,
        int(limit * 0.70),
    )

    tail = max(
        1000,
        limit - head,
    )

    omitted = (
        len(text)
        - head
        - tail
    )

    return (
        text[:head]
        + "\n\n"
        + (
            "[SOPHYANE TOOL OUTPUT TRUNCATED: "
            f"{omitted} characters omitted]"
        )
        + "\n\n"
        + text[-tail:]
    )
