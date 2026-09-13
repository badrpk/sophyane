from datetime import datetime, timedelta, timezone
import json
import pytest


class Clock:
    value = datetime(2026, 9, 12, 18, 0, tzinfo=timezone(timedelta(hours=5)))
    def __call__(self):
        return self.value


def make_store(tmp_path):
    from sophyane.rsi.availability import AvailabilityStore
    clock = Clock()
    return AvailabilityStore(tmp_path / 'external' / 'state.json', clock=clock), clock


def test_before_exact_and_after_retry_and_restart(tmp_path):
    from sophyane.rsi.availability import AvailabilityStore
    store, clock = make_store(tmp_path)
    store.failure('codex_cli', RuntimeError('usage limit try again at 10:32 PM'))
    clock.value = clock.value.replace(hour=22, minute=31)
    assert store.blocked('codex_cli')
    restarted = AvailabilityStore(store.path, clock=clock)
    assert restarted.blocked('codex_cli')
    clock.value += timedelta(minutes=1)
    assert not restarted.blocked('codex_cli')
    clock.value += timedelta(hours=1)
    assert not restarted.blocked('codex_cli')


def test_independent_windows_and_provider_health(tmp_path):
    store, clock = make_store(tmp_path)
    store.failure('codex_cli', RuntimeError('5-hour limit reset at 19:00'))
    store.failure('codex_cli', RuntimeError('weekly limit resets tomorrow at 20:00'))
    clock.value = clock.value.replace(hour=21)
    assert store.blocked('codex_cli')
    assert not store.blocked('nifdu_browser')
    clock.value += timedelta(days=1)
    assert not store.blocked('codex_cli')


@pytest.mark.parametrize('message', ['quota', 'rate limit', 'credits', 'HTTP 429',
                                    'usage limit', '5-hour limit', 'weekly limit'])
def test_unknown_reset_uses_bounded_probe_and_stores_no_message(tmp_path, message):
    store, clock = make_store(tmp_path)
    store.probe('codex_cli')
    store.failure('codex_cli', RuntimeError(message + ' token=SECRET prompt=PRIVATE'))
    state = json.loads(store.path.read_text())['providers']['codex_cli']
    assert state['retry_at'] is None
    assert state['probe_after']
    assert state['last_probe_at'] == clock.value.isoformat()
    assert 'SECRET' not in store.path.read_text()
    assert 'PRIVATE' not in store.path.read_text()
    assert state['failure_class'] == 'quota'
    assert store.blocked('codex_cli')
    clock.value += timedelta(minutes=16)
    assert not store.blocked('codex_cli')
    store.success('codex_cli')
    assert json.loads(store.path.read_text())['providers']['codex_cli']['last_success_at']


def test_candidate_cannot_redirect_pinned_external_store(tmp_path, monkeypatch):
    store, clock = make_store(tmp_path)
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    store.assert_external(candidate)
    monkeypatch.setenv('XDG_STATE_HOME', str(candidate))
    monkeypatch.setenv('SOPHYANE_PROVIDER_AVAILABILITY_FILE', str(candidate / 'fake.json'))
    store.failure('codex_cli', RuntimeError('quota'))
    assert store.path.exists()
    assert not (candidate / 'fake.json').exists()
    from sophyane.rsi.availability import AvailabilityStore
    with pytest.raises(PermissionError):
        AvailabilityStore(candidate / 'fake.json').assert_external(candidate)


def test_corrupt_state_fails_closed_and_naive_clock_rejected(tmp_path):
    store, clock = make_store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text('{bad')
    with pytest.raises(ValueError):
        store.blocked('codex_cli')
    store.path.unlink()
    clock.value = datetime(2026, 9, 12)
    with pytest.raises(ValueError):
        store.blocked('codex_cli')


def test_old_mode6_state_is_honored_without_raw_message_retention(tmp_path):
    store, clock = make_store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps({'version': 1, 'providers': {'codex_cli': {
        'retry_at': '2026-09-12T22:32:00+05:00', 'message': 'PRIVATE',
        'failure_class': 'quota', 'observed_at': clock.value.isoformat()}}}))
    assert store.blocked('codex_cli')
    store.probe('nifdu_browser')
    assert 'PRIVATE' not in store.path.read_text()


def test_multiple_windows_in_one_observation_block_until_last(tmp_path):
    store, clock = make_store(tmp_path)
    store.failure('codex_cli',RuntimeError('5-hour limit reset at 19:00; weekly limit resets tomorrow at 20:00'))
    clock.value = clock.value.replace(hour=21)
    assert store.blocked('codex_cli')
    clock.value += timedelta(days=1)
    assert not store.blocked('codex_cli')


def test_explicit_timezone_clock_is_not_misread_as_system_local(tmp_path):
    store, clock = make_store(tmp_path)
    store.failure('codex_cli',RuntimeError('quota reset at 19:00 UTC'))
    clock.value = clock.value.replace(hour=20)
    assert store.blocked('codex_cli')  # 19:00 UTC is midnight in +05:00


def test_legacy_probe_deadline_is_not_dropped(tmp_path):
    store,clock = make_store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps({'version':1,'providers':{'codex_cli':{
        'probe_after':'2099-01-01T00:00:00+00:00'}}}))
    assert store.blocked('codex_cli')


@pytest.mark.parametrize('state', [{'version':999,'providers':{}},
    {'version':2,'providers':{'codex_cli':{'probe_after':'2099-01-01T00:00:00+00:00'}}}])
def test_unsupported_or_incomplete_state_fails_closed(tmp_path,state):
    store,clock=make_store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps(state))
    with pytest.raises(ValueError): store.blocked('codex_cli')
