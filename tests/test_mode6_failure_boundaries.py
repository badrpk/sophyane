"""Additional Mode-6 error and read-only configuration boundary regressions."""
import pytest

from sophyane.providers.base import ProviderError
from sophyane.providers.human_conversation import HumanConversationProvider


@pytest.mark.parametrize('cause', [TypeError('bug'), AssertionError('bug'), PermissionError('denied')])
def test_wrapped_programming_and_authority_errors_are_terminal(monkeypatch, cause):
    calls = []
    provider = HumanConversationProvider()

    def create(name):
        calls.append(name)
        raise ProviderError('connection failed') from cause

    monkeypatch.setattr(provider, '_create', create)
    with pytest.raises(ProviderError, match='connection failed'):
        provider.generate('hello', '')
    assert calls == ['codex_cli']


def test_diagnostic_line_number_is_not_http_failure(monkeypatch):
    calls = []
    provider = HumanConversationProvider()

    def create(name):
        calls.append(name)
        raise ProviderError('internal error at line 503')

    monkeypatch.setattr(provider, '_create', create)
    with pytest.raises(ProviderError, match='line 503'):
        provider.generate('hello', '')
    assert calls == ['codex_cli']


def test_mode6_runtime_config_reads_without_initialization(monkeypatch, tmp_path):
    from sophyane import config, main

    monkeypatch.setenv('SOPHYANE_SESSION_MODE', 'human_conversation')
    monkeypatch.setenv('SOPHYANE_SESSION_PROVIDER', 'gemini')
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'missing.json')
    monkeypatch.setattr(config, 'ensure_default_llm_files', lambda: pytest.fail('initialization'))
    monkeypatch.setattr(main, 'load_config', lambda: pytest.fail('generic reader'))
    result = main.load_runtime_config()
    assert result['provider'] == 'codex_cli'
    assert result['provider_failover_order'] == ['codex_cli', 'nifdu_browser', 'local_gguf']
    assert list(tmp_path.iterdir()) == []


def test_mode6_startup_does_not_eagerly_start_saved_local_provider(monkeypatch):
    from sophyane import cli_entry

    monkeypatch.setenv('SOPHYANE_SESSION_MODE', 'human_conversation')
    monkeypatch.setattr(cli_entry, 'load_config', lambda: pytest.fail('generic reader'))
    monkeypatch.setattr('sophyane.local_server.ensure_server_background',
                        lambda: pytest.fail('eager local startup'))
    cli_entry._start_local_server_if_needed()


def test_mode6_wrapper_is_not_a_globally_selectable_provider():
    from sophyane.plugin_loader import PluginLoader

    providers = PluginLoader().discover()
    assert 'human_conversation' not in providers
    assert 'gemini' in providers
    assert {'codex_cli', 'nifdu_browser', 'local_gguf'} <= providers.keys()
