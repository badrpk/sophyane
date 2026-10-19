from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "guest/sophyane-bootstrap.sh"
SERVICE = ROOT / "guest/sophyane-bootstrap.service"
README = ROOT / "guest/README.md"
FSTAB = ROOT / "guest/sophyane-fstab"


def test_bootstrap_script_is_strict_and_argv_only():
    text = SCRIPT.read_text()

    assert "set -eu" in text
    assert "shell=False" in text
    assert "subprocess.run(command" in text
    assert "eval " not in text
    assert "sh -c" not in text


def test_bootstrap_uses_expected_mounts_and_atomic_result():
    text = SCRIPT.read_text()

    assert "sophyane-input" in text
    assert "sophyane-output" in text
    assert "task.json" in text
    assert "result.json.tmp" in text
    assert "os.replace" in text


def test_service_is_one_shot_non_restarting_and_restrictive():
    text = SERVICE.read_text()

    assert "Type=oneshot" in text
    assert "Restart=" not in text or "Restart=no" in text
    assert "NoNewPrivileges=yes" in text
    assert "PrivateNetwork=yes" in text
    assert "MemoryMax=" in text
    assert "TimeoutStartSec=" in text
    assert "sophyane-bootstrap.sh" in text


def test_guest_readme_documents_installation():
    text = README.read_text()

    assert "virt-customize" in text
    assert "9P" in text
    assert "sophyane-bootstrap.service" in text


def test_guest_fstab_mounts_both_host_shares():
    text = FSTAB.read_text()

    assert "sophyane-input /mnt/sophyane-input 9p" in text
    assert "sophyane-output /mnt/sophyane-output 9p" in text
    assert "ro" in text
