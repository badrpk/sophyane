from __future__ import annotations
import json
import re
import os

# SOPHYANE_RACE_APPLY_VERIFY_LOOP_V1

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Any, Callable

from sophyane.execution_runtime import (
    _normalize_action,
)
from sophyane.race_adapters import (
    WorkspaceWriteLease,
)
from sophyane.race_orchestrator import (
    run_adaptive_race,
)


Progress = Callable[[str], None]


@dataclass
class VerificationResult:
    ok: bool
    command: tuple[str, ...]
    returncode: int
    output: str


@dataclass
class AppliedAction:
    engine: str
    action: dict[str, Any]
    changed_paths: tuple[str, ...] = ()


@dataclass
class RaceExecutionResult:
    ok: bool
    winner: str | None = None
    applied: list[AppliedAction] = field(
        default_factory=list
    )
    verifications: list[VerificationResult] = field(
        default_factory=list
    )
    attempts: int = 0
    error: str = ""


def _emit(
    progress: Progress | None,
    message: str,
) -> None:
    if not callable(progress):
        return

    try:
        progress(
            message
        )
    except Exception:
        pass


def _safe_target(
    workspace: Path,
    relative: str,
) -> Path:
    target = (
        workspace
        / relative
    ).resolve()

    try:
        target.relative_to(
            workspace
        )
    except ValueError as exc:
        raise PermissionError(
            f"path escapes workspace: {relative}"
        ) from exc

    return target



# SOPHYANE_RACE_WORKSPACE_ENVIRONMENT_V1
def _workspace_environment(
    workspace: Path,
) -> dict[str, str]:
    """Build subprocess environment with target workspace importable."""
    workspace = (
        Path(workspace)
        .expanduser()
        .resolve()
    )

    environment = dict(
        os.environ
    )

    existing = str(
        environment.get(
            "PYTHONPATH"
        )
        or ""
    ).strip()

    parts = [
        str(workspace)
    ]

    if existing:
        parts.append(
            existing
        )

    environment[
        "PYTHONPATH"
    ] = os.pathsep.join(
        parts
    )

    return environment


def _apply_action(
    *,
    engine: str,
    action: dict[str, Any],
    workspace: Path,
    lease: WorkspaceWriteLease,
) -> AppliedAction:
    lease.assert_owner(
        engine
    )

    normalized = (
        _normalize_action(
            action
        )
    )

    if normalized is None:
        raise ValueError(
            "winner proposal is not a valid execution action"
        )

    kind = str(
        normalized.get("type")
        or ""
    ).strip().lower()

    changed: list[str] = []

    if kind == "write_file":
        relative = str(
            normalized.get("path")
            or ""
        ).strip()

        if not relative:
            raise ValueError(
                "write_file requires path"
            )

        target = _safe_target(
            workspace,
            relative,
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            str(
                normalized.get("content")
                or ""
            ),
            encoding="utf-8",
        )

        changed.append(
            str(
                target.relative_to(
                    workspace
                )
            )
        )

    elif kind == "append_file":
        relative = str(
            normalized.get("path")
            or ""
        ).strip()

        if not relative:
            raise ValueError(
                "append_file requires path"
            )

        target = _safe_target(
            workspace,
            relative,
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with target.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                str(
                    normalized.get("content")
                    or ""
                )
            )

        changed.append(
            str(
                target.relative_to(
                    workspace
                )
            )
        )

    elif kind == "mkdir":
        relative = str(
            normalized.get("path")
            or ""
        ).strip()

        if not relative:
            raise ValueError(
                "mkdir requires path"
            )

        target = _safe_target(
            workspace,
            relative,
        )

        target.mkdir(
            parents=True,
            exist_ok=True,
        )

        changed.append(
            str(
                target.relative_to(
                    workspace
                )
            )
        )

    elif kind in {
        "run",
        "shell",
        "run_command",
        "bash",
    }:
        command = str(
            normalized.get("command")
            or ""
        ).strip()

        if not command:
            raise ValueError(
                "run requires command"
            )

        completed = subprocess.run(
            command,
            cwd=workspace,
            env=_workspace_environment(
                workspace
            ),
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "action command failed: "
                + (
                    completed.stdout
                    or ""
                )[-12000:]
            )

    elif kind in {
        "respond",
        "message",
    }:
        pass

    else:
        raise ValueError(
            f"unsupported race action: {kind}"
        )

    return AppliedAction(
        engine=engine,
        action=normalized,
        changed_paths=tuple(
            changed
        ),
    )


def _verification_commands(
    workspace: Path,
) -> list[
    tuple[str, ...]
]:
    commands: list[
        tuple[str, ...]
    ] = []

    if (
        workspace
        / "pyproject.toml"
    ).exists():
        commands.append(
            (
                "python3",
                "-m",
                "compileall",
                "-q",
                ".",
            )
        )

        if (
            workspace
            / "tests"
        ).is_dir():
            commands.append(
                (
                    "pytest",
                    "-q",
                    "--disable-warnings",
                    "--maxfail=1",
                )
            )

    elif (
        workspace
        / "package.json"
    ).exists():
        commands.append(
            (
                "npm",
                "test",
                "--",
                "--runInBand",
            )
        )

    return commands


def verify_workspace(
    workspace: str | Path,
    *,
    timeout: int = 180,
) -> list[VerificationResult]:
    workspace = (
        Path(workspace)
        .expanduser()
        .resolve()
    )

    results = []

    for command in _verification_commands(
        workspace
    ):
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=_workspace_environment(
                    workspace
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )

            output = (
                completed.stdout
                or ""
            )

            results.append(
                VerificationResult(
                    ok=(
                        completed.returncode
                        == 0
                    ),
                    command=command,
                    returncode=(
                        completed.returncode
                    ),
                    output=output[
                        -24000:
                    ],
                )
            )

            if (
                completed.returncode
                != 0
            ):
                break

        except subprocess.TimeoutExpired as exc:
            results.append(
                VerificationResult(
                    ok=False,
                    command=command,
                    returncode=124,
                    output=str(exc),
                )
            )

            break

    return results


def _winner_action(
    winner,
) -> dict[str, Any] | None:
    if winner is None:
        return None

    proposal = winner.value

    payload = getattr(
        proposal,
        "payload",
        None,
    )

    if not isinstance(
        payload,
        dict,
    ):
        return None

    action = payload.get(
        "action"
    )

    if isinstance(
        action,
        dict,
    ):
        return action

    # SOPHYANE_RACE_SLI_SHADOW_PROMOTION_V1
    #
    # SLI is allowed to perform speculative mutations only inside its
    # isolated shadow workspace.  If that work wins the race, translate
    # one material shadow-file change into the same execution-action
    # contract used by local/cloud workers.  The authoritative workspace
    # is still mutated later by _apply_action under the write lease.
    if str(
        getattr(
            winner,
            "worker",
            "",
        )
    ).strip().lower() == "sli":
        shadow_value = payload.get(
            "shadow_workspace"
        )
        changed_value = payload.get(
            "changed_files"
        )

        if (
            isinstance(shadow_value, str)
            and shadow_value.strip()
            and isinstance(changed_value, (list, tuple))
        ):
            shadow = Path(
                shadow_value
            ).expanduser().resolve()

            for changed_path in changed_value:
                if not isinstance(
                    changed_path,
                    str,
                ):
                    continue

                relative = Path(
                    changed_path
                )

                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                ):
                    continue

                candidate = (
                    shadow
                    / relative
                ).resolve()

                try:
                    candidate.relative_to(
                        shadow
                    )
                except ValueError:
                    continue

                if not candidate.is_file():
                    continue

                try:
                    content = candidate.read_text(
                        encoding="utf-8"
                    )
                except (
                    OSError,
                    UnicodeError,
                ):
                    continue

                promoted = {
                    "type": "write_file",
                    "path": relative.as_posix(),
                    "content": content,
                }

                normalized = _normalize_action(
                    promoted
                )

                if normalized is not None:
                    return normalized

    return None



def _is_indexing_or_daemon_request(request: str) -> bool:
    """Requests that should not be gated on a green pytest suite."""
    text = " ".join(str(request or "").lower().split())
    markers = (
        "index",
        "indexing",
        "indexer",
        "daemon",
        "vector store",
        "vectorstore",
        "chroma",
        "faiss",
        "embedding",
        "embeddings",
        "repositoryindex",
        "repository index",
        "auto-index",
        "auto index",
        "build index",
        "rebuild index",
    )
    return any(m in text for m in markers)

from dataclasses import dataclass

@dataclass(frozen=True)
class RaceStrategy:
    """Per-request race behaviour."""
    max_rounds: int = 3
    require_executable_action: bool = True
    success_mode: str = "pytest"  # pytest | applied | plan_ok
    prefer_sli_only: bool = False


def race_strategy_for(request: str) -> RaceStrategy:
    """Derive race strategy from request class."""
    if _is_indexing_or_daemon_request(request):
        return RaceStrategy(
            max_rounds=2,
            require_executable_action=False,
            success_mode="plan_ok",
            prefer_sli_only=True,
        )
    return RaceStrategy()





# SOPHYANE_RACE_COMPLEX_CONSTRUCTION_PREDICATE_V1
def _requires_semantic_completion_judge(
    request: str,
) -> bool:
    """Whether material existence + deterministic verification is insufficient.

    Keep ordinary writes, repairs and simple artifact creation on the existing
    deterministic path. Escalate only requests that explicitly demand a
    constructed software/artifact result with multiple functional obligations.
    """

    text = " ".join(
        str(request or "").lower().split()
    )

    construction_terms = (
        "generate",
        "create",
        "build",
        "implement",
        "develop",
        "produce",
    )

    functional_terms = (
        "functional",
        "functionality",
        "derive",
        "generate",
        "parse",
        "validate",
        "mock",
        "client",
        "server",
        "backend",
        "frontend",
        "api",
        "schema",
        "specification",
        "daemon",
        "service",
        "application",
    )

    construction = any(
        term in text
        for term in construction_terms
    )

    obligations = sum(
        1
        for term in functional_terms
        if term in text
    )

    return (
        construction
        and obligations >= 2
    )

# SOPHYANE_RACE_GEMINI_SEMANTIC_COMPLETION_V1
def _semantic_completion_judgement(
    *,
    request: str,
    workspace: Path,
    changed_paths: tuple[str, ...],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Use configured Gemini provider to judge objective completion.

    This is semantic validation only. Gemini receives bounded artifact text and
    returns a compact JSON judgement. It does not mutate the workspace.
    """

    if not changed_paths:
        return {
            "available": True,
            "complete": False,
            "reason": "No material artifact paths were produced.",
            "missing": ["material output"],
        }

    artifact_parts: list[str] = []

    for relative_value in changed_paths[:8]:
        relative = Path(str(relative_value))

        if relative.is_absolute() or ".." in relative.parts:
            continue

        candidate = (workspace / relative).resolve()

        try:
            candidate.relative_to(workspace)
        except ValueError:
            continue

        if not candidate.is_file():
            continue

        try:
            source = candidate.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        artifact_parts.append(
            "FILE: "
            + relative.as_posix()
            + "\n"
            + source[:12000]
        )

    if not artifact_parts:
        return {
            "available": True,
            "complete": False,
            "reason": "No readable material artifacts were available.",
            "missing": ["readable requested artifact"],
        }

    try:
        # Reuse Sophyane's already-configured Gemini provider. The API key,
        # model, timeout and provider authority stay in the existing provider
        # layer rather than being duplicated here.
        from sophyane.race_orchestrator import _single_provider

        provider = _single_provider(
            provider_id="gemini",
            config=config,
        )

        system_prompt = (
            "You are Sophyane's semantic completion judge. "
            "Judge whether the supplied material artifact substantially "
            "satisfies the ORIGINAL USER REQUEST. "
            "Do not reward mere file existence, syntax, filenames, comments, "
            "or promises. Required functional capabilities must actually be "
            "represented in the artifact. "
            "Return ONLY strict JSON with exactly these keys: "
            '{"complete":true|false,"reason":"concise explanation",'
            '"missing":["missing requirement", "..."]}. '
            "Be conservative but fair. A task may be complete in one file or "
            "many files. Do not demand requirements the user did not request."
        )

        user_prompt = (
            "ORIGINAL USER REQUEST:\n"
            + str(request)
            + "\n\nMATERIAL ARTIFACTS:\n\n"
            + "\n\n---\n\n".join(artifact_parts)
        )

        raw = provider.generate(
            user_prompt,
            system_prompt,
        )

        raw_text = str(raw or "").strip()

        # Accept a plain JSON object or a fenced JSON response.
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()

            if lines:
                lines = lines[1:]

            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]

            raw_text = "\n".join(lines).strip()

        parsed = json.loads(raw_text)

        if not isinstance(parsed, dict):
            raise ValueError("semantic judge did not return an object")

        complete = bool(parsed.get("complete"))
        reason = str(parsed.get("reason") or "").strip()

        missing_value = parsed.get("missing")

        if isinstance(missing_value, list):
            missing = [
                str(item).strip()
                for item in missing_value
                if str(item).strip()
            ]
        else:
            missing = []

        return {
            "available": True,
            "complete": complete,
            "reason": reason,
            "missing": missing,
        }

    except Exception as exc:
        # Provider availability and semantic incompleteness are different
        # states. Never report an API outage/rate limit as if Gemini actually
        # inspected and rejected the artifact.
        return {
            "available": False,
            "complete": None,
            "reason": (
                "Semantic completion judge unavailable: "
                + str(exc)
            ),
            "missing": [],
        }


def run_race_apply_verify(
    request: str,
    *,
    workspace: str | Path,
    config: dict[str, Any],
    progress: Progress | None = None,
    max_rounds: int | None = None,
    race_timeout: float = 180.0,
    race_runner=run_adaptive_race,
    verifier=verify_workspace,
    strategy: RaceStrategy | None = None,
    semantic_judge=None,
) -> RaceExecutionResult:
    """Race -> apply one action -> deterministic verify -> repair race."""

    workspace_path = (
        Path(workspace)
        .expanduser()
        .resolve()
    )
    strategy = strategy or race_strategy_for(request)
    if max_rounds is None:
        max_rounds = strategy.max_rounds


    lease = WorkspaceWriteLease(
        workspace_path
    )

    result = RaceExecutionResult(
        ok=False
    )

    current_request = request

    # SOPHYANE_RACE_BASELINE_DIFFERENTIAL_VERIFICATION_V2
    #
    # The injected verifier is historically a post-action callback and may
    # legitimately expect generated files to exist. Do not invoke it before
    # mutation. Capture the immutable workspace baseline with Sophyane's
    # built-in deterministic verifier instead.
    #
    # When production uses verify_workspace as its verifier, baseline and
    # post-action results are directly comparable. Custom verifiers retain
    # their original post-action-only contract.
    baseline_verification = verify_workspace(
        workspace_path
    )

    def _verification_failure_signature(item):
        if item is None or item.ok:
            return None

        # SOPHYANE_RACE_BASELINE_CANONICALIZATION_V3
        #
        # Preserve deterministic failure identity while removing pytest's
        # volatile elapsed-duration rendering. An unchanged failing suite can
        # otherwise appear different solely because one run says "0.45s" and
        # the next says "0.46s".
        #
        # Do not strip exception text, test/module identity, paths, counts,
        # return codes, or arbitrary numbers.
        normalized_output = " ".join(
            str(item.output or "").split()
        )

        command = tuple(item.command)

        if any(
            str(part).endswith("pytest")
            or str(part) == "pytest"
            for part in command
        ):
            normalized_output = re.sub(
                r"(?<=\bin )\d+(?:\.\d+)?s\b",
                "<elapsed>",
                normalized_output,
            )

        return (
            command,
            int(item.returncode),
            normalized_output,
        )

    baseline_failure_signatures = {
        signature
        for signature in (
            _verification_failure_signature(item)
            for item in baseline_verification
        )
        if signature is not None
    }

    use_baseline_differential = (
        verifier is verify_workspace
    )

    # SOPHYANE_SEMANTIC_REPAIR_MATERIAL_CONTEXT_V1
    #
    # A semantic repair round must know what the preceding round
    # materially produced.  Provider workers receive a workspace path,
    # but cloud providers cannot inspect that path themselves.
    #
    # Keep the context bounded: only the paths changed by the immediately
    # preceding action, and only a compact textual prefix of each file.
    def _semantic_repair_material_context(
        changed_paths,
    ) -> str:
        sections: list[str] = []

        for relative_value in tuple(changed_paths)[:8]:
            relative = str(relative_value).strip()

            if not relative:
                continue

            candidate = (
                workspace_path
                / relative
            ).resolve()

            try:
                candidate.relative_to(
                    workspace_path
                )
            except ValueError:
                continue

            if not candidate.is_file():
                continue

            try:
                content = candidate.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                continue

            # Repair context is evidence, not another full generation
            # channel.  Bound each artifact to avoid prompt explosion.
            content = content[:6000]

            sections.append(
                "FILE: "
                + relative
                + "\n"
                + content
            )

        if not sections:
            return ""

        return (
            "\n\nCURRENT MATERIAL ARTIFACT STATE:\n"
            + "\n\n".join(sections)
        )


    for round_index in range(
        1,
        max_rounds + 1,
    ):
        result.attempts = (
            round_index
        )

        _emit(
            progress,
            (
                "Adaptive race round "
                f"{round_index}/{max_rounds}"
            ),
        )

        race = race_runner(
            current_request,
            workspace=workspace_path,
            config=config,
            progress=progress,
            timeout=race_timeout,
        )

        winner = race.winner

        if winner is None:
            result.error = (
                "race produced no valid winner"
            )
            return result

        result.winner = (
            winner.worker
        )

        action = _winner_action(
            winner
        )

        if action is None:
            # plan_ok strategy (indexing/daemon): accept strong non-action
            # proposals instead of burning remaining repair budget.
            if strategy.success_mode == "plan_ok":
                result.ok = True
                result.error = ""
                result.winner = winner.worker
                return result

            # A strong SLI acquisition/plan can win a reasoning stage
            # without yet being executable. Feed it into the next round
            # rather than falsely treating it as applied work.
            proposal = getattr(
                winner,
                "value",
                None,
            )

            current_request = (
                request
                + "\n\n"
                + "RACE CONTEXT:\n"
                + str(
                    getattr(
                        proposal,
                        "payload",
                        proposal,
                    )
                )
                + "\n\n"
                + (
                    "Produce the next executable action "
                    "needed to advance this objective."
                )
            )

            continue

        if not lease.acquire(
            winner.worker
        ):
            result.error = (
                "could not acquire workspace write lease"
            )
            return result

        try:
            applied = _apply_action(
                engine=winner.worker,
                action=action,
                workspace=workspace_path,
                lease=lease,
            )
            result.applied.append(
                applied
            )

            # SOPHYANE_RACE_MATERIAL_OUTPUT_CONTRACT_V1
            #
            # Artifact/construction requests must not succeed solely because
            # a non-material respond/message action was executed.
            #
            # Keep this deliberately narrow:
            # - plan_ok is handled earlier and retains its own semantics;
            # - direct-answer chat does not belong in apply/verify;
            # - filesystem actions expose changed_paths;
            # - run/shell actions may have externally validated effects.
            _request_text = " ".join(
                str(request or "").lower().split()
            )

            _artifact_markers = (
                "generate",
                "create",
                "build",
                "implement",
                "produce",
                "write",
                "openapi",
                "schema",
                "backend",
                "frontend",
                "stub",
                "client",
                "script",
                "artifact",
                "project",
                "application",
            )

            _artifact_request = any(
                marker in _request_text
                for marker in _artifact_markers
            )

            _applied_kind = str(
                applied.action.get("type")
                or ""
            ).strip().lower()

            if (
                _artifact_request
                and _applied_kind in {
                    "respond",
                    "message",
                }
                and not applied.changed_paths
            ):
                current_request = (
                    request
                    + "\n\n"
                    + "PREVIOUS RACE ACTION WAS NON-MATERIAL.\n"
                    + (
                        "The objective requires a concrete artifact or "
                        "material implementation result, but the applied "
                        "action only returned a response and changed no "
                        "workspace paths.\n\n"
                    )
                    + (
                        "Produce exactly one corrected executable action "
                        "that materially advances the requested artifact."
                    )
                )
                continue
        except Exception as exc:
            lease.release(
                winner.worker
            )
            current_request = (
                request
                + "\n\n"
                + "PREVIOUS RACE ACTION FAILED TO APPLY:\n"
                + str(exc)
                + "\n\n"
                + "Generate a corrected executable action."
            )
            continue
        finally:
            if (
                lease.owner
                == winner.worker
            ):
                lease.release(
                    winner.worker
                )

        # SOPHYANE_RACE_EXACT_WRITE_VERIFIED_ISOLATION_V1
        #
        # The SLI deterministic exact-write capability has already:
        #   1. parsed an explicitly exact write request,
        #   2. written inside an isolated shadow workspace,
        #   3. read the artifact back byte-for-byte,
        #   4. won the adaptive race, and
        #   5. been re-applied to the authoritative workspace under lease.
        #
        # Do not let an unrelated repository-wide pytest failure turn that
        # completed exact write into a repair prompt capable of overwriting
        # the requested bytes.
        #
        # This is deliberately provenance-gated.  Ordinary local/cloud
        # write_file actions continue through normal deterministic
        # verification.
        _winner_payload = getattr(
            getattr(
                winner,
                "value",
                None,
            ),
            "payload",
            None,
        )

        _trusted_exact_write = (
            str(
                getattr(
                    winner,
                    "worker",
                    "",
                )
                or ""
            ).strip().lower()
            == "sli"
            and isinstance(
                _winner_payload,
                dict,
            )
            and str(
                _winner_payload.get(
                    "route",
                    "",
                )
                or ""
            ).strip()
            == "deterministic_capability"
            and bool(
                _winner_payload.get(
                    "success",
                    False,
                )
            )
            and str(
                _winner_payload.get(
                    "capability",
                    "",
                )
                or ""
            ).strip()
            == "filesystem.write_exact_verified"
            and str(
                applied.action.get(
                    "type",
                    "",
                )
                or ""
            ).strip().lower()
            == "write_file"
            and bool(
                applied.changed_paths
            )
        )

        if _trusted_exact_write:
            result.ok = True
            result.error = ""
            return result

        verification = verifier(
            workspace_path
        )
        result.verifications.extend(
            verification
        )

        # SOPHYANE_RACE_SEMANTIC_COMPLETION_GATE_V3
        #
        # Deterministic verification remains authoritative and always runs
        # first. Semantic completion is an additional objective-level gate
        # only for complex construction requests.
        if (
            semantic_judge is not None
            and _requires_semantic_completion_judge(
                request
            )
            and applied.changed_paths
        ):
            semantic = semantic_judge(
                request=request,
                workspace=workspace_path,
                changed_paths=applied.changed_paths,
                config=config,
            )

            if semantic.get("available") is True:
                if semantic.get("complete") is False:
                    reason = str(
                        semantic.get("reason")
                        or "Artifact is semantically incomplete."
                    ).strip()

                    missing = semantic.get(
                        "missing"
                    )

                    if isinstance(
                        missing,
                        list,
                    ):
                        missing_text = "; ".join(
                            str(item)
                            for item in missing
                            if str(item).strip()
                        )
                    else:
                        missing_text = ""

                    current_request = (
                        request
                        + "\n\n"
                        + "SEMANTIC COMPLETION VALIDATION FAILED.\n"
                        + reason
                        + _semantic_repair_material_context(
                            applied.changed_paths
                        )
                    )

                    if missing_text:
                        current_request += (
                            "\nMissing requirements: "
                            + missing_text
                        )

                    current_request += (
                        "\n\nProduce exactly one corrected executable "
                        "action that addresses these missing requirements "
                        "while preserving correct existing work."
                    )

                    continue

            else:
                # Availability failure is not a semantic rejection.
                # Preserve existing deterministic race semantics rather than
                # fabricating a negative Gemini judgement.
                pass

        # applied / plan_ok strategies: a successfully applied action
        # is enough progress (no pytest gate).
        if strategy.success_mode in {"applied", "plan_ok"}:
            result.ok = True
            result.error = ""
            return result

        if (
            verification
            and all(
                item.ok
                for item in verification
            )
        ):
            result.ok = True
            result.error = ""
            return result

        if not verification:
            # No deterministic verifier exists for this workspace.
            # One successfully applied validated action counts as progress,
            # but not as a falsely asserted green build.
            result.ok = True
            return result

        failure = next(
            (
                item
                for item in verification
                if (
                    not item.ok
                    and (
                        not use_baseline_differential
                        or _verification_failure_signature(item)
                        not in baseline_failure_signatures
                    )
                )
            ),
            None,
        )
        if failure is None:
            result.ok = True
            return result

        current_request = (
            request
            + "\n\n"
            + "DETERMINISTIC VERIFICATION FAILED.\n"
            + "Command: "
            + " ".join(
                failure.command
            )
            + "\n"
            + "Return code: "
            + str(
                failure.returncode
            )
            + "\n"
            + "Output:\n"
            + failure.output
            + "\n\n"
            + (
                "Diagnose this failure and produce exactly "
                "one corrected executable action."
            )
        )

    result.error = (
        "maximum adaptive repair rounds exhausted"
    )

    return result


__all__ = [
    "AppliedAction",
    "RaceExecutionResult",
    "VerificationResult",
    "run_race_apply_verify",
    "verify_workspace",
]
