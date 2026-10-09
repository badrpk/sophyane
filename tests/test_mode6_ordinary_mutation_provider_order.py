from types import SimpleNamespace

import pytest

import sophyane.rsi.coding_provider as coding_provider
from sophyane.providers.base import ProviderError
from sophyane.providers.human_conversation import (
    HumanConversationProvider,
)
from sophyane.rsi.authority import Operation


class OpenStore:
    def blocked(self, _name):
        return False

    def revalidation_due(self, _name):
        return True

    def probe(self, _name):
        pass

    def failure(self, _name, _error):
        pass

    def success(self, _name):
        pass


def provider():
    value = HumanConversationProvider({})
    value._mutation_availability = OpenStore()
    return value


def test_ordinary_workspace_mutation_stops_after_cloud_failure(
    monkeypatch,
):
    subject = provider()
    attempts = []
    constructed = []

    monkeypatch.setattr(
        coding_provider,
        "eligible_failure",
        lambda _error: True,
    )

    def create(name):
        constructed.append(name)
        assert name != "local_gguf"
        return SimpleNamespace(provider_id=name)

    monkeypatch.setattr(
        subject,
        "_create",
        create,
    )

    def request(candidate):
        attempts.append(candidate.provider_id)
        raise ProviderError(
            f"{candidate.provider_id}: unavailable"
        )

    with pytest.raises(
        ProviderError,
        match="DEFERRED_NO_CODING_PROVIDER",
    ):
        subject._run_mutation_request(
            request,
            Operation.ORDINARY_WORKSPACE_MUTATION,
            "",
        )

    assert attempts == [
        "codex_cli",
        "nifdu_browser",
    ]
    assert constructed == [
        "codex_cli",
        "nifdu_browser",
    ]
    assert subject.last_provider == ""



def test_sophyane_source_mutation_never_reaches_local(
    monkeypatch,
):
    subject = provider()
    attempts = []

    monkeypatch.setattr(
        coding_provider,
        "eligible_failure",
        lambda _error: True,
    )

    monkeypatch.setattr(
        subject,
        "_create",
        lambda name: SimpleNamespace(
            provider_id=name,
        ),
    )

    def request(candidate):
        attempts.append(candidate.provider_id)

        if candidate.provider_id == "local_gguf":
            pytest.fail(
                "local_gguf received protected source mutation"
            )

        raise ProviderError(
            f"{candidate.provider_id}: unavailable"
        )

    with pytest.raises(
        ProviderError,
        match="DEFERRED_NO_CODING_PROVIDER",
    ):
        subject._run_mutation_request(
            request,
            Operation.SOPHYANE_SOURCE_MUTATION,
            "",
        )

    assert attempts == [
        "codex_cli",
        "nifdu_browser",
    ]



def test_mode6_ordinary_mutation_availability_store_is_cloud_only(
    monkeypatch,
):
    """Mode-6 ordinary mutation must never admit local GGUF."""
    import sophyane.rsi.coding_provider as coding_provider
    from sophyane.providers.base import ProviderError
    from sophyane.providers.human_conversation import HumanConversationProvider
    from sophyane.rsi.authority import Operation

    subject = HumanConversationProvider({})
    attempts = []
    constructed = []
    availability_calls = []

    class CloudOnlyStore:
        def _check(self, name, method):
            availability_calls.append((method, name))
            assert name in {
                "codex_cli",
                "nifdu_browser",
            }

        def blocked(self, name):
            self._check(name, "blocked")
            return False

        def revalidation_due(self, name):
            self._check(name, "revalidation_due")
            return True

        def probe(self, name):
            self._check(name, "probe")

        def failure(self, name, error):
            self._check(name, "failure")

        def success(self, name):
            self._check(name, "success")

    subject._mutation_availability = CloudOnlyStore()

    monkeypatch.setattr(
        coding_provider,
        "eligible_failure",
        lambda _error: True,
    )

    def create(name):
        constructed.append(name)
        assert name != "local_gguf"
        return SimpleNamespace(provider_id=name)

    monkeypatch.setattr(subject, "_create", create)

    def request(candidate):
        attempts.append(candidate.provider_id)
        raise ProviderError(
            f"{candidate.provider_id}: unavailable"
        )

    with pytest.raises(
        ProviderError,
        match="DEFERRED_NO_CODING_PROVIDER",
    ):
        subject._run_mutation_request(
            request,
            Operation.ORDINARY_WORKSPACE_MUTATION,
            "",
        )

    assert attempts == [
        "codex_cli",
        "nifdu_browser",
    ]
    assert constructed == [
        "codex_cli",
        "nifdu_browser",
    ]
    assert availability_calls
    assert all(
        name in {"codex_cli", "nifdu_browser"}
        for _method, name in availability_calls
    )
    assert subject.last_provider == ""
