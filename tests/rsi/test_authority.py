import pytest


def test_only_canonical_external_providers_can_mutate():
    from sophyane.rsi.authority import Operation, require

    for operation in Operation:
        for name in ("codex_cli", "nifdu_browser"):
            require(name, operation)

        if operation is Operation.READ_ONLY_OPERATION:
            require("local_gguf", operation)
            continue

        if operation is Operation.ORDINARY_WORKSPACE_MUTATION:
            # Exact local provider identity is intentionally permitted for
            # ordinary workspace mutation, but aliases/unknown providers are
            # never granted authority.
            require("local_gguf", operation)

            denied = (
                "LOCAL_GGUF",
                " local_gguf ",
                "local-gguf",
                "gguf",
                "gemini",
                "Codex_Cli",
                "codex",
                "",
                "unknown",
            )

            for name in denied:
                with pytest.raises(PermissionError):
                    require(name, operation)

            continue

        for name in (
            "local_gguf",
            "LOCAL_GGUF",
            " local_gguf ",
            "local-gguf",
            "gguf",
            "gemini",
            "Codex_Cli",
            "codex",
            "",
            "unknown",
        ):
            with pytest.raises(PermissionError):
                require(name, operation)


def test_local_read_only_remains_permitted():
    from sophyane.rsi.authority import Operation, require
    require('local_gguf', Operation.READ_ONLY_OPERATION)


def test_mode6_capability_stops_mutation_but_retains_operational_local(monkeypatch):
    from sophyane.rsi.authority import Operation
    from sophyane.providers.human_conversation import HumanConversationProvider
    from sophyane.providers.base import ProviderError
    wrapper = HumanConversationProvider()
    calls = []
    def create(name):
        calls.append(name)
        if name != 'local_gguf': raise ProviderError('provider unavailable')
        return object()
    monkeypatch.setattr(wrapper, '_create', create)
    with pytest.raises(ProviderError, match='DEFERRED_NO_CODING_PROVIDER'):
        wrapper.run_request(lambda p: 'mutation', operation=Operation.SOPHYANE_SOURCE_MUTATION)
    assert calls == ['codex_cli', 'nifdu_browser']
    calls.clear()
    class Local: pass
    monkeypatch.setattr(wrapper, '_create', lambda name: Local())
    assert wrapper.run_request(lambda p: 'read-only') == 'read-only'


def test_repository_execution_declares_source_capability(monkeypatch,tmp_path):
    from sophyane import human_conversation_cli as cli, main, adaptive_execution
    from sophyane.providers.human_conversation import HumanConversationProvider
    from sophyane.providers.base import ProviderError
    wrapper = HumanConversationProvider()
    calls = []
    class Local:
        def generate(self,*args): return '{"action":"write_file","path":"bad.py","content":"attack"}'
    def create(name):
        calls.append(name)
        if name != 'local_gguf': raise ProviderError('provider unavailable')
        return Local()
    monkeypatch.setattr(wrapper,'_create',create)
    monkeypatch.setattr(main,'create_provider',lambda config: wrapper)
    monkeypatch.setattr(main,'load_runtime_config',lambda: {})
    monkeypatch.setenv('SOPHYANE_SESSION_MODE','human_conversation')
    monkeypatch.setattr(adaptive_execution,'run_adaptive_loop',lambda *a,**k: pytest.fail('Unauthorized action reached executor'))
    with pytest.raises(
        ProviderError,
        match='All Mode-6 providers failed',
    ):
        cli._execute_repository_request(
            'fix source in this repository',
            workspace=tmp_path,
        )

    # The initial intelligence turn is deliberately non-mutating. If both
    # high-authority cloud providers are unavailable, execution stops here:
    # local GGUF must not receive the protected source mission and the
    # adaptive mutation executor must not run.
    assert calls == ['codex_cli', 'nifdu_browser']


def test_mode6_mutation_semantic_quota_and_persistent_probe(monkeypatch):
    from sophyane.rsi.authority import Operation
    from sophyane.providers.human_conversation import HumanConversationProvider
    from sophyane.providers.base import ProviderError
    wrapper=HumanConversationProvider()
    calls=[]
    class Fake:
        def __init__(self,name): self.name=name
        def generate(self,*args): return 'ChatGPT usage limit reached'
    def create(name):
        calls.append(name)
        if name == 'codex_cli': raise ProviderError('credits exhausted')
        return Fake(name)
    monkeypatch.setattr(wrapper,'_create',create)
    for _ in range(2):
        with pytest.raises(ProviderError,match='DEFERRED_NO_CODING_PROVIDER'):
            wrapper.generate('repair','',operation=Operation.SOPHYANE_SOURCE_MUTATION)
    assert calls == ['codex_cli','nifdu_browser']
