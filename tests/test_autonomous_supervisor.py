import threading
from sophyane.rsi import supervisor


def test_default_supervisor_is_singleton_daemon_and_stops(tmp_path, monkeypatch):
    monkeypatch.delenv('SOPHYANE_AUTONOMOUS_RSI', raising=False)
    started = threading.Event()
    class Controller:
        def run(self, stop_event, max_cycles=None):
            started.set()
            stop_event.wait(5)
    try:
        first = supervisor.start_supervisor(controller=Controller(), state_dir=tmp_path)
        assert first is not None
        assert started.wait(1)
        second = supervisor.start_supervisor(controller=Controller(), state_dir=tmp_path)
        assert second is first and first.thread.daemon
        supervisor.stop_supervisor()
        assert not first.thread.is_alive()
    finally:
        supervisor.stop_supervisor()


def test_kill_switch_disables_startup(monkeypatch, tmp_path):
    monkeypatch.setenv('SOPHYANE_AUTONOMOUS_RSI', '0')
    assert supervisor.start_supervisor(state_dir=tmp_path) is None
    assert not list(tmp_path.iterdir())


def test_normal_main_starts_and_stops_supervisor(monkeypatch):
    import sys
    from sophyane import main as cli
    calls = []
    monkeypatch.setattr(supervisor, 'start_supervisor', lambda: calls.append('start'))
    monkeypatch.setattr(supervisor, 'stop_supervisor', lambda: calls.append('stop'))
    monkeypatch.setattr(cli, 'ensure_directories', lambda: None)
    monkeypatch.setattr(cli, 'list_providers', lambda: 'providers')
    monkeypatch.setattr(cli, 'configure_logging', lambda *a: None)
    monkeypatch.setattr(sys, 'argv', ['sophyane', '--providers'])
    assert cli.main() == 0
    assert calls == ['start', 'stop']


def test_foreground_failure_publishes_observation_and_blocks_heavy_work(tmp_path):
    from sophyane.rsi.observation_bus import autonomous_bus
    autonomous_bus.drain(256)
    controller = supervisor.default_controller(tmp_path)
    @supervisor.foreground
    def failing():
        assert controller.governor.sample().user_active
        raise RuntimeError('reproducible failure')
    import pytest
    with pytest.raises(RuntimeError):
        failing()
    assert any('reproducible failure' in o.problem for o, _ in autonomous_bus.drain())


def test_process_lock_prevents_second_owner(tmp_path):
    import fcntl
    handle = (tmp_path / 'supervisor.lock').open('a+')
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert supervisor.start_supervisor(state_dir=tmp_path) is None
    finally:
        handle.close()
