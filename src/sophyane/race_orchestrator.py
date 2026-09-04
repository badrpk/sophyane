from __future__ import annotations

# SOPHYANE_REAL_THREE_WORKER_RACE_V1

import json
import hashlib
import os
import queue
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sophyane.execution_runtime import (
    _normalize_action,
)
from sophyane.race_adapters import (
    CooperativeRace,
    ProgressProposal,
    proposal_worker,
)

_MODE1_RECOVERABLE_MARKERS = ("quota", "rate limit", "429", "timeout", "timed out", "temporar", "unavailable", "transport", "connection", "network", "credentials unavailable", "token exhausted", "authentication exhausted")
_MODE1_NON_RECOVERABLE_MARKERS = ("approval", "safety", "permission denied", "forbidden", "unauthorized", "invalid_api_key", "incorrect api key", "authentication_error", "billing")

def _mode1_recoverable_provider_error(error: BaseException) -> bool:
    text = str(error).strip().lower()
    return bool(text) and not any(marker in text for marker in _MODE1_NON_RECOVERABLE_MARKERS) and any(marker in text for marker in _MODE1_RECOVERABLE_MARKERS)

def _mode1_penalize_route(scores: dict[str, float], route: str, error: BaseException) -> None:
    """Record a request-local TXQ capability penalty for a failed route."""
    scores[route] = scores.get(route, 1.0) - 1.0


def _mode1_provider_order(primary: str, config: dict[str, Any]) -> tuple[str, ...]:
    """Resolve eligible intelligence routes without reading mutable global state."""
    primary = str(primary or "").strip().lower()
    order: list[str] = []
    def add(value: Any) -> None:
        name = str(value or "").strip().lower()
        if name and name not in order and name != "fallback":
            order.append(name)
    add(primary)
    explicit_present = "provider_fallback_order" in config or "fallback_order" in config
    explicit = config.get("provider_fallback_order", config.get("fallback_order", ()))
    for value in explicit or ():
        add(value)
    # An explicitly supplied lane is authoritative: independent workers must
    # not collapse into a cross-class fallback chain.
    if not explicit_present and (primary not in {"local", "local_gguf"} or bool(config.get("allow_local_fallbacks"))):
        for value in ("gemini", "xai", "openai", "anthropic", "groq", "openrouter", "deepseek", "nifdu_browser", "codex_cli", "agy", "local_gguf"):
            add(value)
    return tuple(order)


Progress = Callable[[str], None]


@dataclass(frozen=True)
class RaceEngineResult:
    engine: str
    proposal: ProgressProposal[Any]
    raw: Any = None


@dataclass
class RealRaceResult:
    race_result: Any
    workspace: Path
    shadow_workspaces: dict[str, Path]

    @property
    def winner(self):
        return self.race_result.winner

    @property
    def ok(self) -> bool:
        return bool(
            self.race_result
            and self.race_result.winner
        )


def _noop_progress(
    _message: str,
) -> None:
    return None


def _emit(
    progress: Progress | None,
    message: str,
) -> None:
    callback = (
        progress
        if callable(progress)
        else _noop_progress
    )

    try:
        callback(
            message
        )
    except Exception:
        pass


def _copy_shadow_workspace(
    workspace: Path,
    *,
    engine: str,
) -> Path:
    """Create an isolated speculative workspace.

    The authoritative repository is never handed to SLI during the race.
    """
    workspace = (
        workspace
        .expanduser()
        .resolve()
    )

    root = Path(
        tempfile.mkdtemp(
            prefix=(
                f"sophyane-race-{engine}-"
            )
        )
    )

    destination = (
        root
        / "workspace"
    )

    ignore_names = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
    }

    def ignore(
        _directory: str,
        names: list[str],
    ):
        return [
            name
            for name in names
            if (
                name in ignore_names
                or ".before-" in name
            )
        ]

    shutil.copytree(
        workspace,
        destination,
        ignore=ignore,
        symlinks=True,
    )

    return destination


def _file_manifest(
    root: Path,
) -> dict[str, tuple[int, int]]:
    """Cheap structural manifest used to detect shadow mutations."""
    result: dict[
        str,
        tuple[int, int],
    ] = {}

    if not root.exists():
        return result

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        relative = str(
            path.relative_to(root)
        )

        result[
            relative
        ] = (
            int(stat.st_size),
            int(stat.st_mtime_ns),
        )

    return result


def _shadow_changes(
    before: dict[str, tuple[int, int]],
    shadow: Path,
) -> tuple[str, ...]:
    after = _file_manifest(
        shadow
    )

    changed = sorted(
        {
            *(
                key
                for key, value
                in after.items()
                if before.get(key)
                != value
            ),
            *(
                key
                for key
                in before
                if key not in after
            ),
        }
    )

    return tuple(
        changed
    )


def _extract_json_object(
    text: str,
) -> dict[str, Any] | None:
    value = str(
        text
        or ""
    ).strip()

    if not value:
        return None

    try:
        parsed = json.loads(
            value
        )

        if isinstance(
            parsed,
            dict,
        ):
            return parsed

    except json.JSONDecodeError:
        pass

    first = value.find("{")
    last = value.rfind("}")

    if (
        first < 0
        or last <= first
    ):
        return None

    try:
        parsed = json.loads(
            value[
                first:
                last + 1
            ]
        )

    except json.JSONDecodeError:
        return None

    return (
        parsed
        if isinstance(
            parsed,
            dict,
        )
        else None
    )


def _llm_proposal(
    *,
    engine: str,
    text: str,
    mode: str = "execution",
) -> ProgressProposal[Any]:
    """Turn local/cloud output into one validated speculative proposal."""
    raw = str(
        text
        or ""
    ).strip()

    parsed = (
        _extract_json_object(
            raw
        )
    )

    action = None

    if parsed is not None:
        action = (
            _normalize_action(
                parsed
            )
        )

    if action is not None:
        return ProgressProposal(
            engine=engine,
            payload={
                "action": action,
                "raw": raw,
            },
            kind="action",
            confidence=0.82,
            evidence=(
                "valid JSON",
                (
                    "execution action normalized "
                    "by execution_runtime"
                ),
            ),
            # The proposal itself is read-only.
            # Mutation happens only after explicit promotion.
            requires_write=False,
        )

    if raw:
        direct_answer = (
            str(mode).strip().lower() == "answer"
        )

        return ProgressProposal(
            engine=engine,
            payload={
                (
                    "answer"
                    if direct_answer
                    else "plan"
                ): raw,
            },
            kind=(
                "answer"
                if direct_answer
                else "plan"
            ),
            confidence=0.60,
            evidence=(
                (
                    "non-empty provider answer"
                    if direct_answer
                    else "non-empty provider proposal"
                ),
            ),
            requires_write=False,
        )

    return ProgressProposal(
        engine=engine,
        payload="",
        kind="plan",
        confidence=0.0,
        evidence=(),
        requires_write=False,
    )


def _race_system_prompt(
    mode: str = "execution",
) -> str:
    if str(mode).strip().lower() == "answer":
        return (
            "You are a speculative Sophyane answer worker. "
            "Return the best direct user-facing answer. "
            "Do not return executable action JSON, commands, "
            "or claims that files were modified."
        )

    return (
        "You are a speculative Sophyane race worker. "
        "Do NOT assume you own the repository and do NOT claim "
        "that files were modified. Analyze the objective and return "
        "the single best NEXT ACTION as strict JSON. "
        "Preferred schema: "
        '{"action":{"type":"run|write_file|append_file|mkdir|respond",'
        '"path":"optional relative path",'
        '"command":"optional command",'
        '"content":"optional content",'
        '"message":"optional response"}}. '
        "Return one action only."
    )

def _race_user_prompt(
    request: str,
    workspace: Path,
    mode: str = "execution",
) -> str:
    if str(mode).strip().lower() == "answer":
        return (
            "SOPHYANE SPECULATIVE ANSWER RACE\n\n"
            "User request:\n"
            f"{request}\n\n"
            "Return the direct answer only."
        )

    return (
        "SOPHYANE SPECULATIVE RACE\n\n"
        f"Workspace: {workspace}\n\n"
        "Objective:\n"
        f"{request}\n\n"
        "Generate only the next useful action. "
        "Do not execute it."
    )

# SOPHYANE_RACE_LOCAL_HARD_DEADLINE_V1
_LOCAL_RACE_APPLICATION_DEADLINE_SECONDS = 6.0


def _generate_provider_for_race(
    *,
    provider: Any,
    provider_id: str,
    prompt: str,
    system_prompt: str,
) -> Any:
    """Generate one race proposal with a hard local application deadline.

    Local GGUF generation runs behind an external deadline because the
    provider itself intentionally permits longer on-device generations.
    A local result reaching this boundary is cancelled and can never cross
    back into race proposal validation or winner selection.

    Non-local providers retain their existing synchronous behaviour.
    """
    normalized = str(
        provider_id
        or ""
    ).strip().lower()

    if normalized != "local_gguf":
        return provider.generate(
            prompt,
            system_prompt,
        )

    from sophyane.runtime_cancel import (
        bind_generation,
        cancel_generation,
        new_generation,
        release_generation,
    )

    generation = new_generation()

    result_queue: queue.Queue[
        tuple[str, Any]
    ] = queue.Queue(
        maxsize=1
    )

    started = time.monotonic()
    deadline = (
        started
        + _LOCAL_RACE_APPLICATION_DEADLINE_SECONDS
    )

    def worker() -> None:
        bind_generation(
            generation
        )

        try:
            value = provider.generate(
                prompt,
                system_prompt,
            )

            item = (
                "ok",
                value,
            )

        except BaseException as error:  # noqa: BLE001
            item = (
                "error",
                error,
            )

        finally:
            release_generation(
                generation
            )

        try:
            result_queue.put_nowait(
                item
            )
        except queue.Full:
            # The parent may already have timed out and abandoned the queue.
            pass

    thread = threading.Thread(
        target=worker,
        daemon=True,
        name="sophyane-race-local-provider",
    )

    thread.start()

    while True:
        remaining = (
            deadline
            - time.monotonic()
        )

        if remaining <= 0:
            cancel_generation(
                generation
            )

            # Never wait for the late provider thread. Its queue is private
            # to this invocation and nothing after this point can be applied.
            try:
                while True:
                    result_queue.get_nowait()
            except queue.Empty:
                pass

            raise TimeoutError(
                "race local_gguf response exceeded "
                f"{_LOCAL_RACE_APPLICATION_DEADLINE_SECONDS:g}s "
                "and was discarded"
            )

        try:
            status, value = (
                result_queue.get(
                    timeout=min(
                        0.05,
                        remaining,
                    )
                )
            )
        except queue.Empty:
            continue

        completed_at = (
            time.monotonic()
        )

        # Completion at the deadline is late. Do this check after dequeueing
        # so a scheduling race cannot smuggle an over-budget result through.
        if completed_at >= deadline:
            cancel_generation(
                generation
            )

            raise TimeoutError(
                "race local_gguf response exceeded "
                f"{_LOCAL_RACE_APPLICATION_DEADLINE_SECONDS:g}s "
                "and was discarded"
            )

        if status == "error":
            raise value

        return value


def _single_provider(
    *,
    provider_id: str,
    config: dict[str, Any],
):
    """Create exactly one provider without a fallback chain."""
    # Import through main because the current production tree already
    # centralizes PluginLoader/get_secret there.
    from sophyane.main import (
        PluginLoader,
        get_secret,
    )

    loader = PluginLoader()
    providers = loader.discover()

    if provider_id not in providers:
        raise RuntimeError(
            f"provider unavailable: {provider_id}"
        )

    provider_class = (
        providers[
            provider_id
        ]
    )

    metadata = (
        provider_class.metadata
    )

    api_key = ""

    if metadata.requires_api_key:
        api_key = (
            get_secret(
                provider_id,
                metadata.environment_variable,
            )
            or ""
        )

        # Gemini installations commonly use GOOGLE_API_KEY.
        if (
            provider_id == "gemini"
            and not api_key
        ):
            api_key = (
                get_secret(
                    "gemini",
                    "GOOGLE_API_KEY",
                )
                or ""
            )

        if not api_key:
            raise RuntimeError(
                f"{provider_id} credentials unavailable"
            )

    model = ""

    if (
        provider_id
        == "local_gguf"
    ):
        try:
            from sophyane.providers.local_gguf import (
                load_gguf_runtime_state,
            )

            state = (
                load_gguf_runtime_state()
                or {}
            )

            model = str(
                state.get("model")
                or ""
            ).strip()

        except Exception:
            model = ""

    if not model:
        configured_provider = str(
            config.get("provider")
            or ""
        ).strip().lower()

        if configured_provider == provider_id:
            model = str(
                config.get("model")
                or ""
            ).strip()

    if not model:
        model = str(
            metadata.default_model
            or ""
        ).strip()

    timeout = int(
        config.get("timeout")
        or (
            300
            if provider_id
            == "local_gguf"
            else 180
        )
    )

    max_tokens = int(
        config.get("max_tokens")
        or 4096
    )

    # A race proposal is one compact next action, not a complete artifact.
    max_tokens = min(
        max_tokens,
        384,
    )

    return loader.create(
        provider_id,
        api_key=api_key,
        model=model,
        timeout=timeout,
        temperature=float(
            config.get(
                "temperature",
                0.3,
            )
        ),
        max_tokens=max_tokens,
    )



# SOPHYANE_SLI_STATE_ACCESS_V1
def _state_value(
    state: Any,
    key: str,
    default: Any = None,
) -> Any:
    """Read SLI results whether represented as mappings or objects."""
    if isinstance(
        state,
        dict,
    ):
        return state.get(
            key,
            default,
        )

    return getattr(
        state,
        key,
        default,
    )


# SOPHYANE_SLI_STATE_ACCESS_V1
def _state_value(
    state: Any,
    key: str,
    default: Any = None,
) -> Any:
    """Read SLI results whether represented as mappings or objects."""
    if isinstance(
        state,
        dict,
    ):
        return state.get(
            key,
            default,
        )

    return getattr(
        state,
        key,
        default,
    )


def make_sli_producer(
    *,
    request: str,
    workspace: Path,
    progress: Progress | None = None,
    shadow_registry: dict[str, Path] | None = None,
    authority_context=None,
):
    """Build the real SLI worker against an isolated workspace."""

    def produce():
        from sophyane.sli_graph import (
            run_sli_graph,
        )

        shadow = (
            _copy_shadow_workspace(
                workspace,
                engine="sli",
            )
        )

        if (
            shadow_registry
            is not None
        ):
            shadow_registry[
                "sli"
            ] = shadow

        before = (
            _file_manifest(
                shadow
            )
        )

        _emit(
            progress,
            (
                "Race SLI worker: "
                "starting isolated SLI Graph"
            ),
        )

        # SOPHYANE_RACE_SLI_HARNESS_FAST_PATH_V1
        #
        # A coding/test-repair race must not fall through from a failed
        # local harness attempt into slow internet/browser acquisition.
        # In race mode SLI is a speculative peer: return its harness
        # evidence promptly and let another worker win if it cannot repair.
        from sophyane.sli_harness_orchestrator import (
            is_harness_execution_request,
            run_harness_execution,
        )

        if is_harness_execution_request(
            request
        ):
            _emit(
                progress,
                (
                    "Race SLI worker: "
                    "direct harness fast path"
                ),
            )

            harness_result = run_harness_execution(
                request,
                workspace=shadow,
                progress=progress,
            )

            harness_ok = bool(
                _state_value(
                    harness_result,
                    "ok",
                    _state_value(
                        harness_result,
                        "success",
                        False,
                    ),
                )
            )

            harness_report = (
                _state_value(
                    harness_result,
                    "report",
                    None,
                )
                or _state_value(
                    harness_result,
                    "summary",
                    None,
                )
                or _state_value(
                    harness_result,
                    "error",
                    None,
                )
                or str(
                    harness_result
                    or ""
                )
            )

            state = {
                "route": "harness_execution",
                "success": harness_ok,
                "promoted": False,
                "report": str(
                    harness_report
                    or ""
                ),
            }

        else:
            # SOPHYANE_RACE_SLI_DETERMINISTIC_CAPABILITY_FAST_PATH_V1
            #
            # Give the unified deterministic execution kernel first refusal
            # inside the isolated SLI shadow.  The authoritative workspace
            # remains untouched until normal race winner application.
            from sophyane.unified_execution_kernel import (
                execute_request as execute_unified_request,
            )

            deterministic_result = execute_unified_request(
                request,
                workspace=shadow,
            )

            deterministic_handled = bool(
                getattr(
                    deterministic_result,
                    "handled",
                    False,
                )
            )

            if deterministic_handled:
                deterministic_ok = bool(
                    getattr(
                        deterministic_result,
                        "ok",
                        False,
                    )
                )

                capability = str(
                    getattr(
                        deterministic_result,
                        "capability",
                        "",
                    )
                    or getattr(
                        deterministic_result,
                        "capability_id",
                        "",
                    )
                    or "deterministic_capability"
                ).strip()

                report_value = (
                    getattr(
                        deterministic_result,
                        "message",
                        None,
                    )
                    or getattr(
                        deterministic_result,
                        "text",
                        None,
                    )
                    or getattr(
                        deterministic_result,
                        "detail",
                        None,
                    )
                    or str(
                        deterministic_result
                        or ""
                    )
                )

                _emit(
                    progress,
                    (
                        "Race SLI worker: "
                        "deterministic capability fast path "
                        f"capability={capability} "
                        f"ok={deterministic_ok}"
                    ),
                )

                state = {
                    "route":
                        "deterministic_capability",

                    "success":
                        deterministic_ok,

                    "promoted":
                        False,

                    "report":
                        str(
                            report_value
                            or capability
                        ),

                    "capability":
                        capability,
                }

            else:
                state = run_sli_graph(
                    request,
                    workspace=shadow,
                    progress=progress,
                    max_retries=1,
                    context=authority_context,
                )

        report = str(
            _state_value(
                state,
                "report",
                "",
            )
            or ""
        ).strip()

        route = str(
            _state_value(
                state,
                "route",
                "",
            )
            or ""
        ).strip()

        success = bool(
            _state_value(
                state,
                "success",
                False,
            )
        )

        promoted = bool(
            _state_value(
                state,
                "promoted",
                False,
            )
        )

        changed = (
            _shadow_changes(
                before,
                shadow,
            )
        )

        evidence = []

        if route:
            evidence.append(
                f"SLI route={route}"
            )

        if success:
            evidence.append(
                "SLI state success"
            )

        if promoted:
            evidence.append(
                "SLI candidate promoted"
            )

        if report:
            evidence.append(
                "SLI report produced"
            )

        if changed:
            evidence.append(
                (
                    "isolated shadow changed "
                    f"{len(changed)} file(s)"
                )
            )

        # A failed SLI attempt may still return useful diagnostics,
        # but diagnostics alone must never become a valid race winner.
        #
        # Previously:
        #   base 0.45 + route 0.08 + report 0.07 == 0.60
        #
        # That exceeded the adaptive race minimum score of 0.55 even
        # when success=False and promoted=False, allowing a failed SLI
        # artifact to cancel a still-running local provider.
        if not success:
            confidence = 0.0
        else:
            confidence = 0.45

            if route:
                confidence += 0.08

            if report:
                confidence += 0.07

            confidence += 0.18

            if promoted:
                confidence += 0.12

            confidence = min(
                confidence,
                0.95,
            )

        return ProgressProposal(
            engine="sli",
            payload={
                "route": route,
                "report": report,
                "success": success,
                "promoted": promoted,
                # SOPHYANE_RACE_DETERMINISTIC_CAPABILITY_PROVENANCE_V1
                #
                # Preserve trusted deterministic capability identity across
                # the isolated SLI proposal boundary.  race_execution can
                # then distinguish a runtime-verified exact write from an
                # ordinary provider-generated write_file proposal.
                "capability": (
                    str(
                        _state_value(
                            state,
                            "capability",
                            "",
                        )
                        or ""
                    ).strip()
                ),
                "shadow_workspace": (
                    str(shadow)
                ),
                "changed_files": (
                    changed
                ),
            },
            kind=(
                "patch"
                if changed
                else "acquisition"
            ),
            confidence=confidence,
            evidence=tuple(
                evidence
            ),
            # Shadow mutations do not imply permission to mutate real repo.
            requires_write=False,
        )

    return produce




# SOPHYANE_RACE_SEMANTIC_PROPOSAL_RELEVANCE_V1
def _semantic_proposal_relevance(
    *,
    request: str,
    action: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Judge whether one proposed action materially advances the objective.

    This gate is intentionally separate from final semantic completion:
    relevance asks whether the NEXT action is useful; completion asks whether
    the requested objective has ultimately been satisfied.
    """
    try:
        provider = _single_provider(
            provider_id="gemini",
            config=config,
        )

        system_prompt = (
            "You are Sophyane's speculative race proposal relevance judge. "
            "Judge ONLY whether the supplied NEXT ACTION materially advances "
            "the ORIGINAL USER OBJECTIVE. "
            "Do not reward an action merely because it is valid JSON, safe, "
            "executable, or syntactically normalized. "
            "Inspection and discovery commands may be relevant when they are "
            "reasonably necessary for the objective, but generic busywork "
            "must not pass. "
            "Return ONLY strict JSON with exactly these keys: "
            '{"relevant":true|false,"score":0.0,'
            '"reason":"concise explanation"}. '
            "score must be between 0.0 and 1.0. "
            "Use score >= 0.55 only when the action materially advances the "
            "objective."
        )

        user_prompt = (
            "ORIGINAL USER OBJECTIVE:\n"
            + str(request)
            + "\n\nPROPOSED NEXT ACTION:\n"
            + json.dumps(
                action,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        raw = provider.generate(
            user_prompt,
            system_prompt,
        )

        raw_text = str(raw or "").strip()

        if raw_text.startswith("```"):
            lines = raw_text.splitlines()

            if lines:
                lines = lines[1:]

            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]

            raw_text = "\n".join(lines).strip()

        parsed = json.loads(raw_text)

        if not isinstance(parsed, dict):
            raise ValueError(
                "proposal relevance judge did not return an object"
            )

        relevant = bool(parsed.get("relevant"))

        try:
            score = float(parsed.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        score = max(
            0.0,
            min(
                1.0,
                score,
            ),
        )

        reason = str(
            parsed.get("reason")
            or ""
        ).strip()

        if not relevant:
            score = min(
                score,
                0.54,
            )

        return {
            "available": True,
            "relevant": relevant,
            "score": score,
            "reason": reason,
        }

    except Exception as exc:
        return {
            "available": False,
            "relevant": None,
            "score": None,
            "reason": (
                "Semantic proposal relevance judge unavailable: "
                + str(exc)
            ),
        }



# SOPHYANE_RACE_DIRECT_ANSWER_COMPLETION_V1
def _answer_completion_judgement(
    *,
    request: str,
    answer: str,
) -> dict[str, Any]:
    """Deterministically check explicit direct-answer deliverables.

    This is intentionally local and provider-independent.  It does not try
    to decide whether prose is brilliant; it prevents a merely non-empty
    response from winning when the user explicitly requested concrete
    artifacts or precision guarantees that the response omitted.
    """
    request_text = str(request or "").strip()
    answer_text = str(answer or "").strip()

    request_lower = request_text.lower()
    answer_lower = answer_text.lower()

    missing: list[str] = []
    evidence: list[str] = []

    if not answer_text:
        return {
            "complete": False,
            "score": 0.0,
            "missing": ("non-empty answer",),
            "evidence": (),
        }

    # Explicit code-deliverable requests must contain actual fenced code,
    # rather than prose that merely says a snippet could be written.
    code_requested = any(
        phrase in request_lower
        for phrase in (
            "code snippet",
            "code example",
            "complete code",
            "complete implementation",
            "working implementation",
            "provide code",
            "show code",
        )
    )

    has_code_fence = "```" in answer_text

    if code_requested:
        if has_code_fence:
            evidence.append("requested code artifact present")
        else:
            missing.append("requested code artifact")

    # Preserve explicit language requirements.  When multiple languages are
    # joined by "/" or "and", each requested language is material.
    language_markers = {
        "python": (
            "python" in request_lower,
            (
                "```python" in answer_lower
                or "python" in answer_lower
            ),
        ),
        "c++": (
            (
                "c++" in request_lower
                or "cpp" in request_lower
            ),
            (
                "```cpp" in answer_lower
                or "```c++" in answer_lower
                or "c++" in answer_lower
                or "cpp" in answer_lower
            ),
        ),
        "javascript": (
            (
                "javascript" in request_lower
                or "js " in request_lower
            ),
            (
                "```javascript" in answer_lower
                or "```js" in answer_lower
                or "javascript" in answer_lower
            ),
        ),
        "typescript": (
            "typescript" in request_lower,
            (
                "```typescript" in answer_lower
                or "```ts" in answer_lower
                or "typescript" in answer_lower
            ),
        ),
        "rust": (
            "rust" in request_lower,
            (
                "```rust" in answer_lower
                or "rust" in answer_lower
            ),
        ),
        "go": (
            (
                " golang" in request_lower
                or " go " in f" {request_lower} "
            ),
            (
                "```go" in answer_lower
                or "golang" in answer_lower
            ),
        ),
    }

    for language, (requested, present) in language_markers.items():
        if not requested:
            continue

        if present:
            evidence.append(
                f"requested language present: {language}"
            )
        else:
            missing.append(
                f"requested language: {language}"
            )

    # Exactness/guarantee phrases are material constraints.  A response that
    # silently weakens them must not receive a winning score.
    precision_requirements = (
        (
            ("bit-for-bit", "bit for bit"),
            ("bit-for-bit", "bit for bit"),
            "bit-for-bit precision",
        ),
        (
            ("deterministic replay",),
            ("deterministic replay", "deterministic", "replay"),
            "deterministic replay",
        ),
        (
            ("thread interleaving", "thread interleavings"),
            ("interleaving", "schedule", "thread"),
            "thread interleavings",
        ),
        (
            ("async api", "asynchronous api"),
            ("async", "asynchronous", "api response"),
            "async API capture",
        ),
    )

    for request_terms, answer_terms, label in precision_requirements:
        if not any(
            term in request_lower
            for term in request_terms
        ):
            continue

        if any(
            term in answer_lower
            for term in answer_terms
        ):
            evidence.append(
                f"requested capability addressed: {label}"
            )
        else:
            missing.append(
                f"requested capability: {label}"
            )

    # A requested replay demonstration must show replay behavior, not merely
    # define a logger.
    replay_demo_requested = (
        "replay a failed execution path" in request_lower
        or "show how to replay" in request_lower
        or "demonstrate replay" in request_lower
    )

    if replay_demo_requested:
        replay_signal = (
            "replay" in answer_lower
            and (
                "failed" in answer_lower
                or "journal" in answer_lower
                or "schedule" in answer_lower
            )
        )

        if replay_signal:
            evidence.append("requested replay demonstration addressed")
        else:
            missing.append("requested replay demonstration")

    if missing:
        # Hard ceiling below CooperativeRace's normal 0.55 threshold.
        score = 0.54
        complete = False
    else:
        score = 0.72
        complete = True

    return {
        "complete": complete,
        "score": score,
        "missing": tuple(missing),
        "evidence": tuple(evidence),
    }


def make_provider_producer(
    *,
    engine: str,
    provider_id: str,
    request: str,
    workspace: Path,
    config: dict[str, Any],
    progress: Progress | None = None,
    mode: str = "execution",
):
    """Build one local/cloud speculative provider worker."""

    def prepare_proposal(raw: object) -> ProgressProposal[Any]:
        proposal = _llm_proposal(
            engine=engine,
            text=str(
                raw
                or ""
            ),
            mode=mode,
        )

        # Direct-answer races require deterministic completion evidence.
        # A non-empty answer is not sufficient by itself: explicit requested
        # deliverables such as complete code, named languages, replay, or
        # precision guarantees must actually appear in the response.
        if (
            str(mode).strip().lower() == "answer"
            and proposal.kind == "answer"
            and isinstance(proposal.payload, dict)
        ):
            answer_text = str(
                proposal.payload.get("answer")
                or ""
            ).strip()

            judgement = _answer_completion_judgement(
                request=request,
                answer=answer_text,
            )

            evidence = list(
                proposal.evidence
            )
            evidence.extend(
                judgement["evidence"]
            )

            missing = tuple(
                judgement["missing"]
            )

            if missing:
                evidence.append(
                    "missing answer requirements: "
                    + ", ".join(missing)
                )

            proposal = ProgressProposal(
                engine=proposal.engine,
                payload=proposal.payload,
                kind=proposal.kind,
                confidence=float(
                    judgement["score"]
                ),
                evidence=tuple(evidence),
                requires_write=proposal.requires_write,
            )

        # Executable proposals retain the objective-aware action gate.
        if (
            str(mode).strip().lower() != "answer"
            and proposal.kind == "action"
            and isinstance(proposal.payload, dict)
            and isinstance(
                proposal.payload.get("action"),
                dict,
            )
        ):
            judgement = _semantic_proposal_relevance(
                request=request,
                action=proposal.payload["action"],
                config=config,
            )

            if judgement["available"]:
                semantic_score = float(
                    judgement["score"]
                    or 0.0
                )

                reason = str(
                    judgement["reason"]
                    or ""
                ).strip()

                evidence = list(
                    proposal.evidence
                )
                evidence.append(
                    "semantic proposal relevance="
                    + (
                        "relevant"
                        if judgement["relevant"]
                        else "irrelevant"
                    )
                )

                if reason:
                    evidence.append(
                        "semantic relevance: "
                        + reason
                    )

                proposal = ProgressProposal(
                    engine=proposal.engine,
                    payload=proposal.payload,
                    kind=proposal.kind,
                    confidence=semantic_score,
                    evidence=tuple(evidence),
                    requires_write=proposal.requires_write,
                )

        return proposal

    def usable_for_mode(
        proposal: ProgressProposal[Any],
    ) -> bool:
        normalized_mode = str(mode).strip().lower()

        if normalized_mode == "answer":
            # Answer workers may fall through to another intelligence
            # source when deterministic completion evidence leaves the
            # proposal below the race acceptance threshold. The proposal
            # is still retained as best_proposal so exhausting all routes
            # returns evidence to the race instead of converting a
            # semantic shortfall into a provider failure.
            return (
                proposal.kind == "answer"
                and isinstance(proposal.payload, dict)
                and bool(
                    str(
                        proposal.payload.get("answer")
                        or ""
                    ).strip()
                )
                and float(proposal.confidence) >= 0.55
            )

        # Execution-mode semantic confidence belongs to the race layer.
        # Any structurally valid normalized action remains a legitimate
        # proposal even when semantic relevance scores it below 0.55.
        return (
            proposal.kind == "action"
            and isinstance(proposal.payload, dict)
            and isinstance(
                proposal.payload.get("action"),
                dict,
            )
        )

    def produce():
        _emit(
            progress,
            (
                f"Race {engine} worker: "
                "creating isolated provider"
            ),
        )

        prompt = _race_user_prompt(
            request,
            workspace,
            mode=mode,
        )
        system_prompt = _race_system_prompt(
            mode=mode,
        )

        last_error: Exception | None = None
        best_proposal: ProgressProposal[Any] | None = None
        route_scores: dict[str, float] = {}

        for route in _mode1_provider_order(
            provider_id,
            config,
        ):
            try:
                provider = _single_provider(
                    provider_id=route,
                    config=config,
                )

                _emit(
                    progress,
                    (
                        f"Race {engine} worker: "
                        f"requesting proposal via {route}"
                    ),
                )

                raw = _generate_provider_for_race(
                    provider=provider,
                    provider_id=route,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )

                usage_getter = getattr(
                    provider,
                    "get_token_usage",
                    None,
                )
                usage = (
                    usage_getter()
                    if callable(usage_getter)
                    else {}
                )

                if isinstance(usage, dict) and usage:
                    compact = ", ".join(
                        f"{key}={value}"
                        for key, value
                        in sorted(usage.items())
                    )
                    _emit(
                        progress,
                        (
                            f"Race {engine}: route "
                            f"{route} complete · "
                            f"tokens {compact}"
                        ),
                    )
                else:
                    _emit(
                        progress,
                        (
                            f"Race {engine}: route "
                            f"{route} complete · tokens n/a"
                        ),
                    )

                proposal = prepare_proposal(raw)

                if (
                    best_proposal is None
                    or float(proposal.confidence)
                    > float(best_proposal.confidence)
                ):
                    best_proposal = proposal

                if usable_for_mode(proposal):
                    return proposal

                # A provider call may succeed transport-wise while still
                # producing something unusable for this race mode. Treat that
                # as a request-local capability miss, not as terminal success.
                # The original request/prompt and authority remain unchanged.
                _mode1_penalize_route(
                    route_scores,
                    route,
                    RuntimeError(
                        "provider proposal unusable "
                        f"for {str(mode).strip().lower()} mode"
                    ),
                )

                _emit(
                    progress,
                    (
                        f"Race {engine} provider {route} "
                        "proposal unusable for this request; "
                        "trying next eligible intelligence route"
                    ),
                )

            except Exception as error:
                last_error = error

                if not _mode1_recoverable_provider_error(
                    error
                ):
                    raise

                # Feed transport/availability failure into request-local TXQ
                # capability scoring. The objective is retained byte-for-byte.
                _mode1_penalize_route(
                    route_scores,
                    route,
                    error,
                )

                _emit(
                    progress,
                    (
                        f"Race {engine} provider {route} "
                        "penalised for this request"
                    ),
                )

        if best_proposal is not None:
            return best_proposal

        if last_error is not None:
            raise last_error

        raise RuntimeError(
            "no eligible intelligence provider produced "
            "any proposal"
        )

    return produce


def _mode1_sli_applies(request: str) -> bool:
    """Admit SLI when grounding or the bounded repair harness can contribute."""
    text = " ".join(str(request or "").lower().split())

    if any(
        token in text
        for token in (
            "memory",
            "internet",
            "research",
            "ground",
            "source",
            "index",
            "graph",
            "latest",
        )
    ):
        return True

    # SOPHYANE_MODE1_SLI_HARNESS_ADMISSION_V1
    # make_sli_producer already owns a bounded coding/test-repair fast path.
    # Keep admission aligned with that classifier so repair objectives such
    # as "fix the pytest failure" can actually race through SLI instead of
    # making the fast path unreachable behind grounding-only keywords.
    try:
        from sophyane.sli_harness_orchestrator import (
            is_harness_execution_request,
        )

        return bool(
            is_harness_execution_request(
                request
            )
        )
    except Exception:
        # Admission failure must not make Mode 1 unavailable. Other independent
        # intelligence lanes remain eligible and may still complete the task.
        return False


def _mode1_capability_class(provider_id: str) -> str:
    provider = str(provider_id or "").strip().lower()
    if provider in {"nifdu_browser", "browser", "chatgpt_browser"}:
        return "external_browser"
    if provider in {"codex_cli", "agy", "claude_code", "harness"}:
        return "external_harness"
    if provider in {"local_gguf", "local"}:
        return "local_gguf"
    return "external_api"


def _mode1_provider_available(provider_id: str, config: dict[str, Any]) -> bool:
    """Use startup's readiness inventory; explicit test inventories remain supported."""
    provider = str(provider_id).strip().lower()
    advertised = config.get("available_providers")
    if isinstance(advertised, (list, tuple, set)):
        return provider in {str(item).strip().lower() for item in advertised}
    try:
        from sophyane.startup_policy import intelligence_provider_inventory
        return provider in intelligence_provider_inventory(config)
    except Exception:
        return provider in {"local", "local_gguf"}


# Eligibility is decided before this point; history only breaks ties between
# proposals that already clear the normal race threshold.
_MODE1_HISTORY_BONUS_CAP = 0.10
_MODE1_HISTORY_MIN_SCORE = 0.55


def _mode1_history_capability(worker_id: str, provider_id: str) -> str:
    if str(worker_id).strip().lower() == "sli":
        return "sli_graph"
    return _mode1_capability_class(provider_id)


def _mode1_verified_history_bonus(*, request: str, worker_id: str, provider_id: str, repository_identity: str | None = None) -> float:
    """Return a bounded advisory bonus from canonical trusted history."""
    try:
        from sophyane.sli_learner import read_verified_history
        records = read_verified_history(request=request, capability_class=_mode1_history_capability(worker_id, provider_id), limit=16)
    except Exception:
        return 0.0
    unique: dict[str, dict[str, Any]] = {}
    for record in records or ():
        if not isinstance(record, dict):
            continue
        identity = (str(record.get("event_key") or "").strip() or str(record.get("trace_id") or "").strip() or "|".join(str(record.get(key) or "").strip() for key in ("objective_hash", "provider_identity", "created_at")))
        if identity and identity not in unique:
            unique[identity] = record
    if not unique:
        return 0.0
    provider = str(provider_id or "").strip().casefold()
    repository = str(repository_identity or "").strip().casefold()
    provider_hits = sum(str(record.get("provider_identity") or "").strip().casefold() == provider for record in unique.values() if provider)
    repository_hits = sum(str(record.get("repository_identity") or "").strip().casefold() == repository for record in unique.values() if repository)
    bonus = min(0.06, 0.02 * len(unique))
    if provider_hits:
        bonus += 0.02
    if repository_hits:
        bonus += 0.02
    return min(_MODE1_HISTORY_BONUS_CAP, bonus)


def _mode1_recurrent_principle_bonus(*, worker_id: str, provider_id: str, repository_identity: str | None, principles_root: str | Path | None) -> float:
    """Return a small scope-checked bonus from canonical recurrent principles."""
    if principles_root is None:
        return 0.0
    try:
        from sophyane.evolution.principles import PrincipleStore
        principles = PrincipleStore.read_recurrent_principles(principles_root, limit=32)
    except Exception:
        return 0.0
    capability = _mode1_history_capability(worker_id, provider_id).casefold()
    repository = str(repository_identity or "").strip().casefold()
    matched: set[str] = set()
    for principle in principles:
        if str(principle.get("origin") or "").casefold() != "verified_execution":
            continue
        scoped = {str(principle.get("component") or "").strip().casefold()}
        scoped.update(str(value).strip().casefold() for value in (principle.get("capabilities") or ()))
        if capability not in scoped:
            continue
        principle_repository = str(principle.get("repository_identity") or "").strip().casefold()
        if principle_repository and principle_repository != repository:
            continue
        identity = str(principle.get("id") or principle.get("principle") or "").strip()
        if identity:
            matched.add(identity)
    return min(0.04, 0.02 * len(matched))


def _mode1_apply_history_preference(proposal: ProgressProposal[Any], *, request: str, worker_id: str, provider_id: str, repository_identity: str | None = None, principles_root: str | Path | None = None) -> ProgressProposal[Any]:
    """Apply history only after the normal proposal has cleared the gate."""
    base = float(proposal.confidence)
    if base < _MODE1_HISTORY_MIN_SCORE:
        return proposal
    history_bonus = _mode1_verified_history_bonus(request=request, worker_id=worker_id, provider_id=provider_id, repository_identity=repository_identity)
    principle_bonus = _mode1_recurrent_principle_bonus(worker_id=worker_id, provider_id=provider_id, repository_identity=repository_identity, principles_root=principles_root)
    bonus = min(_MODE1_HISTORY_BONUS_CAP, history_bonus + principle_bonus)
    if bonus <= 0.0:
        return proposal
    return ProgressProposal(engine=proposal.engine, payload=proposal.payload, kind=proposal.kind, confidence=min(1.0, base + bonus), evidence=tuple(proposal.evidence) + (f"verified history advisory bonus={bonus:.3f}",), requires_write=proposal.requires_write)


def _mode1_history_worker(worker_id: str, producer: Callable[[], ProgressProposal[Any]], *, request: str, provider_id: str, repository_identity: str | None = None, principles_root: str | Path | None = None):
    """Adapt one already-eligible worker with the shared advisory signal."""
    base_worker = proposal_worker(worker_id, producer)
    def worker(stop, report):
        proposal = base_worker(stop, report)
        return _mode1_apply_history_preference(proposal, request=request, worker_id=worker_id, provider_id=provider_id, repository_identity=repository_identity, principles_root=principles_root)
    return worker


def build_real_workers(
    *,
    request: str,
    workspace: str | Path,
    config: dict[str, Any],
    progress: Progress | None = None,
    shadow_registry: dict[str, Path] | None = None,
    mode: str = "execution",
    authority_context=None,
):
    """Return independently raced, capability-classed intelligence workers."""
    workspace = Path(workspace).expanduser().resolve()
    workers = {}
    repository_identity = getattr(authority_context, "target_identity", None)
    if repository_identity is None:
        try:
            from sophyane.sli_graph import _repository_memory_target
            repository_identity = _repository_memory_target(request)
        except Exception:
            repository_identity = None
    if _mode1_sli_applies(request):
        workers["sli"] = _mode1_history_worker(
            "sli",
            make_sli_producer(request=request, workspace=workspace,
                              progress=progress, shadow_registry=shadow_registry,
                              authority_context=authority_context),
            request=request, provider_id="sli_graph", repository_identity=repository_identity, principles_root=workspace,
        )
    workers["local"] = _mode1_history_worker(
        "local",
        make_provider_producer(engine="local", provider_id="local_gguf",
                               request=request, workspace=workspace, config=config,
                               progress=progress, mode=mode),
        request=request, provider_id="local_gguf", repository_identity=repository_identity, principles_root=workspace,
    )

    primary = str(config.get("provider") or "gemini").strip().lower()
    candidates = [primary]
    explicit = config.get("provider_workers") or config.get("available_providers") or ()
    candidates.extend(str(item).strip().lower() for item in explicit)
    try:
        from sophyane.startup_policy import intelligence_provider_inventory
        candidates.extend(intelligence_provider_inventory(config).keys())
    except Exception:
        pass
    seen = set()
    for provider in candidates:
        if provider in seen or provider in {"", "local", "local_gguf"}:
            continue
        seen.add(provider)
        if not _mode1_provider_available(provider, config):
            continue
        capability = _mode1_capability_class(provider)
        prefix = {"external_api": "api", "external_browser": "browser", "external_harness": "harness"}[capability]
        worker_id = f"{prefix}:{provider}"
        lane_config = dict(config)
        lane_config["provider_fallback_order"] = ()
        workers[worker_id] = _mode1_history_worker(
            worker_id,
            make_provider_producer(engine=worker_id, provider_id=provider,
                                   request=request, workspace=workspace,
                                   config=lane_config, progress=progress, mode=mode),
            request=request, provider_id=provider, repository_identity=repository_identity, principles_root=workspace,
        )
    return workers


def run_adaptive_race(
    request: str,
    *,
    workspace: str | Path,
    config: dict[str, Any],
    progress: Progress | None = None,
    timeout: float | None = 180.0,
    minimum_score: float = 0.55,
    winner_grace_seconds: float = 0.25,
    workers=None,
    mode: str = "execution",
    authority_context=None,
) -> RealRaceResult:
    """Run SLI/local/cloud concurrently and return the best valid proposal.

    This function does NOT apply a winning action to the authoritative
    workspace. Application is deliberately a separate lease-controlled stage.
    """
    workspace_path = (
        Path(workspace)
        .expanduser()
        .resolve()
    )
    if authority_context is None:
        try:
            from sophyane.sli_graph import RequestAuthorityContext, _txq_capability, _repository_memory_target
            original = str(request or "")
            authority_context = RequestAuthorityContext(
                original_objective=original,
                original_objective_hash=hashlib.sha256(original.encode("utf-8")).hexdigest(),
                target_identity=_repository_memory_target(original),
                txq_capability=_txq_capability(original),
            )
        except Exception:
            authority_context = None

    shadows: dict[
        str,
        Path,
    ] = {}

    coordinator = (
        CooperativeRace(
            workspace_path,
            minimum_score=(
                minimum_score
            ),
            winner_grace_seconds=(
                winner_grace_seconds
            ),
        )
    )

    if workers is None:
        workers = (
            build_real_workers(
                request=request,
                workspace=(
                    workspace_path
                ),
                config=config,
                progress=progress,
                shadow_registry=(
                    shadows
                ),
                mode=mode,
                authority_context=authority_context,
            )
        )

    _emit(
        progress,
        (
            "Sophyane adaptive race: "
            f"starting {len(workers)} workers"
        ),
    )

    source_classes = {}
    for name in workers:
        if name == "sli":
            source_classes[name] = "sli_graph"
        elif name == "local":
            source_classes[name] = "local_gguf"
        elif ":" in name:
            source_classes[name] = name.split(":", 1)[0].replace("api", "external_api").replace("browser", "external_browser").replace("harness", "external_harness")
        else:
            source_classes[name] = "external_api"
    objective = (getattr(authority_context, "original_objective", None) or str(request))
    objective_hash = hashlib.sha256(objective.encode("utf-8")).hexdigest()
    _emit(progress, "ORIGINAL_OBJECTIVE_HASH=" + objective_hash)
    _emit(progress, "ELIGIBLE_SOURCES=" + ",".join(f"{name}:{source_classes[name]}" for name in sorted(source_classes)))
    _emit(progress, "STARTED_SOURCES=" + ",".join(f"{name}:{source_classes[name]}" for name in sorted(workers)))

    race_result = (
        coordinator.run(
            workers,
            timeout=timeout,
        )
    )

    completed = sorted({candidate.worker for candidate in race_result.candidates})
    rejected = sorted(set(race_result.errors) - set(completed))
    _emit(progress, "COMPLETED_SOURCES=" + ",".join(f"{name}:{source_classes.get(name, 'unknown')}" for name in completed))
    _emit(progress, "REJECTED_UNUSABLE_SOURCES=" + ",".join(rejected))

    winner = (
        race_result.winner
    )

    if winner is not None:
        _emit(progress, "WINNER=" + str(winner.worker))
        _emit(progress, "WINNER_CAPABILITY_CLASS=" + source_classes.get(winner.worker, "unknown"))
        _emit(
            progress,
            (
                "Sophyane adaptive race: "
                f"winner={winner.worker} "
                f"score={winner.score:.3f} "
                f"elapsed={winner.elapsed_seconds:.3f}s"
            ),
        )

    else:
        _emit(
            progress,
            "Sophyane adaptive race: no valid winner",
        )

    return RealRaceResult(
        race_result=race_result,
        workspace=workspace_path,
        shadow_workspaces=shadows,
    )


__all__ = [
    "RaceEngineResult",
    "RealRaceResult",
    "build_real_workers",
    "make_provider_producer",
    "make_sli_producer",
    "run_adaptive_race",
]
