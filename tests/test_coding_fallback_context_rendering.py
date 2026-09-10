from __future__ import annotations

import json
from pathlib import Path

from sophyane.context_builder import ContextPacket
from sophyane.memory import MemoryStore
from sophyane.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderMetadata,
)
from sophyane.providers.fallback import FallbackProvider
from sophyane.strict_interactive_doer import StrictInteractiveCodingDoerRuntime


class RecordingProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="recording",
        display_name="Recording",
        default_model="recording",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(
        self,
        *,
        capabilities: ProviderCapabilities,
        fail: bool = False,
        result: str = "OK",
    ) -> None:
        super().__init__(
            api_key="",
            model="recording",
            timeout=30,
            temperature=0.0,
            max_tokens=4096,
        )
        self._capabilities = capabilities
        self.fail = fail
        self.result = result
        self.prompts: list[str] = []

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        self.prompts.append(prompt)

        if self.fail:
            raise RuntimeError("temporary network timeout")

        return self.result


def test_fallback_public_renderer_preserves_json_shape_per_child():
    browser = RecordingProvider(
        capabilities=ProviderCapabilities(
            provider_managed_context=True,
        ),
        fail=True,
    )
    local = RecordingProvider(
        capabilities=ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        ),
        result="LOCAL",
    )

    provider = FallbackProvider(
        [
            ("nifdu_browser", browser),
            ("local_gguf", local),
        ],
        primary="nifdu_browser",
    )

    packet = ContextPacket()
    packet.add(
        "Repository summary",
        "SUMMARY_MARKER",
        priority=100,
    )
    packet.add(
        "Large source",
        "SOURCE_BEGIN_"
        + ("X" * 6000)
        + "_SOURCE_END",
        priority=50,
    )

    def renderer(capabilities: ProviderCapabilities) -> str:
        from sophyane.context_builder import ContextBuilder

        context = ContextBuilder(
            capabilities
        ).build(packet).text

        return json.dumps(
            {
                "user_request": "repair repository",
                "persistent_and_repository_context": context,
            }
        )

    assert provider.generate_for_capabilities(
        renderer,
        "system",
    ) == "LOCAL"

    browser_payload = json.loads(browser.prompts[0])
    local_payload = json.loads(local.prompts[0])

    assert "SOURCE_END" in browser_payload[
        "persistent_and_repository_context"
    ]
    assert "SOURCE_END" not in local_payload[
        "persistent_and_repository_context"
    ]

    assert "SUMMARY_MARKER" in local_payload[
        "persistent_and_repository_context"
    ]


def test_strict_artifact_request_no_longer_has_fixed_5000_tail(
    tmp_path: Path,
) -> None:
    def backend(prompt: str, system: str) -> str:
        raise AssertionError("unexpected generation")

    runtime = StrictInteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        capabilities=ProviderCapabilities(
            provider_managed_context=True,
        ),
    )

    context = (
        "CONTEXT_BEGIN_"
        + ("C" * 9000)
        + "_CONTEXT_END"
    )

    payload = json.loads(
        runtime._artifact_fallback_request(
            "build app",
            context,
            "",
            [],
            [],
            None,
        )
    )

    assert payload["workspace_context"] == context
    assert payload["workspace_context"].startswith(
        "CONTEXT_BEGIN_"
    )
    assert payload["workspace_context"].endswith(
        "_CONTEXT_END"
    )


def test_strict_backend_capability_hook_is_used(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def backend(prompt: str, system: str) -> str:
        raise AssertionError(
            "legacy backend should not be called"
        )

    def generate_for_capabilities(
        renderer,
        system: str,
    ) -> str:
        rendered = renderer(
            ProviderCapabilities(
                context_window_tokens=1024,
                max_output_tokens=256,
            )
        )
        calls.append(rendered)
        return "HOOK_OK"

    setattr(
        backend,
        "generate_for_capabilities",
        generate_for_capabilities,
    )

    runtime = StrictInteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        capabilities=ProviderCapabilities(
            provider_managed_context=True,
        ),
    )

    runtime._coding_context_packet.add(
        "Repository summary",
        "SUMMARY",
        priority=100,
    )
    runtime._coding_context_packet.add(
        "Large file",
        "BEGIN_"
        + ("Z" * 6000)
        + "_END",
        priority=10,
    )

    result = runtime._backend_for_capabilities(
        lambda capabilities: runtime._context_for_capabilities(
            capabilities
        ),
        "system",
    )

    assert result == "HOOK_OK"
    assert calls
    assert "SUMMARY" in calls[0]
    assert "_END" not in calls[0]
