from __future__ import annotations

from pathlib import Path

import sophyane.race_orchestrator as race


def test_build_real_workers_has_no_sli_and_does_not_crash(
    tmp_path,
    monkeypatch,
):
    # Prevent external provider discovery/construction from becoming
    # part of this architectural registry test.
    monkeypatch.setattr(
        race,
        "_configured_local_provider",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    monkeypatch.setattr(
        race,
        "_configured_cloud_provider",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    workers = race.build_real_workers(
        request="answer hello",
        workspace=Path(tmp_path),
        config={},
        progress=lambda _message: None,
    )

    assert isinstance(workers, dict)
    assert "sli" not in workers
