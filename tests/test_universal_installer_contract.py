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
    assert "Current stable release: `v27.0.1`" in text

    normalized = " ".join(text.split())

    assert (
        "do not need to uninstall Sophyane manually first"
        in normalized
    )


def test_posix_installer_commits_core_before_optional_bootstrap() -> None:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")

    benchmark = text.index('BENCH_LOG="$TMP/install-benchmark.log"')
    publication = text.index(
        "# Publication phase.  Candidate validation above intentionally leaves the"
    )
    commit = text.index('SWAPPED=0', publication)
    local = text.index(
        'Checking hardware-fit local GGUF/runtime...',
        commit,
    )
    native = text.index(
        'Checking NIFDU/Neuron native backends...',
        commit,
    )

    assert benchmark < publication < commit < local < native

    candidate_region = text[benchmark:publication]
    assert "ensure_local_open_model" not in candidate_region
    assert "download_hf_gguf" not in candidate_region
    assert "install_llama_cpp" not in candidate_region
    assert "ensure_nifdu" not in candidate_region
    assert "ensure_neuron" not in candidate_region


def test_posix_installer_never_relocates_candidate_venv() -> None:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")

    publication = text.index(
        "# Publication phase.  Candidate validation above intentionally leaves the"
    )
    commit = text.index('SWAPPED=0', publication)

    transaction = text[publication:commit]

    assert 'mv "$CAND_VENV" "$VENV"' not in transaction
    assert 'python3 -m venv "$VENV"' in transaction
    assert '"$OLD_VENV/bin/$name"' in transaction


def test_posix_optional_bootstrap_is_nonfatal_and_uses_permanent_paths() -> None:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")

    commit = text.index('SWAPPED=0')
    tail = text[commit:]

    assert 'SOPHYANE_NATIVE_BIN="$BIN"' in tail
    assert '"$VENV/bin/python"' in tail
    assert "ensure_local_open_model" in tail
    assert "ensure_nifdu" in tail
    assert "ensure_neuron" in tail

    assert 'SOPHYANE_MODELS_DIR="$TMP/models"' not in tail
    assert 'SOPHYANE_NATIVE_BIN="$TMP/native-bin"' not in tail
    assert 'SOPHYANE_STATE_DIR="$TMP/local-state"' not in tail
    assert 'SOPHYANE_STATE_DIR="$TMP/native-state"' not in tail

    assert (
        "Sophyane core remains installed and startup can retry later."
        in tail
    )
    assert (
        "Sophyane core installation remains usable."
        in tail
    )
