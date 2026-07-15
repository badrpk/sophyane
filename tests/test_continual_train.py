from __future__ import annotations

from pathlib import Path

from sophyane.continual.engine import (
    contribute_round,
    ensure_train_core,
    federated_aggregate,
    record_experience,
    run_local_train_step,
    train_opt_in,
    train_status,
)


def test_build_cpp_core() -> None:
    path = ensure_train_core()
    assert Path(path).exists()
    assert Path(path).stat().st_size > 1000


def test_opt_in_and_local_step() -> None:
    train_opt_in(True)
    record_experience("how do I cross-compile for aarch64?", "use g++ -march", source="test")
    result = run_local_train_step()
    assert result.get("ok") is True, result
    assert result.get("core") == "C++"
    assert Path(result["adapter_dir"], "adapter.bin").exists()


def test_federated_aggregate_and_status() -> None:
    train_opt_in(True)
    run_local_train_step()
    agg = federated_aggregate()
    assert agg.get("ok") is True, agg
    st = train_status()
    assert st.get("ok") is True
    assert st.get("local_adapter") is True
    assert st.get("opt_in") is True


def test_contribute_round() -> None:
    train_opt_in(True)
    record_experience("mesh federated train", "delta", source="test")
    # mesh may be down — round still ok if local+aggregate succeed
    out = contribute_round(publish_mesh=False)
    assert out.get("ok") is True, out
