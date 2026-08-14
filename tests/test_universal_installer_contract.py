from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_posix_installer_replaces_runtime_but_preserves_state() -> None:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'SYSTEM="$BASE/system"' in text
    assert 'VENV="$BASE/venv"' in text
    assert 'USER_WORK="$BASE/user-work"' in text
    assert 'rm -rf "$OLD_SYSTEM" "$OLD_VENV"' in text
    assert "Previous managed version: removed after validation" in text
    assert "User state/work: preserved" in text


def test_windows_installer_uses_separate_managed_runtime() -> None:
    text = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert '$SystemDir = Join-Path $Base "system"' in text
    assert '$VenvDir = Join-Path $Base "venv"' in text
    assert '$UserWork = Join-Path $Base "user-work"' in text
    assert "Previous managed version: removed after validation" in text
    assert "User state/work preserved under" in text


def test_download_page_documents_supported_upgrade_contract() -> None:
    text = (ROOT / "DOWNLOAD.md").read_text(encoding="utf-8")

    assert "replace-the-runtime, preserve-the-user" in text
    assert "current GitHub `main`" in text
    normalized = " ".join(
        text.split()
    )

    assert (
        "do not need to uninstall Sophyane manually first"
        in normalized
    )
