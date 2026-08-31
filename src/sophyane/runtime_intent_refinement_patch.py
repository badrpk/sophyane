"""LLM-assisted intent refinement with explicit user approval before execution."""
from __future__ import annotations

from typing import Any

from sophyane.runtime_semantic_instruction import apply_live_instruction


def _refinement_prompt(message: str, *, has_project: bool) -> str:
    project_state = "an active project exists" if has_project else "no active project exists"
    return (
        "Refine the user's request before any action. Correct spelling, recover likely missing intent, "
        "and make the request precise without adding unrelated features. Decide whether it is an execution "
        "request that should build/edit/run a software project, or ordinary chat/writing/media creation that should be answered directly. ""A standalone request to create a portrait, image, illustration, drawing, logo, poster, wallpaper, photograph, avatar, thumbnail, painting, meme, or other visual is route=chat. It is route=execution only when the user explicitly requests code, an app, website, HTML, SVG, canvas, script, generator, editor, API, repository, or project files. "
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
    # Deterministic routing has final authority over the model's
    # route label. Generative models often interpret verbs such as "make",
    # "create", and "design" as software execution even when the requested
    # result is only an image or other visual.
    if tui_v2._pure_media_request(original) or tui_v2._pure_media_request(refined):
        route = "chat"

    return route, refined, assumptions


def _confirm_refinement(self: Any, original: str, *, has_project: bool, tui_v2: Any) -> tuple[str, str] | None:
    clean = str(original or "").strip()

    # Standalone media requests are direct-response tasks. Do not ask a
    # language model whether they are software builds and do not show the
    # execution approval menu.
    if tui_v2._pure_media_request(clean):
        self.progress("Media request detected; using direct response route")
        return "chat", clean

    # Ordinary informational chat has a deterministic route. Sending it
    # through intent refinement creates an unnecessary provider call and
    # allows internal SLI semantic JSON to leak into the user-facing turn.
    continuing = tui_v2._project_continuation(clean, has_project)
    executable = tui_v2._execution_requested(clean)

    if not continuing and not executable:
        return "chat", clean

    candidate = clean
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

            # SOPHYANE_NIFDU_ACTIVE_PATH_STATE_V1
            #
            # Runtime execution code expects active_workspace to expose
            # pathlib.Path methods such as exists(). Keep that invariant
            # even when older patches stored a string.
            from pathlib import Path as _SophyaneActivePath

            if (
                self.active_workspace
                and not isinstance(
                    self.active_workspace,
                    _SophyaneActivePath,
                )
            ):
                self.active_workspace = _SophyaneActivePath(
                    self.active_workspace
                )

            # SOPHYANE_NIFDU_EFFECTIVE_LOCAL_GROUNDING_V1
            #
            # install_intent_refinement() replaces ObservableTUI.run()
            # completely. Therefore Option-4/NIFDU filesystem reads and
            # discovery must be intercepted HERE at the effective original
            # user-request boundary, before preflight, refinement, simple
            # chat routing or any provider call.
            import os as _nifdu_ground_os

            if (
                _nifdu_ground_os.environ.get(
                    "SOPHYANE_SESSION_MODE",
                    "",
                ).strip().lower()
                == "nifdu_llm"
            ):
                from pathlib import Path as _NifduGroundPath

                from sophyane.nifdu_guarded_execution import (
                    grounded_nifdu_file_followup,
                    grounded_nifdu_largest_file,
                    grounded_nifdu_named_file_discovery,
                    grounded_nifdu_python_file_read,
                    requested_python_read_filename,
                )

                if not hasattr(
                    self,
                    "_nifdu_grounded_file",
                ):
                    self._nifdu_grounded_file = None

                if not hasattr(
                    self,
                    "_nifdu_grounded_matches",
                ):
                    self._nifdu_grounded_matches = []

                # SOPHYANE_NIFDU_EFFECTIVE_LARGEST_FILE_DISPATCH_V1
                _nifdu_largest = grounded_nifdu_largest_file(
                    message,
                    workspace=_NifduGroundPath.cwd().resolve(),
                )

                if _nifdu_largest is not None:
                    self.last_mode = "chat"
                    self.last_raw = _nifdu_largest

                    self.history.extend(
                        [
                            ("user", message[:300]),
                            ("assistant", _nifdu_largest[:500]),
                        ]
                    )
                    self.history = self.history[-4:]

                    self.emit(
                        "Sophyane",
                        _nifdu_largest,
                    )
                    continue

                # Device/local-root discovery is deterministic and never
                # delegated to ChatGPT.
                _nifdu_discovery = (
                    grounded_nifdu_named_file_discovery(
                        message
                    )
                )

                if _nifdu_discovery is not None:
                    _nifdu_paths = list(
                        _nifdu_discovery.get(
                            "paths",
                            [],
                        )
                    )

                    self._nifdu_grounded_matches = (
                        _nifdu_paths
                    )

                    self._nifdu_grounded_file = (
                        _nifdu_paths[0]
                        if len(_nifdu_paths) == 1
                        else None
                    )

                    self.last_mode = "chat"
                    self.last_raw = str(
                        _nifdu_discovery[
                            "message"
                        ]
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

                    self.history = (
                        self.history[-4:]
                    )

                    self.emit(
                        "Sophyane",
                        self.last_raw,
                    )

                    continue

                # Follow-ups such as "what is content of this file?" are
                # resolved only against runtime-grounded state. Multiple
                # matches remain explicitly ambiguous.
                _nifdu_followup = (
                    grounded_nifdu_file_followup(
                        message,
                        active_file=(
                            self._nifdu_grounded_file
                        ),
                        candidate_paths=(
                            self._nifdu_grounded_matches
                        ),
                    )
                )

                if _nifdu_followup is not None:
                    self.last_mode = "chat"
                    self.last_raw = (
                        _nifdu_followup
                    )

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

                    self.history = (
                        self.history[-4:]
                    )

                    self.emit(
                        "Sophyane",
                        _nifdu_followup,
                    )

                    continue

                # Explicit workspace-relative reads, e.g.
                # "code of yaqeen.py", are grounded in cwd and never
                # answered from model memory.
                _nifdu_grounded_read = (
                    grounded_nifdu_python_file_read(
                        message,
                        workspace=(
                            _NifduGroundPath.cwd().resolve()
                        ),
                    )
                )

                if _nifdu_grounded_read is not None:
                    _nifdu_read_name = (
                        requested_python_read_filename(
                            message
                        )
                    )

                    if _nifdu_read_name is not None:
                        _nifdu_read_path = (
                            _NifduGroundPath.cwd().resolve()
                            / _nifdu_read_name
                        )

                        if _nifdu_read_path.is_file():
                            self._nifdu_grounded_file = (
                                _nifdu_read_path.resolve()
                            )

                            self._nifdu_grounded_matches = [
                                self._nifdu_grounded_file
                            ]

                        else:
                            self._nifdu_grounded_file = None
                            self._nifdu_grounded_matches = []

                    self.last_mode = "chat"
                    self.last_raw = (
                        _nifdu_grounded_read
                    )

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

                    self.history = (
                        self.history[-4:]
                    )

                    self.emit(
                        "Sophyane",
                        _nifdu_grounded_read,
                    )

                    continue


            # SOPHYANE_AUTHORITATIVE_OBJECTIVE_PREFLIGHT
            # Consume the ORIGINAL user request before adaptive dispatch,
            # intent refinement, SLI acquisition, races or provider calls.
            from sophyane.objective_preflight import (
                preflight_original_request,
            )

            preflight_reply = preflight_original_request(
                message
            )

            if preflight_reply is not None:
                self.emit(
                    "Sophyane",
                    str(preflight_reply),
                )

                self.active_request = ""
                continue


            # SOPHYANE_NIFDU_NATIVE_EXECUTION_HANDOFF_V1
            #
            # Option 4 -> NIFDU uses ChatGPT only as the model/provider.
            # Once the original user request is classified as executable,
            # the same native Sophyane execution_runtime used by every
            # other provider owns:
            #
            #   action parsing
            #   workspace mutation
            #   safe command execution
            #   verification
            #   browser preview/opening
            #   continuation
            #
            # Do not route through NIFDU-specific WRITE_FILE, replacement,
            # process-launch or browser-launch primitives.
            import os as _nifdu_native_os

            if (
                _nifdu_native_os.environ.get(
                    "SOPHYANE_SESSION_MODE",
                    "",
                ).strip().lower()
                == "nifdu_llm"
                and tui_v2._execution_requested(
                    message
                )
            ):
                from pathlib import Path as _NifduNativePath

                _nifdu_workspace = (
                    _NifduNativePath.cwd().resolve()
                )

                # pathlib.Path is the native execution-runtime contract.
                # Never persist a string workspace into continuation state.
                self.active_workspace = (
                    _nifdu_workspace
                )

                _nifdu_continuing = bool(
                    self.active_request
                    and self.project_requirements
                )

                if _nifdu_continuing:
                    self.project_requirements.append(
                        message
                    )
                else:
                    self.active_request = message
                    self.project_requirements = [
                        message
                    ]

                self.last_mode = "execution"

                _nifdu_native_prompt = (
                    "Execute the user's request using Sophyane's "
                    "existing structured action runtime.\n\n"
                    "Return ONLY the next concrete executable Sophyane "
                    "action. Do not return a completion/result envelope.\n\n"
                    "Use existing action schema such as:\n"
                    '{"type":"write_file","path":"relative-file",'
                    '"content":"complete content"}\n'
                    '{"type":"append_file","path":"relative-file",'
                    '"content":"content"}\n'
                    '{"type":"run","command":"concrete command"}\n\n'
                    "Use relative workspace paths only.\n"
                    "Do not claim a file, process, test, server or browser "
                    "operation succeeded unless Sophyane executes and "
                    "verifies it.\n"
                    "Do not return WRITE_FILE / END_WRITE_FILE wrappers.\n"
                    "Do not return shell commands as prose.\n\n"
                    "AUTHORITATIVE USER REQUEST:\n"
                    + message
                )

                # SOPHYANE_NIFDU_GUARDED_FAST_PATH_V2
                #
                # execute_nifdu_file_request() is itself the guarded executor.
                # Its real contract is:
                #
                #   execute_nifdu_file_request(
                #       request,
                #       workspace=Path(...),
                #   ) -> Path | None
                #
                # A returned Path means NIFDU proposed the contents and
                # Sophyane parsed, validated and performed the local write.
                # None means this request is not handled by that capability.
                try:
                    from sophyane.nifdu_guarded_execution import (
                        NifduExecutionError as _NifduFastPathError,
                        execute_nifdu_file_continuation,
                        execute_nifdu_file_request,
                        requested_python_filename,
                    )

                    _nifdu_guarded_existing_update = False

                    try:
                        _nifdu_guarded_path = (
                            execute_nifdu_file_request(
                                message,
                                workspace=_nifdu_workspace,
                            )
                        )

                    except _NifduFastPathError as _nifdu_fast_error:
                        _nifdu_existing_name = (
                            requested_python_filename(
                                message
                            )
                        )

                        _nifdu_existing_target = (
                            (
                                _nifdu_workspace
                                / _nifdu_existing_name
                            ).resolve()
                            if _nifdu_existing_name
                            else None
                        )

                        _nifdu_existing_update = bool(
                            _nifdu_existing_target is not None
                            and _nifdu_existing_target.is_file()
                            and str(
                                _nifdu_fast_error
                            ).startswith(
                                "target already exists:"
                            )
                        )

                        if not _nifdu_existing_update:
                            raise

                        try:
                            _nifdu_existing_target.relative_to(
                                _nifdu_workspace
                            )
                        except ValueError as _nifdu_escape_error:
                            raise _NifduFastPathError(
                                "existing target escapes workspace"
                            ) from _nifdu_escape_error

                        # SOPHYANE_NIFDU_EXISTING_NAMED_FILE_UPDATE_V1
                        #
                        # WRITE_FILE remains strictly create-only.
                        # An explicitly named existing Python target instead
                        # uses the already-authoritative guarded REPLACE_FILE
                        # continuation contract.
                        _nifdu_guarded_path = (
                            execute_nifdu_file_continuation(
                                (
                                    "Update the existing Python file "
                                    + _nifdu_existing_name
                                    + " so that it satisfies this exact "
                                    "authoritative request:\n"
                                    + message
                                ),
                                workspace=_nifdu_workspace,
                                active_file=_nifdu_existing_target,
                            )
                        )

                        if _nifdu_guarded_path is None:
                            raise _NifduFastPathError(
                                "guarded existing-file continuation "
                                "did not accept the request"
                            )

                        _nifdu_guarded_existing_update = True

                except Exception as _nifdu_guarded_error:  # noqa: BLE001
                    self.progress(
                        "Guarded NIFDU file path did not complete: "
                        f"{type(_nifdu_guarded_error).__name__}: "
                        f"{_nifdu_guarded_error}"
                    )
                    _nifdu_guarded_path = None
                    _nifdu_guarded_existing_update = False

                if _nifdu_guarded_path is not None:
                    from pathlib import Path as _NifduResultPath
                    # SOPHYANE_NIFDU_JSON_IMPORT_FREE_RENDER_V1
                    #
                    # Reuse tui_v2's existing json module; do not add
                    # a json import to this intent-wrapper module.

                    _nifdu_guarded_path = (
                        _NifduResultPath(
                            _nifdu_guarded_path
                        ).resolve()
                    )

                    _nifdu_workspace_resolved = (
                        _NifduResultPath(
                            _nifdu_workspace
                        ).resolve()
                    )

                    try:
                        _nifdu_relative = (
                            _nifdu_guarded_path.relative_to(
                                _nifdu_workspace_resolved
                            )
                        )
                    except ValueError:
                        raise RuntimeError(
                            "Guarded NIFDU returned a path "
                            "outside the active workspace"
                        )

                    if not _nifdu_guarded_path.is_file():
                        raise RuntimeError(
                            "Guarded NIFDU reported a file "
                            "that does not exist"
                        )

                    _nifdu_result_payload = {
                        "handled": True,
                        "ok": True,
                        "capability": (
                            "nifdu.guarded_python_file_write"
                        ),
                        "summary": (
                            (
                                "Updated and validated "
                                if _nifdu_guarded_existing_update
                                else "Created and validated "
                            )
                            + f"{_nifdu_relative}."
                        ),
                        "workspace": str(
                            _nifdu_workspace_resolved
                        ),
                        "files": [
                            str(_nifdu_relative)
                        ],
                        "evidence": [
                            {
                                "path": str(
                                    _nifdu_guarded_path
                                ),
                                "exists": True,
                                "bytes": (
                                    _nifdu_guarded_path
                                    .stat()
                                    .st_size
                                ),
                            }
                        ],
                        "error": "",
                    }

                    _nifdu_result_text = (
                        tui_v2.json.dumps(
                            _nifdu_result_payload,
                            ensure_ascii=False,
                            indent=2,
                        )
                    )

                    self.last_raw = (
                        _nifdu_result_text
                    )

                    self.history.extend(
                        [
                            (
                                "user",
                                message[:300],
                            ),
                            (
                                "assistant",
                                _nifdu_result_text[:500],
                            ),
                        ]
                    )

                    self.history = (
                        self.history[-4:]
                    )

                    self.emit(
                        "Sophyane",
                        _nifdu_result_text,
                    )

                    continue

                self.progress(
                    "Planning with NIFDU; native Sophyane runtime "
                    "owns execution"
                )

                try:
                    _nifdu_initial = self.call_provider(
                        _nifdu_native_prompt
                    )

                    _nifdu_initial_text = getattr(
                        _nifdu_initial,
                        "text",
                        str(_nifdu_initial),
                    )

                    self.last_raw = (
                        _nifdu_initial_text
                    )

                    _nifdu_result = (
                        tui_v2.run_structured_loop(
                            initial_text=(
                                _nifdu_initial_text
                            ),
                            original_request=message,
                            ask=lambda prompt: (
                                self.call_provider(
                                    prompt
                                )
                            ),
                            workspace=(
                                _nifdu_workspace
                            ),
                            max_steps=(
                                8
                                if self.small_local
                                else 16
                            ),
                            progress=self.progress,
                        )
                    )

                except Exception as error:  # noqa: BLE001
                    self.emit(
                        "system",
                        (
                            "Native Sophyane execution failed safely: "
                            + f"{type(error).__name__}: {error}"
                        ),
                    )

                    continue

                self.history.extend(
                    [
                        (
                            "user",
                            message[:300],
                        ),
                        (
                            "assistant",
                            str(_nifdu_result)[:500],
                        ),
                    ]
                )

                self.history = (
                    self.history[-4:]
                )

                self.emit(
                    "Sophyane",
                    str(_nifdu_result),
                )

                continue

                        # SOPHYANE_NIFDU_GUARDED_BROWSER_LAUNCH_V1
            #
            # Running/opening is a distinct action from editing.
            # Handle it before NIFDU continuation mutation so a request
            # such as "run yaqeen.py in browser" cannot rewrite the file.
            import os as _nifdu_launch_os

            if (
                _nifdu_launch_os.environ.get(
                    "SOPHYANE_SESSION_MODE",
                    "",
                ).strip().lower()
                == "nifdu_llm"
            ):
                from pathlib import Path as _NifduLaunchPath

                from sophyane.nifdu_guarded_execution import (
                    NifduExecutionError as _NifduLaunchError,
                    launch_guarded_browser_python,
                )

                try:
                    _nifdu_launch_result = (
                        launch_guarded_browser_python(
                            message,
                            workspace=_NifduLaunchPath.cwd().resolve(),
                        )
                    )

                except _NifduLaunchError as error:
                    self.emit(
                        "system",
                        "Guarded browser launch refused: "
                        + str(error),
                    )
                    continue

                if _nifdu_launch_result is not None:
                    _nifdu_launch_target, _nifdu_launch_pid = (
                        _nifdu_launch_result
                    )

                    self.emit(
                        "Sophyane",
                        (
                            "Started "
                            + _nifdu_launch_target.name
                            + " through Sophyane's guarded "
                            "execution authority.\n\n"
                            + "PID: "
                            + str(_nifdu_launch_pid)
                        ),
                    )

                    continue

# SOPHYANE_NIFDU_DETERMINISTIC_EMPTY_CREATE_V1
            #
            # A bare request such as "create a file yaqeen.py"
            # needs no LLM intelligence. Sophyane can safely create
            # the empty file itself and remember it as the active
            # continuation target.
            import os as _nifdu_empty_os

            if (
                _nifdu_empty_os.environ.get(
                    "SOPHYANE_SESSION_MODE",
                    "",
                ).strip().lower()
                == "nifdu_llm"
            ):
                from pathlib import Path as _NifduEmptyPath

                from sophyane.nifdu_guarded_execution import (
                    NifduExecutionError as _NifduEmptyError,
                    deterministic_empty_python_create,
                )

                try:
                    _nifdu_empty_target = (
                        deterministic_empty_python_create(
                            message,
                            workspace=_NifduEmptyPath.cwd().resolve(),
                        )
                    )
                except _NifduEmptyError as error:
                    self.emit(
                        "system",
                        "NIFDU deterministic create rejected: "
                        + str(error),
                    )
                    continue

                if _nifdu_empty_target is not None:
                    self.active_workspace = (
                        _nifdu_empty_target.parent
                    )

                    self.active_request = message

                    self.project_requirements = [
                        message
                    ]

                    # Explicit active file for guarded continuation.
                    self._nifdu_active_file = (
                        _nifdu_empty_target
                    )

                    self.last_raw = (
                        "Created empty file natively: "
                        + str(_nifdu_empty_target)
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
                            + _nifdu_empty_target.name
                            + " directly through Sophyane's "
                            "guarded filesystem authority.\n\n"
                            + "Path: "
                            + str(_nifdu_empty_target)
                        ),
                    )

                    continue

            # SOPHYANE_NIFDU_EFFECTIVE_RUN_GUARDED_EXECUTION_V1
            #
            # install_intent_refinement() replaces ObservableTUI.run()
            # completely. Therefore explicit Option 4 -> 2 guarded file
            # execution must live at this effective user-request boundary,
            # before intent refinement can rewrite the request into a
            # compiled work packet.
            import os as _nifdu_effective_os

            if (
                _nifdu_effective_os.environ.get(
                    "SOPHYANE_SESSION_MODE",
                    "",
                ).strip().lower()
                == "nifdu_llm"
            ):
                from pathlib import Path as _NifduEffectivePath

                from sophyane.nifdu_guarded_execution import (
                    NifduExecutionError,
                    execute_nifdu_file_request,
                )

                try:
                    _nifdu_effective_target = (
                        execute_nifdu_file_request(
                            message,
                            workspace=(
                                _NifduEffectivePath.cwd().resolve()
                            ),
                        )
                    )

                except NifduExecutionError as error:
                    self.emit(
                        "system",
                        (
                            "NIFDU proposal rejected by "
                            "Sophyane's guarded executor: "
                            + str(error)
                        ),
                    )
                    continue

                except Exception as error:  # noqa: BLE001
                    self.emit(
                        "system",
                        (
                            "NIFDU guarded execution failed safely: "
                            f"{type(error).__name__}: {error}"
                        ),
                    )
                    continue

                if _nifdu_effective_target is not None:
                    _nifdu_effective_content = (
                        _nifdu_effective_target.read_text(
                            encoding="utf-8",
                        )
                    )

                    self.last_mode = "execution"
                    self.last_raw = (
                        "Created guarded NIFDU file: "
                        + str(
                            _nifdu_effective_target
                        )
                    )

                    self.active_request = message
                    self.active_workspace = str(
                        _NifduEffectivePath.cwd().resolve()
                    )

                    self.project_requirements = [
                        message
                    ]

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
                            + _nifdu_effective_target.name
                            + " through the guarded NIFDU "
                            "execution path.\n\n"
                            + "Path: "
                            + str(
                                _nifdu_effective_target
                            )
                            + "\n"
                            + "Contents:\n"
                            + _nifdu_effective_content.rstrip(
                                "\n"
                            )
                        ),
                    )

                    # Remember guarded execution state using Path
                    # objects so future continuations such as "edit it"
                    # can deterministically resolve to this exact file.
                    self.active_workspace = (
                        _nifdu_effective_target.parent
                    )

                    self._nifdu_active_file = (
                        _nifdu_effective_target
                    )

                    self.active_request = message

                    self.project_requirements = [
                        message
                    ]

                    continue

            # SOPHYANE_NIFDU_GUARDED_CONTINUATION_DISPATCH_V1
            #
            # A supported continuation targeting the remembered Python
            # file must remain in the guarded NIFDU path. Do not send it
            # through generic intent refinement or the legacy structured
            # execution loop.
            if (
                _nifdu_effective_os.environ.get(
                    "SOPHYANE_SESSION_MODE",
                    "",
                ).strip().lower()
                == "nifdu_llm"
            ):
                from sophyane.nifdu_guarded_execution import (
                    execute_nifdu_file_continuation,
                    is_nifdu_file_continuation_request,
                )

                _nifdu_active_file = getattr(
                    self,
                    "_nifdu_active_file",
                    None,
                )

                _nifdu_workspace = (
                    _NifduEffectivePath(
                        self.active_workspace
                    ).resolve()
                    if self.active_workspace
                    else _NifduEffectivePath.cwd().resolve()
                )

                if is_nifdu_file_continuation_request(
                    message,
                    active_file=_nifdu_active_file,
                    workspace=_nifdu_workspace,
                ):
                    try:
                        _nifdu_updated = (
                            execute_nifdu_file_continuation(
                                message,
                                workspace=_nifdu_workspace,
                                active_file=_nifdu_active_file,
                            )
                        )

                    except NifduExecutionError as error:
                        self.emit(
                            "system",
                            "NIFDU continuation rejected by "
                            "Sophyane's guarded executor: "
                            f"{error}",
                        )
                        continue

                    if _nifdu_updated is not None:
                        self.active_workspace = (
                            _nifdu_updated.parent
                        )

                        self._nifdu_active_file = (
                            _nifdu_updated
                        )

                        self.active_request = (
                            str(
                                self.active_request
                                or ""
                            ).strip()
                            + "\n"
                            + message
                        ).strip()

                        self.project_requirements.append(
                            message
                        )

                        _nifdu_updated_content = (
                            _nifdu_updated.read_text(
                                encoding="utf-8",
                            )
                        )

                        self.last_raw = (
                            "Updated guarded NIFDU file: "
                            + str(_nifdu_updated)
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
                                "Updated "
                                + _nifdu_updated.name
                                + " through the guarded NIFDU "
                                "continuation path.\n\n"
                                + "Path: "
                                + str(_nifdu_updated)
                                + "\n"
                                + "Contents:\n"
                                + _nifdu_updated_content.rstrip("\n")
                            ),
                        )

                        continue

            # SOPHYANE_AUTO_EFFECTIVE_TUI_AUTHORITY_V1
            #
            # install_intent_refinement() replaces ObservableTUI.run at
            # runtime. Therefore Auto authority must exist in this effective
            # run() as well as in the base TUI implementation.
            #
            # A handled top-level request is terminal at this boundary:
            # refinement, simple-chat routing, and low-level provider access
            # must not run afterward.
            dispatch = getattr(
                self,
                "dispatch_user_request",
                None,
            )
            if callable(dispatch):
                response = dispatch(message)

                # Auto dispatch returns the completed user-facing response,
                # not merely a boolean handled flag.
                if response is not None:
                    text = getattr(
                        response,
                        "text",
                        str(response),
                    )

                    self.last_raw = text

                    self.history.extend([
                        ("user", message[:300]),
                        ("assistant", text[:500]),
                    ])
                    self.history = self.history[-4:]

                    self.emit(
                        "Sophyane",
                        text,
                    )

                    continue

            # SOPHYANE_ACTIVE_NATIVE_CHOICE_DISPATCH
            normalized_choice = " ".join(message.casefold().split())

            if (
                getattr(self, "_native_choice_context", "") == "saas_agents"
                and normalized_choice
                in {"1", "2", "3", "4", "5", "6", "7"}
            ):
                choices = {
                    "1": (
                        "SophyaneAgent",
                        "Public customer-facing API and conversational agent.",
                    ),
                    "2": (
                        "Multi-agent supervisor",
                        "Routes complex requests, creates task graphs, launches "
                        "specialists, enforces concurrency and retry limits, "
                        "and coordinates completion.",
                    ),
                    "3": (
                        "Specialist workers",
                        "Perform domain-specific services such as coding, "
                        "support, analysis, document processing and automation.",
                    ),
                    "4": (
                        "Executor worker",
                        "Runs validated tools and deterministic operations.",
                    ),
                    "5": (
                        "Reviewer worker",
                        "Validates, compares and merges worker results before "
                        "delivery to the customer.",
                    ),
                    "6": (
                        "Native workers",
                        "Provide fast and inexpensive local deterministic "
                        "capabilities without spending LLM tokens.",
                    ),
                    "7": (
                        "LLM provider worker",
                        "Provides generative reasoning through Gemini, OpenAI "
                        "or another configured model provider.",
                    ),
                }

                name, purpose = choices[normalized_choice]
                self._native_choice_selected = normalized_choice

                self.emit(
                    "Sophyane",
                    f"Selected option {normalized_choice}: {name}\n"
                    f"{purpose}\n\n"
                    "Type `proceed` to continue with this option, "
                    "`options` to show the numbered list again, or enter "
                    "another number.",
                )
                continue

            if (
                getattr(self, "_native_choice_context", "") == "saas_agents"
                and normalized_choice
                in {
                    "options",
                    "show options",
                    "show numbering",
                    "show numbers",
                    "give above numbering",
                    "give above numbering and option i will select to proceed",
                }
            ):
                self.emit(
                    "Sophyane",
                    "Select a SaaS component:\n"
                    "1. SophyaneAgent — public customer-facing API/chat agent\n"
                    "2. Multi-agent supervisor — orchestration and routing\n"
                    "3. Specialist workers — domain-specific services\n"
                    "4. Executor worker — validated tool execution\n"
                    "5. Reviewer worker — output validation and merging\n"
                    "6. Native workers — fast deterministic local services\n"
                    "7. LLM provider worker — generative model reasoning\n\n"
                    "Enter a number from 1 to 7.",
                )
                continue

            if (
                getattr(self, "_native_choice_context", "") == "saas_agents"
                and normalized_choice in {"proceed", "continue", "go ahead", "next"}
            ):
                selected = str(
                    getattr(self, "_native_choice_selected", "") or ""
                ).strip()

                choices = {
                    "1": (
                        "SophyaneAgent",
                        "Expose SophyaneAgent through an authenticated HTTP API. "
                        "Add tenant isolation, request validation, quotas, "
                        "streaming responses, audit logs and usage accounting.",
                    ),
                    "2": (
                        "Multi-agent supervisor",
                        "Place the supervisor behind SophyaneAgent. It should "
                        "classify requests, create bounded task graphs, assign "
                        "specialists, enforce worker and retry limits, collect "
                        "results and send them to the reviewer.",
                    ),
                    "3": (
                        "Specialist workers",
                        "Create a registry of service-specific worker roles with "
                        "declared capabilities, permissions, timeouts and token "
                        "budgets.",
                    ),
                    "4": (
                        "Executor worker",
                        "Connect the executor to validated tools with tenant "
                        "permissions, idempotency controls, timeouts and an "
                        "immutable audit trail.",
                    ),
                    "5": (
                        "Reviewer worker",
                        "Require reviewer validation for worker output, factual "
                        "grounding, policy checks and final response merging.",
                    ),
                    "6": (
                        "Native workers",
                        "Expose deterministic capabilities first and invoke an "
                        "LLM only when native execution cannot satisfy the "
                        "request.",
                    ),
                    "7": (
                        "LLM provider worker",
                        "Create a provider service behind the supervisor with "
                        "model routing, per-tenant API keys, token budgets, "
                        "timeouts, fallback providers and timestamped usage "
                        "accounting.",
                    ),
                }

                if selected not in choices:
                    self.emit(
                        "Sophyane",
                        "Select an option from 1 to 7 before proceeding.",
                    )
                    continue

                name, implementation = choices[selected]

                self.emit(
                    "Sophyane",
                    f"Proceeding with option {selected}: {name}\n\n"
                    f"{implementation}\n\n"
                    "Recommended SaaS flow:\n"
                    "Customer/API → SophyaneAgent → Supervisor → "
                    "Selected worker → Reviewer → Response",
                )

                self._native_choice_context = ""
                self._native_choice_selected = ""
                continue

            quick = tui_v2._simple_chat_reply(message)
            if quick is not None:
                # SOPHYANE_ACTIVE_NATIVE_CHOICE_STORE
                if (
                    "Recommended Sophyane architecture for SaaS services:"
                    in quick
                ):
                    self._native_choice_context = "saas_agents"
                    self._native_choice_selected = ""

                    if "Enter a number from 1 to 7." not in quick:
                        quick = (
                            quick
                            + "\n\nSelect an option by entering a number "
                            "from 1 to 7."
                        )

                self.emit("Sophyane", quick)
                continue

            has_project = bool(self.active_request and self.active_workspace)

            # SOPHYANE_DIRECT_CHAT_REFINEMENT_BYPASS_V1
            #
            # Ordinary deterministic chat does not need a first provider
            # generation merely to rediscover that it is chat. That duplicate
            # refinement call wastes latency/tokens and can cause a small model
            # to answer the routing prompt instead of the user's question.
            #
            # Execution/continuation requests retain the existing refinement
            # and confirmation authority unchanged.
            try:
                from sophyane.runtime_sli_brain import (
                    _route as _sli_pre_refinement_route,
                )

                pre_refinement_route = _sli_pre_refinement_route(
                    message,
                    has_project,
                )
            except Exception:
                pre_refinement_route = ""

            if pre_refinement_route == "chat":
                route = "chat"
                refined_message = message
            else:
                refined_result = _confirm_refinement(
                    self,
                    message,
                    has_project=has_project,
                    tui_v2=tui_v2,
                )

                if refined_result is None:
                    self.emit(
                        "system",
                        "Request cancelled; no files were changed.",
                    )
                    continue

                route, refined_message = refined_result

            # Installed visual capabilities must be activated here,
            # while the original/refined user request is still available.
            # Waiting until call_provider() is too late because chat routing
            # converts the request into an internal "Answer directly" prompt.
            from sophyane.runtime_capability_acquisition_patch import (
                _activate_editable_session,
                _is_editable_session_request,
            )

            if (
                _is_editable_session_request(message)
                or _is_editable_session_request(refined_message)
            ):
                self.last_mode = "execution"

                try:
                    text = _activate_editable_session(
                        self,
                        refined_message,
                    )
                except Exception as error:  # noqa: BLE001
                    self.emit(
                        "system",
                        "Editable visual activation failed safely: "
                        f"{type(error).__name__}: {error}",
                    )
                    continue

                self.active_request = refined_message
                self.active_workspace = str(
                    getattr(
                        self,
                        "_active_canvas_workspace",
                        "",
                    )
                )
                self.project_requirements = [
                    refined_message
                ]
                self.last_raw = text

                self.history.extend(
                    [
                        ("user", message[:300]),
                        ("assistant", text[:500]),
                    ]
                )
                self.history = self.history[-4:]

                self.emit("Sophyane", text)
                continue

            # Final route guard: a standalone media request must never reach
            # the software workspace even if another refinement layer emits
            # route=execution.
            if (
                tui_v2._pure_media_request(message)
                or tui_v2._pure_media_request(refined_message)
            ):
                route = "chat"

            # SOPHYANE_HARNESS_FINAL_ROUTE_AUTHORITY_V1
            # The intent-refinement model may incorrectly downgrade a strong
            # repository/build task to chat. The original user message has
            # final authority for deterministic harness routing.
            try:
                from sophyane.harness_task_policy import (
                    is_execution_request,
                )

                if is_execution_request(message):
                    route = (
                        "continue_project"
                        if has_project
                        and tui_v2._project_continuation(
                            message,
                            has_project,
                        )
                        else "execution"
                    )
            except Exception:
                pass

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
                    # SOPHYANE_CANONICAL_REQUEST_IN_INTENT_WRAPPER
                    snapshot = str(
                        getattr(
                            self,
                            "_sophyane_canonical_request_snapshot",
                            "",
                        )
                        or ""
                    ).strip()

                    active_request = str(
                        getattr(
                            self,
                            "active_request",
                            "",
                        )
                        or ""
                    ).strip()

                    if (
                        snapshot
                        and refined_message.casefold()
                        in snapshot.casefold()
                    ):
                        canonical_request = snapshot
                    elif (
                        active_request
                        and refined_message.casefold()
                        in active_request.casefold()
                    ):
                        canonical_request = active_request
                    else:
                        canonical_request = refined_message


                    text = tui_v2.run_structured_loop(
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
                text = tui_v2._render_nonexecuting_response(text)

            self.history.extend([("user", message[:300]), ("assistant", text[:500])])
            self.history = self.history[-4:]
            self.emit("Sophyane", text)

    tui_v2.ObservableTUI.run = run
    tui_v2.ObservableTUI._intent_refinement_installed = True
