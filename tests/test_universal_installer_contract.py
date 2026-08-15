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


def test_posix_installer_defaults_to_stable_tag_and_validates_dependencies() -> None:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'INSTALL_REF="${SOPHYANE_REF:-}"' in text
    assert 'git ls-remote --tags --refs "$REPO" "refs/tags/v*"' in text
    assert r'refs/tags/v(\d+)\.(\d+)\.(\d+)' in text
    assert '--branch "$INSTALL_REF"' in text
    assert 'SOURCE=$INSTALL_REF' in text
    assert '"$VENV/bin/python" -m pip check' in text
    assert "import numpy" in text
    assert "import pexpect" in text
    assert "import sophyane" in text


def test_windows_installer_uses_separate_managed_runtime() -> None:
    text = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert '$SystemDir = Join-Path $Base "system"' in text
    assert '$VenvDir = Join-Path $Base "venv"' in text
    assert '$UserWork = Join-Path $Base "user-work"' in text
    assert "Previous managed version: removed after validation" in text
    assert "User state/work preserved under" in text


def test_windows_installer_defaults_to_stable_tag_and_validates_dependencies() -> None:
    text = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert '$InstallRef = $env:SOPHYANE_REF' in text
    assert 'git ls-remote --tags --refs $RepoUrl "refs/tags/v*"' in text
    assert r'refs/tags/v(\d+\.\d+\.\d+)$' in text
    assert '--branch $InstallRef' in text
    assert 'SOURCE=$InstallRef' in text
    assert '& $VenvPython -m pip check' in text
    assert "import numpy, pexpect, sophyane" in text


def test_download_page_documents_supported_upgrade_contract() -> None:
    text = (ROOT / "DOWNLOAD.md").read_text(encoding="utf-8")

    assert "replace-the-runtime, preserve-the-user" in text
    assert "newest stable semantic release tag (`vX.Y.Z`)" in text
    assert "`SOPHYANE_REF`" in text
    assert "`pip check`" in text
    assert "Current stable release: `v21.4.2`" in text

    normalized = " ".join(text.split())

    assert (
        "do not need to uninstall Sophyane manually first"
        in normalized
    )
