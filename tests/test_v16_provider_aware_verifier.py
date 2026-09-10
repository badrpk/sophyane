from __future__ import annotations

import json
from pathlib import Path

from sophyane.memory import MemoryStore
from sophyane.providers.base import ProviderCapabilities
from sophyane.v16_doer import CodingDoerRuntime


def _backend(
    prompt: str,
    system: str,
) -> str:
    raise AssertionError(
        "backend generation should not run in payload tests"
    )


def _runtime(
    tmp_path: Path,
    capabilities: ProviderCapabilities,
) -> CodingDoerRuntime:
    return CodingDoerRuntime(
        backend=_backend,
        memory=MemoryStore(
            tmp_path / "memory.db"
        ),
        workspace=tmp_path,
        capabilities=capabilities,
    )


def _payload(
    runtime: CodingDoerRuntime,
    capabilities: ProviderCapabilities,
    *,
    observation: dict | None = None,
):
    return runtime._verifier_payload_for_capabilities(
        prompt="repair repository",
        objective="repair implementation",
        criteria=["tests pass"],
        history=[],
        observation=observation or {
            "status": "ok",
        },
        mechanical={
            "passed": True,
            "results": [],
        },
        repository_digest="abc123",
        git_status={
            "clean": True,
        },
        capabilities=capabilities,
    )


def test_provider_managed_verifier_keeps_complete_evidence(
    tmp_path: Path,
) -> None:
    marker = "FULL_VERIFIER_EVIDENCE_TAIL"

    capabilities = ProviderCapabilities(
        provider_managed_context=True,
    )

    runtime = _runtime(
        tmp_path,
        capabilities,
    )

    # Use observation for a deterministic large evidence block without
    # depending on execution-report implementation details.
    payload = _payload(
        runtime,
        capabilities,
        observation={
            "status": "ok",
            "detail": (
                "BEGIN_"
                + ("X" * 8000)
                + marker
            ),
        },
    )

    assert marker in json.dumps(payload)
    assert "latest_observation" in payload
    assert "execution_report" in payload
    assert "prior_steps" in payload
    assert "mechanical_verification" in payload


def test_bounded_verifier_keeps_contract_and_drops_large_optional_evidence(
    tmp_path: Path,
) -> None:
    marker = "LOCAL_OVERSIZED_OBSERVATION_TAIL"

    capabilities = ProviderCapabilities(
        context_window_tokens=1024,
        max_output_tokens=256,
    )

    runtime = _runtime(
        tmp_path,
        capabilities,
    )

    payload = _payload(
        runtime,
        capabilities,
        observation={
            "status": "ok",
            "detail": (
                "BEGIN_"
                + ("Y" * 8000)
                + marker
            ),
        },
    )

    serialized = json.dumps(payload)

    assert payload["user_request"] == "repair repository"
    assert payload["objective"] == "repair implementation"
    assert payload["success_criteria"] == ["tests pass"]
    assert "mechanical_verification" in payload
    assert "instruction" in payload

    assert marker not in serialized


def test_unknown_verifier_capacity_does_not_invent_limit(
    tmp_path: Path,
) -> None:
    marker = "UNKNOWN_VERIFIER_TAIL"

    capabilities = ProviderCapabilities()

    runtime = _runtime(
        tmp_path,
        capabilities,
    )

    payload = _payload(
        runtime,
        capabilities,
        observation={
            "detail": (
                "BEGIN_"
                + ("Z" * 7000)
                + marker
            ),
        },
    )

    assert marker in json.dumps(payload)


def test_verifier_generation_uses_capability_backend_hook(
    tmp_path: Path,
) -> None:
    rendered_prompts: list[str] = []

    def backend(
        prompt: str,
        system: str,
    ) -> str:
        raise AssertionError(
            "legacy backend should not run"
        )

    def generate_for_capabilities(
        renderer,
        system: str,
    ) -> str:
        prompt = renderer(
            ProviderCapabilities(
                context_window_tokens=1024,
                max_output_tokens=256,
            )
        )
        rendered_prompts.append(prompt)

        return json.dumps(
            {
                "goal_met": False,
                "confidence": 0.5,
                "missing_requirements": [
                    "continue"
                ],
                "next_instruction": "continue",
                "final_answer": "",
            }
        )

    setattr(
        backend,
        "generate_for_capabilities",
        generate_for_capabilities,
    )

    runtime = CodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(
            tmp_path / "memory.db"
        ),
        workspace=tmp_path,
        capabilities=ProviderCapabilities(
            provider_managed_context=True,
        ),
    )

    verdict = runtime._verify(
        "repair repository",
        "repair implementation",
        ["tests pass"],
        [],
        {
            "status": "ok",
            "detail": (
                "BEGIN_"
                + ("Q" * 8000)
                + "_LOCAL_TAIL"
            ),
        },
    )

    assert rendered_prompts

    payload = json.loads(
        rendered_prompts[0]
    )

    assert "user_request" in payload
    assert "mechanical_verification" in payload
    assert "_LOCAL_TAIL" not in rendered_prompts[0]

    assert verdict["goal_met"] is False
