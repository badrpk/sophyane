from __future__ import annotations

import numpy as np

from sophyane.code_memory.store import ChunkStore
from sophyane.self_improve.execution_reward import ExecutionRewardEngine


def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPHYANE_HOME", str(tmp_path / "sophyane-home"))
    return ChunkStore()


def test_success_reward_updates_live_chunkstore(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    chunk = store.add_chunk("verified successful implementation", weight=1.0)

    result = ExecutionRewardEngine(store).process_reward(chunk.id, exit_code=0)

    assert result["ok"] is True
    assert result["backend"] == "chunk_store"
    assert result["old_weight"] == 1.0
    assert result["new_weight"] == 1.25
    assert store.chunks[chunk.id].weight == 1.25

    index = store.ids.index(chunk.id)
    assert np.isclose(store.weights[index], 1.25)

    reloaded = ChunkStore()
    assert reloaded.chunks[chunk.id].weight == 1.25


def test_failure_reward_updates_live_chunkstore_with_floor(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    chunk = store.add_chunk("broken implementation", weight=0.12)

    result = ExecutionRewardEngine(store).process_reward(chunk.id, exit_code=1)

    assert result["ok"] is True
    assert result["reward_applied"] == -0.15
    assert result["new_weight"] == 0.1
    assert store.chunks[chunk.id].weight == 0.1

    index = store.ids.index(chunk.id)
    assert np.isclose(store.weights[index], 0.1)


def test_missing_chunk_fails_closed_without_creating_state(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)

    result = ExecutionRewardEngine(store).process_reward("missing", exit_code=0)

    assert result["ok"] is False
    assert result["chunk_id"] == "missing"
    assert "not found" in result["error"].lower()
    assert store.ids == []


def test_reward_changes_retrieval_weight_used_for_ranking(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    chunk = store.add_chunk("same semantic candidate", weight=1.0)
    engine = ExecutionRewardEngine(store)

    index = store.ids.index(chunk.id)
    before = float(store.weights[index])

    engine.process_reward(chunk.id, exit_code=0)

    after = float(store.weights[index])

    assert before == 1.0
    assert np.isclose(after, 1.25)
    assert after > before
