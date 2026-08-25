from __future__ import annotations

from pathlib import Path

import pytest

from sophyane import sli_capability_engine as engine


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (
            "SOPHYANE_DISABLE_BROWSER_OPEN",
            "1",
        ),
        (
            "SOPHYANE_NO_AUTO_OPEN",
            "true",
        ),
        (
            "SOPHYANE_BROWSER_PREVIEW",
            "0",
        ),
    ],
)
def test_disabled_preview_never_spawns_http_server(
    monkeypatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    (
        workspace
        / "index.html"
    ).write_text(
        "<!doctype html><html><body>ok</body></html>",
        encoding="utf-8",
    )

    monkeypatch.delenv(
        "SOPHYANE_DISABLE_BROWSER_OPEN",
        raising=False,
    )
    monkeypatch.delenv(
        "SOPHYANE_NO_AUTO_OPEN",
        raising=False,
    )
    monkeypatch.delenv(
        "SOPHYANE_BROWSER_PREVIEW",
        raising=False,
    )

    monkeypatch.setenv(
        name,
        value,
    )

    def forbidden_popen(*_args, **_kwargs):
        raise AssertionError(
            "disabled preview must not spawn a server"
        )

    monkeypatch.setattr(
        engine.subprocess,
        "Popen",
        forbidden_popen,
    )

    result = engine.preview_sli_artifact(
        workspace,
    )

    assert (
        "preview is disabled"
        in result.lower()
    )


def test_enabled_preview_reaches_server_spawn(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    (
        workspace
        / "index.html"
    ).write_text(
        "<!doctype html><html><body>ok</body></html>",
        encoding="utf-8",
    )

    for name in (
        "SOPHYANE_DISABLE_BROWSER_OPEN",
        "SOPHYANE_NO_AUTO_OPEN",
        "SOPHYANE_BROWSER_PREVIEW",
    ):
        monkeypatch.delenv(
            name,
            raising=False,
        )

    class SpawnReached(RuntimeError):
        pass

    def prove_spawn(*_args, **_kwargs):
        raise SpawnReached

    monkeypatch.setattr(
        engine.subprocess,
        "Popen",
        prove_spawn,
    )

    with pytest.raises(
        SpawnReached
    ):
        engine.preview_sli_artifact(
            workspace,
        )
