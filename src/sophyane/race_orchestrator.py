from __future__ import annotations

# SOPHYANE_REAL_THREE_WORKER_RACE_V1

import json
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


def make_sli_producer(
    *,
    request: str,
    workspace: Path,
    progress: Progress | None = None,
    shadow_registry: dict[str, Path] | None = None,
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

    def produce():
        _emit(
            progress,
            (
                f"Race {engine} worker: "
                "creating isolated provider"
            ),
        )

        provider = _single_provider(
            provider_id=provider_id,
            config=config,
        )

        _emit(
            progress,
            (
                f"Race {engine} worker: "
                "requesting proposal"
            ),
        )

        raw = _generate_provider_for_race(
            provider=provider,
            provider_id=provider_id,
            prompt=_race_user_prompt(
                request,
                workspace,
                mode=mode,
            ),
            system_prompt=_race_system_prompt(
                mode=mode,
            ),
        )

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

    return produce


def build_real_workers(
    *,
    request: str,
    workspace: str | Path,
    config: dict[str, Any],
    progress: Progress | None = None,
    shadow_registry: dict[str, Path] | None = None,
    mode: str = "execution",
    prefer_sli_only: bool = False,
):
    """Return independent race workers.

    When prefer_sli_only is True (indexing/daemon strategy), only the
    SLI worker is registered — no local GGUF or cloud round-trips.
    """
    workspace = (
        Path(workspace)
        .expanduser()
        .resolve()
    )

    workers = {
        "sli": proposal_worker(
            "sli",
            make_sli_producer(
                request=request,
                workspace=workspace,
                progress=progress,
                shadow_registry=(
                    shadow_registry
                ),
            ),
        ),
    }

    if prefer_sli_only:
        return workers

    # Local GGUF is available when its runtime can be constructed.
    workers[
        "local"
    ] = proposal_worker(
        "local",
        make_provider_producer(
            engine="local",
            provider_id="local_gguf",
            request=request,
            workspace=workspace,
            config=config,
            progress=progress,
            mode=mode,
        ),
    )

    # Cloud failure/quota is intentionally isolated to this worker.
    workers[
        "cloud"
    ] = proposal_worker(
        "cloud",
        make_provider_producer(
            engine="cloud",
            provider_id="gemini",
            request=request,
            workspace=workspace,
            config=config,
            progress=progress,
            mode=mode,
        ),
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
            )
        )

    _emit(
        progress,
        (
            "Sophyane adaptive race: "
            f"starting {len(workers)} workers"
        ),
    )

    race_result = (
        coordinator.run(
            workers,
            timeout=timeout,
        )
    )

    winner = (
        race_result.winner
    )

    if winner is not None:
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
