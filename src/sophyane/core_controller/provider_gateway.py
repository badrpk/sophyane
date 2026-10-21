"""Policy-aware provider admission for controller mode plans."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from .models import FailureBoundary, ModeName, ModePlan, ProviderDecision, ProviderPolicy


class ConfiguredProviderGateway:
    def __init__(
        self,
        *,
        policies: Mapping[ModeName, ProviderPolicy],
        readiness: Callable[[str], bool],
    ):
        self.policies = dict(policies)
        self.readiness = readiness

    @classmethod
    def offline(cls) -> "ConfiguredProviderGateway":
        policies = {
            mode: ProviderPolicy(mode, "offline_unavailable")
            for mode in ModeName
        }
        return cls(policies=policies, readiness=lambda _provider: False)

    def admit(self, plan: ModePlan) -> ProviderDecision:
        policy = self.policies.get(plan.mode)
        if policy is None:
            return ProviderDecision(plan.trace_id, "offline_unavailable", ready=False, reason="mode policy unavailable")
        if plan.mode is ModeName.LOCAL_LLM and plan.provider_intent not in {"", policy.primary_provider}:
            return ProviderDecision(
                plan.trace_id,
                policy.primary_provider,
                fallback_chain=policy.permitted_fallbacks,
                ready=False,
                reason="local-only mode rejects external provider",
            )

        candidates = (policy.primary_provider,) + tuple(policy.permitted_fallbacks)
        reasons: list[str] = []
        for provider in candidates:
            if provider == "offline_unavailable":
                reasons.append("offline_unavailable unavailable")
                continue
            try:
                ready = bool(self.readiness(provider))
            except Exception as error:
                ready = False
                reasons.append(f"{provider} probe error: {error}")
            if ready:
                reason = ", ".join(reasons) or "primary provider ready"
                return ProviderDecision(
                    plan.trace_id,
                    provider,
                    fallback_chain=policy.permitted_fallbacks,
                    ready=True,
                    reason=reason,
                )
            reasons.append(f"{provider} unavailable")
        return ProviderDecision(
            plan.trace_id,
            policy.primary_provider,
            fallback_chain=policy.permitted_fallbacks,
            ready=False,
            reason="; ".join(reasons) or "no provider available",
        )
