"""Disabled intelligence must stop before construction, retries, or rescue."""
import pytest
from sophyane import intelligence_authority as policy

DISABLED = ('gemini', 'openai', 'anthropic', 'claude', 'xai', 'grok', 'groq',
            'openrouter', 'deepseek', 'agy', 'neuron', 'nifdu', 'browser', 'other_local')


def test_exact_active_authority():
    assert getattr(policy, 'ACTIVE_INTELLIGENCE_PROVIDERS', None) == ('codex_cli', 'nifdu_browser', 'local_gguf')
    assert getattr(policy, 'SOURCE_MUTATION_PROVIDERS', None) == ('codex_cli', 'nifdu_browser')


@pytest.mark.parametrize('name', DISABLED)
def test_disabled_authority_is_terminal(name):
    with pytest.raises(PermissionError, match='PROVIDER_DISABLED'):
        policy.assert_provider_allowed(name)


@pytest.mark.parametrize('name', ('local_gguf', *DISABLED))
def test_no_source_mutation_authority(name):
    check = getattr(policy, 'provider_allowed_for_source_mutation', None)
    assert callable(check), 'missing canonical mutation policy'
    assert check(name) is False


@pytest.mark.parametrize('name', DISABLED)
def test_disabled_plugin_rejected_before_discovery(monkeypatch, name):
    from sophyane.plugin_loader import PluginLoader
    monkeypatch.setattr(PluginLoader, 'discover', lambda self: pytest.fail('provider discovery invoked'))
    with pytest.raises(PermissionError, match='PROVIDER_DISABLED'):
        PluginLoader().create(name)


def test_stale_sli_rescue_configuration_cannot_restore_disabled():
    from sophyane.providers import fallback
    from sophyane.runtime_quality_escalation import install_quality_escalation
    install_quality_escalation()
    order = fallback.resolve_provider_order('local_gguf', llm_config={
        'quality_rescue_provider': 'gemini', 'active_provider': 'openai',
        'fallback_order': list(DISABLED), 'allow_quality_escalation': True,
    })
    assert not set(order).intersection(DISABLED)


def test_real_sli_rescue_skips_disabled_instance(monkeypatch):
    from sophyane.providers import fallback
    from sophyane.runtime_quality_escalation import install_quality_escalation
    install_quality_escalation()
    calls = []
    class Candidate:
        model = 'test'
        def __init__(self, name): self.name = name
        def generate(self, *args, **kwargs):
            calls.append(self.name)
            return 'approved artifact'
    provider = fallback.FallbackProvider([(name, Candidate(name)) for name in
        ('local_gguf', 'gemini', 'openai', 'codex_cli')], primary='local_gguf')
    provider._quality_repair_streak = 1
    monkeypatch.setattr(fallback, 'load_llm_config', lambda: {'quality_rescue_provider': 'gemini'})
    assert provider.generate('repair previous invalid artifact', '') == 'approved artifact'
    assert calls == ['codex_cli']
    assert provider.last_provider == 'codex_cli'

@pytest.mark.parametrize('name', DISABLED)
def test_factory_disabled_before_loader(monkeypatch, name):
    from sophyane import main
    monkeypatch.setattr(main, 'PluginLoader', lambda: pytest.fail('loader constructed'))
    with pytest.raises(PermissionError, match='PROVIDER_DISABLED'):
        main.create_provider({'provider': name, 'model': 'stale'})


@pytest.mark.parametrize('name', DISABLED)
def test_disabled_is_not_temporarily_available(monkeypatch, name):
    from sophyane.providers import provider_availability as availability
    monkeypatch.setattr(availability, '_load', lambda: pytest.fail('availability storage read'))
    assert availability.provider_available(name) is False
    assert availability.provider_block_info(name)['failure_class'] == 'policy_disabled'


def test_defaults_do_not_route_to_legacy():
    from sophyane.config import default_config, default_llm_config
    assert default_config()['provider'] == 'codex_cli'
    assert default_llm_config()['fallback_order'] == ['codex_cli', 'nifdu_browser', 'local_gguf']


def test_race_stale_inventory_is_filtered():
    from sophyane.race_orchestrator import _mode1_provider_order, _mode1_provider_available
    cfg = {'available_providers': list(DISABLED), 'fallback_order': list(DISABLED)}
    assert _mode1_provider_order('codex_cli', cfg) == ('codex_cli',)
    for name in DISABLED:
        assert not _mode1_provider_available(name, cfg)


@pytest.mark.parametrize('name', DISABLED)
def test_race_direct_provider_rejected_before_loader(monkeypatch, name):
    from sophyane import main
    from sophyane.race_orchestrator import _single_provider
    monkeypatch.setattr(main, 'PluginLoader', lambda: pytest.fail('loader constructed'))
    with pytest.raises(PermissionError, match='PROVIDER_DISABLED'):
        _single_provider(provider_id=name, config={})


def test_semantic_disabled_selection_leaves_state_intact():
    from types import SimpleNamespace
    from sophyane.runtime_semantic_instruction import apply_provider_preference
    tui = SimpleNamespace(config={'provider': 'codex_cli'})
    with pytest.raises(PermissionError, match='PROVIDER_DISABLED'):
        apply_provider_preference(tui, 'gemini')
    assert tui.config == {'provider': 'codex_cli'}


def test_ontology_never_invokes_gemini(monkeypatch):
    from sophyane import semantic_ontology_learner as ontology
    monkeypatch.setattr(ontology, '_gemini_propose', lambda *a: pytest.fail('Gemini invoked'))
    assert isinstance(ontology.propose_roles(['unrecognized_policy_probe'], 'probe'), dict)


def test_evolution_legacy_direct_request_rejected_before_network(monkeypatch):
    from sophyane.evolution.engine import EvolutionEngine
    engine = object.__new__(EvolutionEngine)
    monkeypatch.setattr(engine, '_gemini_key', lambda: pytest.fail('credentials read'))
    with pytest.raises(PermissionError, match='PROVIDER_DISABLED'):
        engine._gemini('probe')


def test_evolution_source_analyst_never_uses_local(monkeypatch):
    from sophyane.evolution.engine import EvolutionEngine
    from sophyane.providers.human_conversation import HumanConversationProvider
    from sophyane.providers.base import ProviderError
    engine = object.__new__(EvolutionEngine)
    calls = []
    def unavailable(self, name):
        calls.append(name)
        raise ProviderError('temporarily unavailable')
    monkeypatch.setattr(HumanConversationProvider, '_create', unavailable)
    monkeypatch.setattr(engine, '_gemini', lambda *a: pytest.fail('Gemini invoked'))
    monkeypatch.setattr(engine, '_evolution_local_llm', lambda *a, **k: pytest.fail('local analyst invoked'))
    monkeypatch.setenv('SOPHYANE_EVOLUTION_FORCE_LOCAL_ANALYST', '1')
    with pytest.raises(ProviderError, match='DEFERRED_NO_CODING_PROVIDER'):
        engine._analyst_llm('propose source changes')
    assert calls == ['codex_cli', 'nifdu_browser']
