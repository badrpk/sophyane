from pathlib import Path
from types import SimpleNamespace

import sophyane.collaborative_workers as workers


def test_ensure_neuron_does_not_claim_nifdu_as_neuron(monkeypatch, tmp_path):
    monkeypatch.setattr(
        workers,
        "probe_neuron",
        lambda: SimpleNamespace(available=False, path=None),
    )
    monkeypatch.setattr(
        workers,
        "ensure_source_checkout",
        lambda *args, **kwargs: {
            "action": "clone",
            "path": str(tmp_path / "neuron-src"),
            "result": {"ok": True},
        },
    )

    monkeypatch.setattr(
        workers.Path,
        "home",
        classmethod(lambda cls: tmp_path / "home"),
    )
    monkeypatch.setattr(
        workers,
        "CACHE",
        tmp_path / "cache",
    )
    monkeypatch.setattr(
        workers,
        "BIN_DIR",
        tmp_path / "bin",
    )

    def fail_if_nifdu_called():
        raise AssertionError("ensure_neuron must not use NIFDU as Neuron")

    monkeypatch.setattr(
        workers,
        "ensure_nifdu",
        fail_if_nifdu_called,
    )

    result = workers.ensure_neuron()

    assert result["available"] is False
    assert result["fetched"] is True
    assert "runnable" in result["reason"]
    assert "test_neuron_capabilities" in result["reason"]
    assert len(result["steps"]) == 1


def test_ensure_neuron_preserves_existing_legacy_backend(monkeypatch):
    monkeypatch.setattr(
        workers,
        "probe_neuron",
        lambda: SimpleNamespace(
            available=True,
            path="/tmp/test_neuron_capabilities",
        ),
    )

    result = workers.ensure_neuron()

    assert result == {
        "available": True,
        "path": "/tmp/test_neuron_capabilities",
        "fetched": False,
    }


def test_ensure_nifdu_invalidates_discovery_after_build(monkeypatch, tmp_path):
    monkeypatch.setattr(
        workers,
        "probe_nifdu",
        lambda: SimpleNamespace(available=False, path=None),
    )
    monkeypatch.setattr(
        workers,
        "ensure_source_checkout",
        lambda *args, **kwargs: {
            "action": "clone",
            "path": str(tmp_path / "nifdu-src"),
            "result": {"ok": True},
        },
    )

    build_dir = tmp_path / "cache" / "nifdu-build"
    build_dir.mkdir(parents=True)
    binary = build_dir / "nifdu"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)

    monkeypatch.setattr(
        workers,
        "CACHE",
        tmp_path / "cache",
    )
    monkeypatch.setattr(
        workers,
        "BIN_DIR",
        tmp_path / "bin",
    )
    monkeypatch.setattr(
        workers,
        "_run",
        lambda *args, **kwargs: {"ok": True},
    )

    invalidations = []
    monkeypatch.setattr(
        workers,
        "invalidate_discovery",
        lambda: invalidations.append(True),
    )

    result = workers.ensure_nifdu()

    assert result["available"] is True
    assert Path(result["path"]).is_file()
    assert invalidations == [True]
