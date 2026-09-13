"""Immutable intelligence authority for a Sophyane session.

Capability routing may decide WHAT should be done.

It must not silently change WHO is permitted to provide intelligence.
"""
from __future__ import annotations

import os

from dataclasses import asdict, dataclass
from typing import Any


ACTIVE_INTELLIGENCE_PROVIDERS = ("codex_cli", "nifdu_browser", "local_gguf")
SOURCE_MUTATION_PROVIDERS = ("codex_cli", "nifdu_browser")


def active_intelligence_providers() -> tuple[str, ...]:
    return ACTIVE_INTELLIGENCE_PROVIDERS


def provider_allowed_for_operational_intelligence(provider: str) -> bool:
    return str(provider or "").strip().casefold() in ACTIVE_INTELLIGENCE_PROVIDERS


def provider_allowed_for_source_mutation(provider: str) -> bool:
    return str(provider or "").strip().casefold() in SOURCE_MUTATION_PROVIDERS


def provider_intelligence_status(provider: str) -> str:
    return "ACTIVE" if provider_allowed_for_operational_intelligence(provider) else "PROVIDER_DISABLED"


def require_active_provider(provider: str) -> None:
    if not provider_allowed_for_operational_intelligence(provider):
        raise PermissionError(f"PROVIDER_DISABLED: {provider}")


NO_LLM_MODES = {
    "sli_graph",
    "sli_chunks",
}

LOCAL_ONLY_MODES = {
    "local_llm",
}

EXTERNAL_MODES = {
    "cloud_llm",
    "nifdu_llm",
    "codex_cli",
    "agy",
}

LEARNING_MODES = {
    "learning",
}

RACE_MODES = {
    "race",
}


@dataclass(frozen=True)
class IntelligenceAuthority:
    session_mode: str
    session_provider: str
    session_model: str
    local_reasoning_allowed: bool
    provider_switching_allowed: bool
    llm_allowed: bool
    provider_failover_order: tuple[str, ...] = ()
    bounded_provider_failover: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def current_intelligence_authority() -> IntelligenceAuthority:
    mode = str(
        os.environ.get(
            "SOPHYANE_SESSION_MODE",
            "",
        )
        or ""
    ).strip().casefold()

    provider = str(
        os.environ.get(
            "SOPHYANE_SESSION_PROVIDER",
            "",
        )
        or ""
    ).strip().casefold()

    model = str(
        os.environ.get(
            "SOPHYANE_SESSION_MODEL",
            "",
        )
        or ""
    ).strip()

    if mode in NO_LLM_MODES:
        return IntelligenceAuthority(
            session_mode=mode,
            session_provider=provider,
            session_model=model,
            local_reasoning_allowed=False,
            provider_switching_allowed=False,
            llm_allowed=False,
        )

    if mode in LOCAL_ONLY_MODES:
        return IntelligenceAuthority(
            session_mode=mode,
            session_provider=provider or "local_gguf",
            session_model=model,
            local_reasoning_allowed=True,
            provider_switching_allowed=False,
            llm_allowed=True,
        )

    if mode in EXTERNAL_MODES:
        return IntelligenceAuthority(
            session_mode=mode,
            session_provider=provider,
            session_model=model,
            local_reasoning_allowed=False,
            provider_switching_allowed=False,
            llm_allowed=True,
        )

    if mode in LEARNING_MODES:
        # Learning owns its own acquisition policy. The universal request
        # kernel must not silently substitute Local GGUF.
        return IntelligenceAuthority(
            session_mode=mode,
            session_provider=provider,
            session_model=model,
            local_reasoning_allowed=False,
            provider_switching_allowed=False,
            llm_allowed=True,
        )

    if mode == "human_conversation":
        from sophyane.providers.human_conversation import MODE6_PROVIDER_ORDER

        return IntelligenceAuthority(
            session_mode=mode,
            session_provider="codex_cli",
            session_model="codex-default",
            local_reasoning_allowed=True,
            provider_switching_allowed=False,
            llm_allowed=True,
            provider_failover_order=MODE6_PROVIDER_ORDER,
            bounded_provider_failover=True,
        )

    if mode in RACE_MODES:
        return IntelligenceAuthority(
            session_mode=mode,
            session_provider=provider,
            session_model=model,
            local_reasoning_allowed=True,
            provider_switching_allowed=True,
            llm_allowed=True,
        )

    # Backward compatibility for direct library/kernel calls outside an
    # initialized CLI session.
    return IntelligenceAuthority(
        session_mode=mode,
        session_provider=provider,
        session_model=model,
        local_reasoning_allowed=True,
        provider_switching_allowed=True,
        llm_allowed=True,
    )


def local_reasoning_allowed() -> bool:
    return (
        current_intelligence_authority()
        .local_reasoning_allowed
    )


def assert_provider_allowed(
    provider_id: str,
) -> None:
    require_active_provider(provider_id)
    authority = current_intelligence_authority()

    provider = str(
        provider_id
        or ""
    ).strip().casefold()

    if not provider:
        return

    if (
        provider == "local_gguf"
        and not authority.local_reasoning_allowed
    ):
        raise PermissionError(
            "SOPHYANE_INTELLIGENCE_AUTHORITY_VIOLATION:"
            f" mode={authority.session_mode or '<unset>'}"
            f" provider={provider}"
        )

    if authority.bounded_provider_failover:
        if provider in authority.provider_failover_order:
            return
        raise PermissionError(
            "SOPHYANE_INTELLIGENCE_AUTHORITY_VIOLATION:"
            f" mode={authority.session_mode} attempted={provider}"
        )

    if authority.provider_switching_allowed:
        return

    selected = authority.session_provider

    if not selected:
        return

    aliases = {
        "browser": "nifdu_browser",
        "chatgpt_browser": "nifdu_browser",
    }

    effective_provider = aliases.get(
        provider,
        provider,
    )

    effective_selected = aliases.get(
        selected,
        selected,
    )

    if effective_provider != effective_selected:
        raise PermissionError(
            "SOPHYANE_INTELLIGENCE_AUTHORITY_VIOLATION:"
            f" mode={authority.session_mode or '<unset>'}"
            f" selected={effective_selected}"
            f" attempted={effective_provider}"
        )


__all__ = [
    "EXTERNAL_MODES",
    "IntelligenceAuthority",
    "LEARNING_MODES",
    "LOCAL_ONLY_MODES",
    "NO_LLM_MODES",
    "RACE_MODES",
    "assert_provider_allowed",
    "current_intelligence_authority",
    "local_reasoning_allowed",
]
