from pathlib import Path
from types import SimpleNamespace

import pytest

from sophyane.rsi_terminal import build_health_reconciler, health_interval, run_health_tick


def test_health_interval_is_configurable_and_positive(monkeypatch):
    monkeypatch.setenv("SOPHYANE_RSI_HEALTH_INTERVAL_SECONDS", "2.5")
    assert health_interval() == 2.5
    monkeypatch.setenv("SOPHYANE_RSI_HEALTH_INTERVAL_SECONDS", "0")
    with pytest.raises(ValueError):
        health_interval()


def test_daemon_health_tick_uses_repository_scoped_rollback(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    inventory = SimpleNamespace(records=(SimpleNamespace(repo_id="badrpk/repo", path=str(repository), commit="commit"),))
    manager = SimpleNamespace(rollback=lambda: "rollback")
    runtime = SimpleNamespace(repository_inventory=inventory, promotion_managers={"badrpk/repo": manager})

    reconciler = build_health_reconciler(tmp_path / "state", runtime)
    result = run_health_tick(reconciler)

    assert result["status"] in {"healthy", "degraded"}
    assert result["nodes"]["badrpk/repo"]["live_commit"] == ""
    assert reconciler.status()["nodes"]["badrpk/repo"]["repository"] == str(repository.resolve())
    reconciler.close()


def test_health_reconciler_can_be_stopped_without_another_tick(tmp_path):
    runtime = SimpleNamespace(repository_inventory=SimpleNamespace(records=()), promotion_managers={})
    reconciler = build_health_reconciler(tmp_path / "state", runtime)
    reconciler.close()
    with pytest.raises(Exception):
        run_health_tick(reconciler)
