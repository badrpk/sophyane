"""LLM-assisted intent refinement with explicit user approval before execution."""
from __future__ import annotations

import json
from typing import Any

from sophyane.runtime_semantic_instruction import apply_live_instruction


def _refinement_prompt(message: str, *, has_project: bool) -> str:
    project_state = "an active project exists" if has_project else "no active project exists"
    return (
        "Refine the user's request before any action. Correct spelling, recover likely missing intent, "
        "and make the request precise without adding unrelated features. Decide whether it is an execution "
        "request that should build/edit/run a project, or ordinary chat/writing that should be answered directly. "
        "Do NOT execute, write files, or give the final answer yet.\n"
        "Return the normal Sophyane JSON plan schema with these exact conventions:\n"
        "- objective: the complete corrected and refined user request only\n"
        "- selection_reason: exactly route=execution, route=continue_project, or route=chat\n"
        "- action: {\"type\":\"respond\",\"message\":<same refined request>}\n"
        "- success_criteria may contain concise assumptions or missing details\n"
        f"Session state: {project_state}.\n"
        f"RAW USER REQUEST: {message}"
    )


def _parse_refinement(raw: str, original: str, *, has_project: bool, tui_v2: Any) -> tuple[str, str, list[str]]:
    plan = tui_v2.extract_plan(raw)
    refined = ""
    reason = ""
    assumptions: list[str] = []
    if isinstance(plan, dict):
        refined = str(plan.get("objective") or "").strip()
        reason = str(plan.get("selection_reason") or "").strip().lower()
        criteria = plan.get("success_criteria")
        if isinstance(criteria, list):
            assumptions = [str(item).strip() for item in criteria if str(item).strip()][:5]
        action = plan.get("action")
        if not refined and isinstance(action, dict):
            refined = str(action.get("message") or action.get("content") or "").strip()
    if not refined:
        refined = raw.strip() or original.strip()

    if "continue_project" in reason:
        route = "continue_project" if has_project else "execution"
    elif "execution" in reason:
        route = "execution"
    elif "chat" in reason:
        route = "chat"
    else:
        continuing = tui_v2._project_continuation(refined, has_project)
        route = "continue_project" if continuing else ("execution" if tui_v2._execution_requested(refined) else "chat")
    return route, refined, assumptions


def _confirm_refinement(self: Any, original: str, *, has_project: bool, tui_v2: Any) -> tuple[str, str] | None:
    candidate = original
    while True:
        self.progress("Refining intent with the language model")
        try:
            response = self.call_provider(_refinement_prompt(candidate, has_project=has_project))
            raw = getattr(response, "text", str(response))
            route, refined, assumptions = _parse_refinement(raw, candidate, has_project=has_project, tui_v2=tui_v2)
        except Exception as error:  # noqa: BLE001
            self.progress(f"Intent refinement unavailable; using deterministic fallback: {type(error).__name__}")
            continuing = tui_v2._project_continuation(candidate, has_project)
            route = "continue_project" if continuing else ("execution" if tui_v2._execution_requested(candidate) else "chat")
            refined, assumptions = candidate, []

        if route == "chat":
            return route, refined

        print("\nI understood your request as:\n", flush=True)
        print(refined, flush=True)
        if assumptions:
            print("\nAssumptions / acceptance points:", flush=True)
            for item in assumptions:
                print(f"- {item}", flush=True)
        print(
            "\n1. Approve and continue\n"
            "2. Edit the request and refine again\n"
            "3. Continue immediately with this refined request\n"
            "0. Cancel\n"
                "You may also type a new instruction in natural language.",
            flush=True,
        )
        try:
            choice = input("Choose [1-3, default 1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if choice in {"", "1", "3"}:
            return route, refined
        if choice == "0":
            return None
        if choice == "2":
            try:
                edited = input("Edit request: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            if edited:
                candidate = edited
            continue
        # Natural-language input is a new semantic instruction,
        # not an invalid menu choice.
        if choice:
            candidate = apply_live_instruction(
                self,
                refined,
                choice,
            )
            print(
                "\nNew instruction understood. "
                "Refining the authoritative request again.",
                flush=True,
            )
            continue

        print(
            "Please choose a menu number or type a new instruction.",
            flush=True,
        )


def install_intent_refinement() -> None:
    from sophyane import tui_v2

    if getattr(tui_v2.ObservableTUI, "_intent_refinement_installed", False):
        return

    def run(self: Any) -> int:
        print(f"\n◆ Sophyane {tui_v2.__version__}")
        print(f"provider {self.config.get('provider')}  model {self.config.get('model')}")
        print(
            "Requests are refined by the language model before execution. "
            "Approve, edit, or cancel the refined request. /new starts a fresh project. "
            "/inspect shows raw plan and files. /quit exits.\n"
        )
        while True:
            try:
                message = tui_v2._clean_message(self.read_prompt("❯ "))
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
            quick = tui_v2._simple_chat_reply(message)
            if quick is not None:
                self.emit("Sophyane", quick)
                continue

            has_project = bool(self.active_request and self.active_workspace)
            refined_result = _confirm_refinement(self, message, has_project=has_project, tui_v2=tui_v2)
            if refined_result is None:
                self.emit("system", "Request cancelled; no files were changed.")
                continue
            route, refined_message = refined_result
            continuing = route == "continue_project"
            executable = route in {"execution", "continue_project"}
            if tui_v2._explicit_new_benchmark(refined_message):
                continuing = False
            context_message = self._context_prompt(refined_message, continuing=continuing)

            if executable:
                self.last_mode = "execution"
                if continuing:
                    self.project_requirements.append(refined_message)
                    request_for_model = (
                        f"Continue existing project. {context_message}\n"
                        "Return one compact JSON action using relative paths. Modify existing files; do not start over."
                    )
                else:
                    self.active_request = refined_message
                    self.project_requirements = [refined_message]
                    request_for_model = (
                        f"Execute: {context_message}\n"
                        "Return one compact JSON action or artifact. Use relative paths and verify real output."
                    )
            else:
                self.last_mode = "chat"
                request_for_model = f"Answer directly. No JSON or tool action.\n{context_message}"

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
                self.progress("Approved request received; entering adaptive runtime")
                try:
                    workspace = self._workspace_for(continuing)
                    text = tui_v2.run_structured_loop(
                        initial_text=text,
                        original_request=refined_message,
                        ask=lambda prompt: self.call_provider(prompt),
                        workspace=workspace,
                        max_steps=8 if self.small_local else 16,
                        progress=self.progress,
                    )
                except Exception as error:  # noqa: BLE001
                    text = f"Execution loop failed safely: {error}"
            else:
                text = tui_v2._render_nonexecuting_response(text)

            self.history.extend([("user", message[:300]), ("assistant", text[:500])])
            self.history = self.history[-4:]
            self.emit("Sophyane", text)

    tui_v2.ObservableTUI.run = run
    tui_v2.ObservableTUI._intent_refinement_installed = True
