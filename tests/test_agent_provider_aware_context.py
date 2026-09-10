import logging

from sophyane.agent import SophyaneAgent
from sophyane.providers.base import ProviderCapabilities


class FakeMemory:
    def __init__(
        self,
        *,
        relevant: str,
        recent: list[dict[str, str]],
        captured: list[str] | None = None,
    ) -> None:
        self.relevant = relevant
        self.recent = recent
        self.captured = list(
            captured
            or []
        )

    def record_message(
        self,
        role: str,
        content: str,
    ) -> None:
        return None

    def auto_capture(
        self,
        message: str,
    ) -> list[str]:
        return list(
            self.captured
        )

    def format_relevant(
        self,
        query: str,
    ) -> str:
        return self.relevant

    def recent_messages(
        self,
        limit: int = 4,
    ) -> list[dict[str, str]]:
        return self.recent[-limit:]


class FakeProvider:
    def __init__(
        self,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def get_capabilities(
        self,
    ) -> ProviderCapabilities:
        if self.capabilities is None:
            return ProviderCapabilities()

        return self.capabilities

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        self.prompts.append(prompt)
        self.systems.append(system_prompt)
        return "ok"


def make_agent(
    provider,
    memory,
):
    return SophyaneAgent(
        provider,
        memory,
        logging.getLogger(
            "provider-aware-context-test"
        ),
    )


def test_browser_managed_chat_preserves_full_memory_history_and_request():
    memory_begin = (
        "MEMORY_BEGIN_"
        + ("M" * 2500)
    )
    memory_end = (
        ("N" * 2500)
        + "_MEMORY_END"
    )
    memory_context = (
        memory_begin
        + memory_end
    )

    history_content = (
        "HISTORY_BEGIN_"
        + ("H" * 3000)
        + "_HISTORY_END"
    )

    request = (
        "REQUEST_BEGIN_"
        + ("R" * 5000)
        + "_REQUEST_END"
    )

    memory = FakeMemory(
        relevant=memory_context,
        recent=[
            {
                "role": "assistant",
                "content": history_content,
            },
            {
                "role": "user",
                "content": request,
            },
        ],
    )

    provider = FakeProvider(
        ProviderCapabilities(
            provider_managed_context=True,
            provider_managed_output=True,
        )
    )

    agent = make_agent(
        provider,
        memory,
    )

    response = agent.ask(
        request
    )

    assert response.text == "ok"
    assert len(provider.prompts) == 1

    prompt = provider.prompts[0]

    assert "MEMORY_BEGIN_" in prompt
    assert "_MEMORY_END" in prompt
    assert "HISTORY_BEGIN_" in prompt
    assert "_HISTORY_END" in prompt
    assert "REQUEST_BEGIN_" in prompt
    assert "_REQUEST_END" in prompt


def test_numeric_provider_can_drop_optional_context_but_keeps_request():
    request = (
        "IMMUTABLE_REQUEST_"
        + ("R" * 900)
        + "_END_REQUEST"
    )

    memory = FakeMemory(
        relevant=(
            "OPTIONAL_MEMORY_"
            + ("M" * 5000)
        ),
        recent=[
            {
                "role": "assistant",
                "content": (
                    "OPTIONAL_HISTORY_"
                    + ("H" * 5000)
                ),
            },
            {
                "role": "user",
                "content": request,
            },
        ],
    )

    provider = FakeProvider(
        ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        )
    )

    agent = make_agent(
        provider,
        memory,
    )

    response = agent.ask(
        request
    )

    assert response.text == "ok"

    prompt = provider.prompts[0]

    assert "IMMUTABLE_REQUEST_" in prompt
    assert "_END_REQUEST" in prompt

    assert (
        "OPTIONAL_MEMORY_" not in prompt
        or "OPTIONAL_HISTORY_" not in prompt
    )


def test_newly_captured_memory_has_priority_over_old_history():
    request = "CURRENT_REQUEST"

    memory = FakeMemory(
        relevant="",
        recent=[
            {
                "role": "assistant",
                "content": (
                    "OLD_HISTORY_"
                    + ("H" * 3000)
                ),
            },
            {
                "role": "user",
                "content": request,
            },
        ],
        captured=[
            (
                "NEW_CAPTURE_"
                + ("C" * 900)
            )
        ],
    )

    provider = FakeProvider(
        ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        )
    )

    agent = make_agent(
        provider,
        memory,
    )

    agent.ask(
        request
    )

    prompt = provider.prompts[0]

    assert "CURRENT_REQUEST" in prompt
    assert "NEW_CAPTURE_" in prompt
    assert "OLD_HISTORY_" not in prompt


def test_legacy_duck_typed_provider_without_capabilities_still_works():
    class LegacyProvider:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def generate(
            self,
            prompt: str,
            system_prompt: str,
        ) -> str:
            self.prompts.append(
                prompt
            )
            return "legacy-ok"

    provider = LegacyProvider()

    memory = FakeMemory(
        relevant="MEMORY",
        recent=[
            {
                "role": "user",
                "content": "hello",
            }
        ],
    )

    agent = make_agent(
        provider,
        memory,
    )

    response = agent.ask(
        "hello"
    )

    assert response.text == "legacy-ok"
    assert "hello" in provider.prompts[0]


def test_invalid_capability_result_is_treated_conservatively():
    class BadCapabilityProvider(FakeProvider):
        def get_capabilities(self):
            return {
                "context_window_tokens": 1,
            }

    provider = BadCapabilityProvider()

    memory = FakeMemory(
        relevant="RELEVANT_MEMORY",
        recent=[
            {
                "role": "user",
                "content": "hello",
            }
        ],
    )

    agent = make_agent(
        provider,
        memory,
    )

    response = agent.ask(
        "hello"
    )

    assert response.text == "ok"
    assert "RELEVANT_MEMORY" in provider.prompts[0]
    assert "hello" in provider.prompts[0]
