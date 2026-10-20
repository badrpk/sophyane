import json
import os
import sys
import time
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


def test_local_manifest_rejects_unsafe_operation_commands(tmp_path):
    write_manifest(
        tmp_path,
        "huobz",
        operations={
            "deploy": {
                "argv": ["sh", "-c", "rm -rf /"],
            }
        },
    )

    manifest = load_local_manifest(tmp_path, repository="huobz")

    assert manifest is not None
    assert manifest.valid_contract is False


def test_local_root_discovery_marks_local_manifest_ready(monkeypatch, tmp_path):
    peer_root = tmp_path / "peers"
    operation = {
        "status": {
            "argv": [sys.executable, "-c", "print('ready')"],
            "timeout_seconds": 5,
            "max_output_bytes": 1024,
        }
    }
    write_manifest(peer_root / "huobz", "huobz", operations=operation)
    write_manifest(peer_root / "rangoons", "rangoons", operations=operation)
    monkeypatch.setenv("SOPHYANE_BADRPK_ROOT", str(peer_root))
    monkeypatch.setenv("SOPHYANE_ECOSYSTEM_REMOTE", "0")

    capabilities = discover_badrpk_capabilities(workspace=tmp_path / "workspace")
    by_name = {item.repository: item for item in capabilities}

    assert by_name["huobz"].local_available is True
    assert by_name["huobz"].execution_ready is True
    assert by_name["rangoons"].local_available is True
    assert by_name["rangoons"].execution_ready is True


def test_invalid_or_unexecutable_local_manifests_are_not_execution_ready(
    tmp_path,
):
    write_manifest(
        tmp_path / "huobz",
        "huobz",
        operations={
            "status": {
                "argv": [str(tmp_path / "missing")],
                "timeout_seconds": 5,
                "max_output_bytes": 1024,
            }
        },
    )
    capabilities = discover_badrpk_capabilities(roots=[tmp_path])
    huobz = next(item for item in capabilities if item.repository == "huobz")
    assert huobz.execution_ready is False


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


def executable(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(0o700)
    return path


def adapter_for(tmp_path, argv, **kwargs):
    from sophyane.ecosystem_contract import ManifestOperation
    from sophyane.peer_process_adapter import LocalPeerProcessAdapter

    return LocalPeerProcessAdapter(
        "fixture",
        tmp_path,
        {"status": ManifestOperation(tuple(argv), **kwargs)},
    )


def test_process_adapter_runs_fixed_argv_without_shell_interpretation(tmp_path):
    script = executable(
        tmp_path / "echo_args.py",
        "import sys; print(sys.argv[1])",
    )
    adapter = adapter_for(
        tmp_path,
        [str(script), "literal; echo injected"],
    )

    result = adapter.invoke("status", "ignored objective", str(tmp_path))

    assert result.ok is True
    assert result.output.strip() == "literal; echo injected"
    assert result.evidence["exit_status"] == 0
    assert result.evidence["shell"] is False


def test_process_adapter_rejects_unknown_capability(tmp_path):
    result = adapter_for(tmp_path, [sys.executable, "-c", "print('ok')"]).invoke(
        "build", "", str(tmp_path)
    )

    assert result.handled is False
    assert result.ok is False
    assert result.evidence["reason"] == "PEER_CAPABILITY_UNSUPPORTED"


def test_process_adapter_reports_missing_executable(tmp_path):
    result = adapter_for(tmp_path, [str(tmp_path / "missing")]).invoke(
        "status", "", str(tmp_path)
    )

    assert result.handled is True
    assert result.ok is False
    assert result.evidence["reason"] == "PEER_EXECUTABLE_UNAVAILABLE"


def test_process_adapter_reports_nonzero_exit(tmp_path):
    script = executable(
        tmp_path / "fail.py",
        "import sys; print('failed'); sys.exit(7)",
    )
    result = adapter_for(tmp_path, [str(script)]).invoke("status", "", str(tmp_path))

    assert result.ok is False
    assert result.evidence["exit_status"] == 7
    assert result.output.strip() == "failed"


def test_process_adapter_bounds_timeout(tmp_path):
    script = executable(
        tmp_path / "slow.py",
        "import time; time.sleep(1)",
    )
    started = time.monotonic()
    result = adapter_for(
        tmp_path,
        [str(script)],
        timeout_seconds=0.05,
    ).invoke("status", "", str(tmp_path))

    assert time.monotonic() - started < 0.8
    assert result.ok is False
    assert result.evidence["reason"] == "PEER_COMMAND_TIMEOUT"


def test_process_adapter_bounds_output_and_sanitizes_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PEER_SECRET", "must-not-leak")
    script = executable(
        tmp_path / "output.py",
        "import os; print(os.environ.get('PEER_SECRET', 'missing')); print('x' * 5000)",
    )
    result = adapter_for(
        tmp_path,
        [str(script)],
        max_output_bytes=128,
    ).invoke("status", "", str(tmp_path))

    assert result.ok is True
    assert "must-not-leak" not in result.output
    assert len(result.output.encode()) <= 128
    assert result.evidence["output_truncated"] is True


def test_local_registration_requires_a_valid_local_operation_manifest(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SOPHYANE_ECOSYSTEM_REMOTE", "0")
    write_manifest(
        tmp_path / "huobz",
        "huobz",
        operations={
            "status": {
                    "argv": [sys.executable, "-c", "print('ready')"],
                "timeout_seconds": 5,
                "max_output_bytes": 1024,
            }
        },
    )

    from sophyane.ecosystem_peer_runtime import register_local_peer_adapters
    from sophyane.peer_capability_adapter import peer_adapter_catalog

    registered = register_local_peer_adapters(roots=[tmp_path])

    assert "huobz" in registered
    assert "huobz" in peer_adapter_catalog()


def test_local_registration_skips_missing_executable_and_clears_stale_adapter(
    tmp_path,
):
    from sophyane.ecosystem_peer_runtime import register_local_peer_adapters
    from sophyane.peer_capability_adapter import (
        peer_adapter_catalog,
        register_peer_adapter,
    )

    register_peer_adapter(
        repository="huobz",
        capabilities=("status",),
        invoker=lambda *_: None,
    )
    write_manifest(
        tmp_path / "huobz",
        "huobz",
        operations={
            "status": {
                "argv": [str(tmp_path / "missing")],
                "timeout_seconds": 5,
                "max_output_bytes": 1024,
            }
        },
    )

    register_local_peer_adapters(roots=[tmp_path])

    assert "huobz" not in peer_adapter_catalog()


def test_all_four_peer_adapters_register_and_execute_from_fixture_roots(tmp_path):
    from sophyane.ecosystem_peer_runtime import register_local_peer_adapters
    from sophyane.peer_capability_adapter import invoke_peer_capability

    repositories = {
        "veyron": "print('veyron-ready')",
        "huobz": "print('huobz-ready')",
        "rangoons": "print('rangoons-ready')",
        "shmry": "print('shmry-ready')",
    }
    for repository, output in repositories.items():
        write_manifest(
            tmp_path / repository,
            repository,
            operations={
                "status": {
                    "argv": [sys.executable, "-c", output],
                    "timeout_seconds": 5,
                    "max_output_bytes": 1024,
                }
            },
        )

    registered = register_local_peer_adapters(roots=[tmp_path])

    assert set(repositories).issubset(registered)
    for repository in repositories:
        result = invoke_peer_capability(
            repository=repository,
            capability="status",
            objective="fixture verification",
            workspace=tmp_path / repository,
        )
        assert result.handled is True
        assert result.ok is True
        assert result.evidence["exit_status"] == 0


def test_verification_script_uses_temporary_fixtures_only(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPHYANE_BADRPK_ROOT", str(tmp_path / "does-not-exist"))
    from scripts.verify_peer_devops_adapters import verify_peer_devops_adapters

    report = verify_peer_devops_adapters()

    assert report["fixture_verification"]["ok"] is True
    assert set(report["fixture_verification"]["repositories"]) == {
        "veyron",
        "huobz",
        "rangoons",
        "shmry",
    }
