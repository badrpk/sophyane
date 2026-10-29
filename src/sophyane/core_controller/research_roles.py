"""Adapters that expose existing Sophyane modes as research roles."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable

from .research_portfolio import (
    ResearchArtifact,
    ResearchInput,
    ResearchPortfolioResult,
    ResearchRole,
    SkippedRole,
    _safe_error,
)


@dataclass(frozen=True, slots=True)
class ResearchRoleBundle:
    roles: tuple[ResearchRole, ...]
    learning_sink: Callable[[ResearchPortfolioResult], None] | None
    skipped_roles: tuple[SkippedRole, ...] = ()


def _provider_identity(provider: object, fallback: str) -> str:
    chain = getattr(provider, "chain", ())
    if chain:
        return f"mode6-cascade:{','.join(str(item) for item in chain)}"
    metadata = getattr(provider, "metadata", None)
    provider_name = str(
        getattr(provider, "provider_id", "")
        or getattr(metadata, "provider_id", "")
        or fallback
    )
    model = str(getattr(provider, "model", "") or "default")
    return f"{provider_name}:{model}"


def _provider_route_keys(provider: object, provider_id: str) -> tuple[str, ...]:
    chain = tuple(getattr(provider, "chain", ()) or ())
    if not chain:
        return (provider_id.split(":", 1)[0],)
    return tuple(str(name) for name in chain)


def _answer_prompt(request: ResearchInput) -> str:
    sections = [request.question]
    if request.evidence:
        evidence = "\n".join(
            f"[{index}] {item.content}\nSources: {', '.join(item.citations) or 'none recorded'}"
            for index, item in enumerate(request.evidence, 1)
        )
        sections.append("\nSource evidence (use with attribution):\n" + evidence)
    if request.prior_artifacts:
        prior = "\n".join(
            f"Submission from {item.role_id}:\n{item.content}"
            for item in request.prior_artifacts
        )
        sections.append(
            "\nIndependent peer work to review. Identify unsupported steps, "
            "counterexamples, and disagreements; do not claim your peer's work as your own:\n"
            + prior
        )
    return "\n".join(sections)


def _model_role(
    *, role_id: str, kind: str, provider: object, provider_id: str, external: bool,
    available: bool = True, unavailable_reason: str = "provider unavailable",
    route_keys: tuple[str, ...] = (),
) -> ResearchRole:
    from sophyane.runtime_cancel import (
        bind_generation,
        cancel_generation,
        new_generation,
        release_generation,
    )

    active_tokens = set()
    token_lock = Lock()

    def run(request: ResearchInput) -> ResearchArtifact:
        generate = getattr(provider, "generate", None)
        if not callable(generate):
            raise TypeError("research provider must expose generate(prompt, system_prompt)")
        token = new_generation()
        bind_generation(token)
        with token_lock:
            active_tokens.add(token)
        try:
            response = generate(
                    _answer_prompt(request),
                    "Work as a research analyst. Show assumptions and derivations, "
                    "check equations, identify uncertainty, and never claim execution, "
                    "proof, or verification that was not performed.",
                )
            content = str(response)
            resolved_provider = str(getattr(response, "provider_id", "") or "")
            if not resolved_provider:
                resolved_provider = str(getattr(provider, "last_provider", "") or "")
            resolved_model = str(getattr(response, "model", "") or "")
            if not resolved_model and resolved_provider:
                route_models = getattr(provider, "route_models", {})
                if isinstance(route_models, dict):
                    resolved_model = str(route_models.get(resolved_provider) or "")
            if not resolved_model and not resolved_provider:
                resolved_model = str(getattr(provider, "model", "") or "unknown")
            return ResearchArtifact(
                role_id=role_id,
                provider_id=resolved_provider or provider_id,
                content=content,
                resolved_model=resolved_model or "unknown",
            )
        finally:
            with token_lock:
                active_tokens.discard(token)
            release_generation(token)

    def cancel() -> None:
        provider_cancel = getattr(provider, "cancel", None)
        if callable(provider_cancel):
            try:
                provider_cancel()
            except Exception:
                pass
        with token_lock:
            tokens = tuple(active_tokens)
        for token in tokens:
            cancel_generation(token)

    return ResearchRole(
        role_id=role_id,
        kind=kind,
        provider_id=provider_id,
        run=run,
        external=external,
        available=available,
        unavailable_reason=unavailable_reason,
        cancel=cancel,
        route_keys=route_keys or (provider_id,),
    )


def _local_ready() -> bool:
    try:
        from sophyane.local_runtime import llama_server_reachable

        return bool(llama_server_reachable())
    except Exception:
        return False


def _default_local_provider_factory() -> object:
    from sophyane.config import CONFIG_FILE, load_json
    from sophyane.intelligence_authority import current_intelligence_authority
    from sophyane.providers.local_gguf import LocalGgufProvider

    config = load_json(CONFIG_FILE)
    authority = current_intelligence_authority()
    timeout = min(170, int(config.get("timeout", 180)))
    return LocalGgufProvider(
        model=authority.session_model or str(config.get("model") or "local-gguf"),
        timeout=timeout,
        temperature=float(config.get("temperature", 0.3)),
        max_tokens=int(config.get("max_tokens", 4096)),
    )


def _default_external_provider_factory() -> object:
    """Construct the selected external route without switching session policy."""
    from sophyane.intelligence_authority import current_intelligence_authority

    authority = current_intelligence_authority()
    mode = authority.session_mode
    if mode in {"local_llm", "sli_graph", "sli_chunks"} or not authority.llm_allowed:
        raise PermissionError("the active session policy forbids external providers")
    if mode == "human_conversation":
        from sophyane.providers.human_conversation import HumanConversationProvider, mode6_config

        return HumanConversationProvider({**mode6_config(), "research_isolated": True})

    provider_id = authority.session_provider
    if mode == "agy":
        provider_id = provider_id or "agy"
    elif mode == "nifdu_llm":
        provider_id = provider_id or "nifdu_browser"
    elif mode == "codex_cli":
        provider_id = provider_id or "codex_cli"
    else:
        from sophyane.config import CONFIG_FILE, load_json

        config = load_json(CONFIG_FILE)
        provider_id = provider_id or str(config.get("provider") or "codex_cli")

    if provider_id == "local_gguf":
        raise PermissionError("the configured provider route is local-only")
    if provider_id == "nifdu_browser":
        raise PermissionError(
            "NIFDU research is unavailable until a dedicated isolated conversation is supported"
        )
    from sophyane.config import CONFIG_FILE, get_secret, load_json
    from sophyane.plugin_loader import PluginLoader

    config = load_json(CONFIG_FILE)
    loader = PluginLoader()
    provider_class = loader.discover().get(provider_id)
    if provider_class is None:
        raise RuntimeError(f"configured external provider is unavailable: {provider_id}")
    metadata = provider_class.metadata
    api_key = get_secret(provider_id, metadata.environment_variable) if metadata.requires_api_key else ""
    return loader.create(
        provider_id,
        api_key=api_key,
        model=authority.session_model or str(config.get("model") or metadata.default_model),
        timeout=min(170, int(config.get("timeout", 180))),
        temperature=float(config.get("temperature", 0.3)),
        max_tokens=int(config.get("max_tokens", 4096)),
        **({"persist_session": False} if provider_id == "codex_cli" else {}),
    )


def _sli_evidence(question: str) -> object:
    from sophyane.sli_graph import SLIState, try_grounded_knowledge

    # Run only SLI's textual evidence retrieval stage. The full graph can
    # route arbitrary prompts into artifact execution, promotion, or learning.
    with tempfile.TemporaryDirectory(prefix="sophyane-research-sli-") as directory:
        state = SLIState(request=question, workspace=str(Path(directory)), route="general_knowledge")
        return try_grounded_knowledge(state, lambda _message: None)


def _citations(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(sorted(set(re.findall(r"https?://[^\s\])}>]+", value))))
    if isinstance(value, (tuple, list, set)):
        return tuple(sorted({item for child in value for item in _citations(child)}))
    if isinstance(value, dict):
        return tuple(sorted({item for child in value.values() for item in _citations(child)}))
    return ()


def _evidence_role(provider: Callable[[str], object]) -> ResearchRole:
    role_id = "mode2-sli"
    provider_id = "sli_graph:source-retrieval"

    def run(request: ResearchInput) -> ResearchArtifact:
        state = provider(request.question)
        report = getattr(state, "report", state)
        meta = getattr(state, "meta", {})
        content = str(report or "")
        citations = tuple(sorted(set(_citations(content)).union(_citations(meta))))
        return ResearchArtifact(
            role_id=role_id,
            provider_id=provider_id,
            content=content,
            citations=citations,
        )

    return ResearchRole(
        role_id=role_id,
        kind="evidence",
        provider_id=provider_id,
        run=run,
        # SLI Graph can use internet acquisition. The coordinator therefore
        # requires the same explicit opt-in as other external calls.
        external=True,
    )


def _observation_sink(result: ResearchPortfolioResult) -> None:
    """Send only the coordinator's checked, artifact-free learning view."""
    report = result.verification
    source_checked = bool(
        report.citations and report.citations_verified and report.authoritative_sources
    )
    deterministic_checked = bool(
        report.deterministic_checks and report.deterministic_checks_passed
    )
    if (
        result.status.value not in {"established", "partial"}
        or not result.learning_summary
        or result.artifacts
        or not report.supported_claims
        or not (source_checked or deterministic_checked)
    ):
        return
    from sophyane.rsi.observation_bus import (
        ImprovementObservation,
        ImprovementSource,
        autonomous_bus,
    )

    autonomous_bus.submit(
        ImprovementObservation(
            source=ImprovementSource.DIAGNOSTIC,
            problem=result.question,
            component="sophyane.research_portfolio",
            evidence=(result.learning_summary,),
            suggested_direction="Untrusted checked observation; human review required before any changes.",
        )
    )


def build_research_roles(
    *,
    allow_external: bool,
    local_provider_factory: Callable[[], object] | None = None,
    external_provider_factory: Callable[[], object] | None = None,
    evidence_provider: Callable[[str], object] | None = None,
    learning_sink: Callable[[ResearchPortfolioResult], None] | None = None,
    local_readiness: Callable[[], bool] | None = None,
    external_readiness: Callable[[], bool] | None = None,
) -> ResearchRoleBundle:
    """Build local and, only after invocation opt-in, external research roles."""
    if local_provider_factory is None:
        local_provider_factory = _default_local_provider_factory
    if external_provider_factory is None:
        external_provider_factory = _default_external_provider_factory

    from sophyane.intelligence_authority import current_intelligence_authority

    authority = current_intelligence_authority()
    session_forbids_external = (
        not authority.llm_allowed
        or authority.session_mode in {"local_llm", "sli_graph", "sli_chunks"}
    )
    external_role_id = (
        "mode6-conversation"
        if authority.session_mode == "human_conversation"
        else "mode4-external"
    )

    roles: list[ResearchRole] = []
    skipped_roles: list[SkippedRole] = []
    if authority.local_reasoning_allowed:
        try:
            local_provider = local_provider_factory()
            local_provider_id = _provider_identity(local_provider, "local_gguf")
            try:
                local_available = bool(local_readiness()) if local_readiness else _local_ready()
            except Exception:
                local_available = False
            local_reason = "" if local_available else "local provider is not ready"
        except Exception as error:
            local_provider = object()
            local_provider_id = "local_gguf:unavailable"
            local_available = False
            local_reason = f"local provider setup failed: {_safe_error(error)}"
        roles.append(
            _model_role(
                role_id="mode3-local",
                kind="solver",
                provider=local_provider,
                provider_id=local_provider_id,
                external=False,
                available=local_available,
                unavailable_reason=local_reason,
                route_keys=_provider_route_keys(local_provider, local_provider_id),
            )
        )
    else:
        skipped_roles.append(SkippedRole("mode3-local", "blocked by session intelligence policy"))

    if allow_external and not session_forbids_external:
        try:
            external_provider = external_provider_factory()
            external_provider_id = _provider_identity(external_provider, "external_llm")
            try:
                external_available = bool(external_readiness()) if external_readiness else True
            except Exception:
                external_available = False
            external_reason = "" if external_available else "external provider is not ready"
        except Exception as error:
            external_provider = object()
            external_provider_id = "external_llm:unavailable"
            external_available = False
            external_reason = f"external provider setup failed: {_safe_error(error)}"
        roles.append(
            _model_role(
                role_id=external_role_id,
                kind="solver",
                provider=external_provider,
                provider_id=external_provider_id,
                external=True,
                available=external_available,
                unavailable_reason=external_reason,
                route_keys=_provider_route_keys(external_provider, external_provider_id),
            )
        )
        roles.append(_evidence_role(evidence_provider or _sli_evidence))
    elif not allow_external:
        skipped_roles.extend(
            (
                SkippedRole("mode2-sli", "external research not allowed"),
                SkippedRole(external_role_id, "external research not allowed"),
            )
        )
    else:
        skipped_roles.extend(
            (
                SkippedRole("mode2-sli", "blocked by local-only session policy"),
                SkippedRole(external_role_id, "blocked by local-only session policy"),
            )
        )

    return ResearchRoleBundle(
        roles=tuple(roles),
        learning_sink=learning_sink or _observation_sink,
        skipped_roles=tuple(skipped_roles),
    )
