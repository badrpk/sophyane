import json
from pathlib import Path

from sophyane.ecosystem_capabilities import discover_badrpk_capabilities
from sophyane.ecosystem_contract import load_local_manifest


def write_manifest(root: Path, repository: str, *, operations=None):
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "sophyane-ecosystem-v1",
        "component": repository,
        "role": "test-peer",
        "capabilities": ["status"],
        "peers": {"sophyane": "multi-option-harness"},
        "routing": {
            "policy": "request-peer-capability-when-local-capability-is-missing",
            "transport": ["local-process"],
            "fallback": "return-explicit-capability-unavailable",
        },
    }
    if operations is not None:
        payload["operations"] = operations
    (root / "ecosystem.json").write_text(json.dumps(payload))


def test_local_manifest_preserves_explicit_safe_operations(tmp_path):
    write_manifest(
        tmp_path,
        "huobz",
        operations={
            "status": {
                "argv": ["python", "-c", "print('ok')"],
                "timeout_seconds": 5,
                "max_output_bytes": 1024,
            }
        },
    )

    manifest = load_local_manifest(tmp_path, repository="huobz")

    assert manifest is not None
    assert manifest.valid_contract is True
    assert manifest.operations[0][0] == "status"
    assert manifest.operations[0][1].argv == (
        "python",
        "-c",
        "print('ok')",
    )


def test_local_root_discovery_marks_local_manifest_ready(monkeypatch, tmp_path):
    peer_root = tmp_path / "peers"
    write_manifest(peer_root / "huobz", "huobz")
    write_manifest(peer_root / "rangoons", "rangoons")
    monkeypatch.setenv("SOPHYANE_BADRPK_ROOT", str(peer_root))
    monkeypatch.setenv("SOPHYANE_ECOSYSTEM_REMOTE", "0")

    capabilities = discover_badrpk_capabilities(workspace=tmp_path / "workspace")
    by_name = {item.repository: item for item in capabilities}

    assert by_name["huobz"].local_available is True
    assert by_name["huobz"].execution_ready is True
    assert by_name["rangoons"].local_available is True
    assert by_name["rangoons"].execution_ready is True


def test_remote_metadata_never_makes_peer_execution_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("SOPHYANE_ECOSYSTEM_REMOTE", "1")

    remote_manifest = json.dumps(
        {
            "schema": "sophyane-ecosystem-v1",
            "component": "veyron",
            "role": "webserver",
            "capabilities": ["tls"],
        }
    )

    capabilities = discover_badrpk_capabilities(
        roots=[tmp_path],
        remote_loader=lambda repository, relative: (
            remote_manifest if repository == "veyron" else ""
        ),
    )
    veyron = next(item for item in capabilities if item.repository == "veyron")

    assert veyron.remote_available is True
    assert veyron.local_available is False
    assert veyron.execution_ready is False
