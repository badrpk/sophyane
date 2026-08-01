from __future__ import annotations

from pathlib import Path

from sophyane import tui_v2
from sophyane import runtime_filesystem_capabilities_v20 as fs


def test_mobile_scope_selects_shared_storage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    shared = tmp_path / "storage" / "shared"
    shared.mkdir(parents=True)


    monkeypatch.setattr(
        fs.Path,
        "home",
        staticmethod(lambda: tmp_path),
    )

    root, scope = fs.select_scope(
        "what is largest file in my mobile",
        tmp_path / "workspace",
    )

    assert root == shared.resolve()
    assert scope == "android_shared_storage"


def test_tui_largest_mobile_file_uses_local_capability(
    tmp_path: Path,
    monkeypatch,
) -> None:
    shared = tmp_path / "storage" / "shared"
    shared.mkdir(parents=True)

    (shared / "small.txt").write_bytes(b"x" * 10)
    (shared / "large.bin").write_bytes(b"x" * 1000)

    monkeypatch.setattr(
        fs.Path,
        "home",
        staticmethod(lambda: tmp_path),
    )

    reply = tui_v2._simple_chat_reply(
        "what is largest file in my mobile"
    )

    assert reply is not None
    assert "Largest file:" in reply
    assert "large.bin" in reply
    assert "android_shared_storage" in reply
