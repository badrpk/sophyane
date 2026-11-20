from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from sophyane.remote_runner_executors import (
    BoundedCommandRunner,
    CommandResult,
    DockerComposeDeploymentExecutor,
    QemuFastAPIExecutor,
)


_TEST_SSH_HOST_KEY_BLOB = base64.b64encode(
    len(b"ssh-ed25519").to_bytes(4, "big") + b"ssh-ed25519"
    + (32).to_bytes(4, "big") + bytes(range(32))
).decode("ascii")
_TEST_SSH_HOST_KEY = f"ssh-ed25519 {_TEST_SSH_HOST_KEY_BLOB}"


@pytest.mark.skipif(
    not hasattr(sys, "getandroidapilevel") or shutil.which("qemu-img") is None,
    reason="Termux qemu-img address-space regression",
)
def test_qemu_img_overlay_has_bounded_data_and_android_address_space(tmp_path):
    image = tmp_path / "base.qcow2"
    overlay = tmp_path / "overlay.qcow2"
    created = subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", str(image), "12G"],
        capture_output=True, text=True, check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr

    executor = QemuFastAPIExecutor(image, "0" * 64)
    runner = executor._qemu_img_command_runner()
    assert isinstance(runner, BoundedCommandRunner)
    assert runner.memory_bytes == 2 * 1024**3
    assert runner.address_space_bytes == 16 * 1024**3
    assert runner.process_limit == 512

    result = runner(
        ["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", str(image), str(overlay)],
        cwd=tmp_path, env=dict(os.environ), cancel=threading.Event(),
    )
    assert result.exit_code == 0, result.stdout
    assert overlay.is_file()


class SuccessfulCommandRunner:
    timeout = 60

    def __init__(self):
        self.commands = []

    def __call__(self, argv, *, cwd, env, cancel):
        self.commands.append((list(argv), dict(env)))
        if "config" in argv and "--format" in argv:
            if (cwd / ".sophyane-resource-override.yaml").exists():
                override = (cwd / ".sophyane-resource-override.yaml").read_text()
                host_port = re.search(r"127\.0\.0\.1:(\d+):8000", override).group(1)
                config = {
                    "services": {
                        "database": {"image": "postgres:16-alpine", "ports": [], "volumes": [], "cpus": 1.0, "mem_limit": "1g", "pids_limit": 128},
                        "api": {"build": {"context": str(cwd)}, "ports": [
                            {"host_ip": "127.0.0.1", "published": host_port, "target": 8000}], "volumes": [], "cpus": 1.0, "mem_limit": "1g", "pids_limit": 128},
                        "worker": {"build": {"context": str(cwd)}, "ports": [], "volumes": [], "cpus": 1.0, "mem_limit": "1g", "pids_limit": 128},
                    },
                    "networks": {"default": {"internal": True}},
                }
            else:
                config = {"services": {
                    "database": {"image": "postgres:16-alpine"},
                    "api": {"build": {"context": str(cwd)}, "ports": [{"target": 8000}]},
                    "worker": {"build": {"context": str(cwd)}},
                }}
            return CommandResult(list(argv), 0, json.dumps(config), "", 0.01)
        if "ps" in argv and "--format" in argv:
            return CommandResult(list(argv), 0, json.dumps([
                {"Service": "api", "State": "running", "Health": "healthy"},
                {"Service": "database", "State": "running", "Health": "healthy"},
            ]), "", 0.01)
        output = "1\n" if "-Atc" in argv else ""
        return CommandResult(list(argv), 0, output, "", 0.01)


def test_docker_executor_runs_health_restart_persistence_and_owned_cleanup(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    runner = SuccessfulCommandRunner()
    executor = DockerComposeDeploymentExecutor(
        command_runner=runner, http_get=lambda url, timeout: (200, b'{"status":"ok"}'),
        health_timeout=0,
    )
    # A zero health window performs one HTTP check and returns immediately.
    executor.health_timeout = 1
    outcome = executor(tmp_path, {"job_id": "job-" + "a" * 32}, threading.Event())
    labels = [row["label"] for row in outcome["commands"]]
    assert outcome["passed"] is True, outcome
    assert "api-health" in labels
    assert "postgres-volume-persistence" in labels
    assert labels[-1] == "compose-cleanup-remove-owned-volumes"
    assert any("down" in argv and "--volumes" in argv for argv, _ in runner.commands)
    assert all(env["COMPOSE_DISABLE_ENV_FILE"] == "1" for _, env in runner.commands)
    assert "docker-compose-results.json" in outcome["artifacts"]


def test_qemu_executor_pins_image_limits_guest_and_checks_http_from_host(tmp_path, monkeypatch):
    image = tmp_path / "guest.qcow2"
    image.write_bytes(b"pinned guest image")
    image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    runner = SuccessfulCommandRunner()

    class FakeProcess:
        pid = 999999
        returncode = 0

        def __init__(self, argv, **kwargs):
            self.argv = argv
            output_path = next(arg.split("path=", 1)[1].split(",", 1)[0]
                               for arg in argv if "mount_tag=sophyane-output" in arg)
            type(self).output_path = Path(output_path)
            type(self).runner_env = (Path(output_path) / "runner.env").read_text(encoding="utf-8")
            type(self).runner_env_mode = stat.S_IMODE((Path(output_path) / "runner.env").stat().st_mode)
            (Path(output_path) / "qemu-execution.json").write_text(json.dumps({
                "requirements_install_exit_code": 0, "pip_check_exit_code": 0,
                "migration_exit_code": 0, "pytest_exit_code": 0,
            }), encoding="utf-8")
            (Path(output_path) / "qemu-readiness.json").write_text(json.dumps({"stages": {
                "guest_output_mount": {"state": "passed", "diagnostic": "mounted"},
                "guest_source_mount": {"state": "passed", "diagnostic": "mounted"},
                "guest_ssh_service": {"state": "passed", "diagnostic": "sshd active"},
                "guest_dependencies": {"state": "passed", "diagnostic": "pip check passed"},
                "guest_migrations": {"state": "passed", "diagnostic": "schema verified"},
                "guest_saas_tests": {"state": "passed", "diagnostic": "5 passed"},
            }}), encoding="utf-8")
            kwargs["stdout"].write(b"Reached target multi-user.target\nUbuntu guest login:\n")

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return None

    monkeypatch.setattr("sophyane.remote_runner_executors.shutil.which",
                        lambda name: {"qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
                                      "ssh": "/usr/bin/ssh", "ssh-keygen": "/usr/bin/ssh-keygen"}.get(name))
    monkeypatch.setattr("sophyane.remote_runner_executors.subprocess.Popen", FakeProcess)
    monkeypatch.setattr("sophyane.remote_runner_executors.os.killpg", lambda *_: None)
    calls = []

    def http_get(url, timeout):
        calls.append(url)
        return (401, b"authentication required") if url.endswith("/api/inventory") else (200, b'{"status":"ok"}')

    class QemuRunner:
        timeout = 60
        ssh_calls = []
        host_key_entries = []

        def __call__(self, argv, *, cwd, env, cancel):
            if argv and argv[0].endswith("ssh-keygen"):
                key_path = Path(argv[argv.index("-f") + 1])
                key_path.write_text("test-only-private-key")
                key_path.with_suffix(".pub").write_text("ssh-ed25519 test-public-key")
                return CommandResult(list(argv), 0, "", "", 0.01)
            if argv and argv[0].endswith("/ssh"):
                self.ssh_calls.append(list(argv))
                known_hosts_arg = next(arg for arg in argv if arg.startswith("UserKnownHostsFile="))
                self.host_key_entries.append(Path(known_hosts_arg.split("=", 1)[1]).read_text(encoding="ascii"))
                remote = argv[-1]
                if "cloud-init status" in remote:
                    output = '{"status":"done","errors":[]}'
                elif "qemu-readiness.json" in remote:
                    output = (FakeProcess.output_path / "qemu-readiness.json").read_text()
                elif "qemu-execution.json" in remote:
                    output = (FakeProcess.output_path / "qemu-execution.json").read_text()
                elif "psql" in remote:
                    output = "t"
                elif "pytest" in remote:
                    output = "5 passed"
                elif remote == "id":
                    output = "uid=1000(sophyane) gid=1000(sophyane) groups=1000(sophyane)"
                else:
                    output = "active"
                return CommandResult(list(argv), 0, output, "", 0.01)
            return runner(argv, cwd=cwd, env=env, cancel=cancel)

    executor = QemuFastAPIExecutor(image, image_hash, qemu_ssh_host_public_key=_TEST_SSH_HOST_KEY,
                                   command_runner=QemuRunner(), http_get=http_get,
                                   health_timeout=1)
    source = tmp_path / "source"
    source.mkdir()
    outcome = executor(source, {"job_id": "job-" + "b" * 32}, threading.Event())
    assert outcome["passed"] is True
    qemu_command = next(row["argv"] for row in outcome["commands"] if row["label"] == "qemu-process-alive")
    assert "restrict=on" in qemu_command[qemu_command.index("-netdev") + 1]
    assert "127.0.0.1" in qemu_command[qemu_command.index("-netdev") + 1]
    netdev = qemu_command[qemu_command.index("-netdev") + 1]
    assert re.search(r"hostfwd=tcp:127\.0\.0\.1:\d+-:22(?:,|$)", netdev)
    assert re.search(r"hostfwd=tcp:127\.0\.0\.1:\d+-:8000(?:,|$)", netdev)
    assert "cloudinit" not in qemu_command
    assert {"guest-dependencies-installed", "guest-database-migrations", "guest-saas-tests"} <= {
        row["label"] for row in outcome["commands"]
    }
    assert any(url.endswith("/healthz") for url in calls)
    assert any(url.endswith("/api/inventory") for url in calls)
    assert next(row["exit_code"] for row in outcome["commands"]
                if row["label"] == "guest-fastapi-health-from-host") == 0
    assert next(row["exit_code"] for row in outcome["commands"]
                if row["label"] == "guest-ssh-authenticated") == 0
    ssh_probe = QemuRunner.ssh_calls[0]
    assert "StrictHostKeyChecking=yes" in ssh_probe
    assert f"[127.0.0.1]:{ssh_probe[ssh_probe.index('-p') + 1]} {_TEST_SSH_HOST_KEY}" in QemuRunner.host_key_entries[0]
    assert "IdentityAgent=none" in ssh_probe
    assert "PasswordAuthentication=no" in ssh_probe
    assert f"SOPHYANE_RUNNER_SSH_PUBLIC_KEY='ssh-ed25519 test-public-key'" in FakeProcess.runner_env
    assert "test-only-private-key" not in FakeProcess.runner_env
    assert FakeProcess.runner_env_mode == 0o600
    assert any(row["label"] == "guest-9p-mounts" and row["exit_code"] == 0 for row in outcome["commands"])


def test_qemu_executor_records_each_readiness_stage(tmp_path, monkeypatch):
    image = tmp_path / "guest.qcow2"
    image.write_bytes(b"pinned guest image")
    image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    source = tmp_path / "source"
    source.mkdir()
    seed_iso = tmp_path / "seed.iso"
    seed_iso.write_bytes(b"test cloud-init seed")
    runner = SuccessfulCommandRunner()

    def successful_guest_probe(argv, *, cwd, env, cancel):
        runner.commands.append((list(argv), dict(env)))
        command = argv[-1]
        if "cloud-init" in command:
            output = '{"status":"done","errors":[]}'
        elif "qemu-readiness.json" in command:
            output = json.dumps({"stages": {
                "guest_dependencies": {"state": "passed", "diagnostic": "pip check passed"},
                "guest_migrations": {"state": "passed", "diagnostic": "schema verified"},
                "guest_saas_tests": {"state": "passed", "diagnostic": "5 passed"},
            }})
        elif "psql" in command:
            output = "t"
        elif "pytest" in command:
            output = "5 passed"
        elif "pip check" in command:
            output = "No broken requirements found.\nruntime imports passed"
        elif command == "id":
            output = "uid=1000(sophyane) gid=1000(sophyane) groups=1000(sophyane)"
        else:
            output = "active"
        return CommandResult(list(argv), 0, output, "", 0.01)

    original_runner = runner
    ssh_calls = []

    class QemuRunner:
        timeout = 60

        def __call__(self, argv, *, cwd, env, cancel):
            if argv and argv[0].endswith("ssh-keygen"):
                key_path = Path(argv[argv.index("-f") + 1])
                key_path.write_text("test-only-private-key")
                key_path.with_suffix(".pub").write_text("ssh-ed25519 test-public-key")
                return CommandResult(list(argv), 0, "", "", 0.01)
            if argv and argv[0].endswith("/ssh"):
                ssh_calls.append(list(argv))
                return successful_guest_probe(argv, cwd=cwd, env=env, cancel=cancel)
            return original_runner(argv, cwd=cwd, env=env, cancel=cancel)

    class FakeProcess:
        pid = 999999
        returncode = 0

        def __init__(self, argv, **kwargs):
            output_path = next(arg.split("path=", 1)[1].split(",", 1)[0]
                               for arg in argv if "mount_tag=sophyane-output" in arg)
            (Path(output_path) / "qemu-execution.json").write_text(json.dumps({
                "requirements_install_exit_code": 0,
                "pip_check_exit_code": 0,
                "migration_exit_code": 0,
            }), encoding="utf-8")
            (Path(output_path) / "qemu-readiness.json").write_text(json.dumps({"stages": {
                "guest_output_mount": {"state": "passed", "diagnostic": "mounted"},
                "guest_source_mount": {"state": "passed", "diagnostic": "mounted"},
                "guest_ssh_service": {"state": "passed", "diagnostic": "sshd active"},
                "guest_dependencies": {"state": "passed", "diagnostic": "installed"},
                "guest_migrations": {"state": "passed", "diagnostic": "migrated"},
                "guest_saas_tests": {"state": "passed", "diagnostic": "passed"},
            }}), encoding="utf-8")
            kwargs["stdout"].write(b"Reached target multi-user.target\nUbuntu guest login:\n")

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return None

    monkeypatch.setattr("sophyane.remote_runner_executors.shutil.which",
                        lambda name: {"qemu-system-aarch64": "/usr/bin/qemu-system-aarch64",
                                      "qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
                                      "ssh": "/usr/bin/ssh", "ssh-keygen": "/usr/bin/ssh-keygen"}.get(name))
    monkeypatch.setattr("sophyane.remote_runner_executors.subprocess.Popen", FakeProcess)
    monkeypatch.setattr("sophyane.remote_runner_executors.os.killpg", lambda *_: None)
    executor = QemuFastAPIExecutor(
        image, image_hash, qemu_binary="qemu-system-aarch64",
        qemu_ssh_host_public_key=_TEST_SSH_HOST_KEY,
        qemu_bios=str(tmp_path / "edk2-aarch64-code.fd"),
        qemu_seed_iso=str(seed_iso), command_runner=QemuRunner(),
        http_get=lambda url, timeout: (401, b"unauthorized") if url.endswith("/api/inventory") else (200, b'{"status":"ok"}'),
        health_timeout=1,
    )

    result = executor(source, {"job_id": "job-" + "c" * 32}, threading.Event())

    labels = {item["label"] for item in result["commands"]}
    assert result["passed"] is True, result
    qemu_command = next(item["argv"] for item in result["commands"] if item["label"] == "qemu-process-alive")
    assert qemu_command[qemu_command.index("-machine") + 1] == "virt"
    assert qemu_command[qemu_command.index("-accel") + 1] == "tcg,thread=multi"
    assert qemu_command[qemu_command.index("-cpu") + 1] == "cortex-a72"
    assert qemu_command[qemu_command.index("-bios") + 1] == str(tmp_path / "edk2-aarch64-code.fd")
    assert "virtio-blk-device,drive=hd0" in qemu_command
    assert "virtio-net-device,netdev=net0" in qemu_command
    netdev = qemu_command[qemu_command.index("-netdev") + 1]
    assert re.search(r"hostfwd=tcp:127\.0\.0\.1:\d+-:22(?:,|$)", netdev)
    assert re.search(r"hostfwd=tcp:127\.0\.0\.1:\d+-:8000(?:,|$)", netdev)
    assert any(str(seed_iso.resolve()) in arg for arg in qemu_command)
    assert "virtio-blk-device,drive=cloudinit" in qemu_command
    assert ssh_calls
    assert ssh_calls[0][-2] == "sophyane@127.0.0.1"
    assert ssh_calls[0][ssh_calls[0].index("-i") + 1].endswith("runner_ed25519")
    assert ssh_calls[0][-1] == "id"
    assert any(call[-1] == "systemctl is-active multi-user.target" for call in ssh_calls)
    ssh_probe = next(call for call in ssh_calls if call[-1] == "id")
    assert "StrictHostKeyChecking=yes" in ssh_probe
    assert "UserKnownHostsFile=/dev/null" not in ssh_probe
    netdev = qemu_command[qemu_command.index("-netdev") + 1]
    assert re.search(r"hostfwd=tcp:127\.0\.0\.1:\d+-:22(?:,|$)", netdev)
    assert re.search(r"hostfwd=tcp:127\.0\.0\.1:\d+-:8000(?:,|$)", netdev)
    assert {
        "qemu-process-alive", "ubuntu-boot-complete", "guest-ssh-authenticated",
        "guest-9p-mounts",
        "guest-cloud-init-complete", "guest-dependencies-installed", "guest-fastapi-listening",
        "guest-fastapi-health-from-host", "guest-database-migrations", "guest-saas-tests",
    } <= labels


def test_qemu_launch_success_is_not_overwritten_by_guest_boot_failure(tmp_path, monkeypatch):
    image = tmp_path / "guest.qcow2"
    image.write_bytes(b"pinned image")
    source = tmp_path / "source"
    source.mkdir()

    class CommandRunner:
        timeout = 5

        def __call__(self, argv, *, cwd, env, cancel):
            if argv[0].endswith("ssh-keygen"):
                key = Path(argv[argv.index("-f") + 1])
                key.write_text("test private key")
                key.with_suffix(".pub").write_text("ssh-ed25519 test key")
            return CommandResult(list(argv), 0, "", "", 0.01)

    class GuestNeverReady:
        pid = 45678

        def __init__(self, *_args, **_kwargs):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr("sophyane.remote_runner_executors.shutil.which", lambda name: {
        "qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
        "ssh-keygen": "/usr/bin/ssh-keygen",
        "ssh": "/usr/bin/ssh",
    }.get(name))
    monkeypatch.setattr("sophyane.remote_runner_executors.subprocess.Popen", GuestNeverReady)
    monkeypatch.setattr("sophyane.remote_runner_executors.os.killpg", lambda *_args: None)
    executor = QemuFastAPIExecutor(
        image, hashlib.sha256(image.read_bytes()).hexdigest(),
        qemu_ssh_host_public_key=_TEST_SSH_HOST_KEY,
        qemu_binary="qemu-system-x86_64", command_runner=CommandRunner(), health_timeout=0.05,
    )

    outcome = executor(source, {"job_id": "job-" + "d" * 32}, threading.Event())
    stages = {row["label"]: row["exit_code"] for row in outcome["commands"]}

    assert stages["qemu-process-alive"] == 0
    assert stages["qemu-boot"] == 0
    assert stages["ubuntu-boot-complete"] == 1


def test_guest_startup_reports_failure_stage_and_runs_migration_as_app_user():
    script = Path("guest/remote-fastapi-start.sh").read_text(encoding="utf-8")
    assert "qemu-readiness.json" in script
    assert "SOPHYANE_RUNNER_SSH_PUBLIC_KEY" in script
    assert "authorized_keys" in script
    assert "runuser -u sophyane --" in script
    assert "psql" in script
    assert "cloud-init status --wait" in script
    assert "usermod --shell /bin/bash sophyane" in script
    assert script.index("usermod --shell /bin/bash sophyane") < script.index("authorized_keys")
    assert "chmod 0700 /home/sophyane/.ssh" in script
    assert 'chmod 0600 "$KEY_TMP"' in script
    assert 'mv -f "$KEY_TMP" /home/sophyane/.ssh/authorized_keys' in script
    assert "sshd -t" in script


def test_guest_startup_verifies_9p_filesystem_type_and_access_modes():
    script = Path("guest/remote-fastapi-start.sh").read_text(encoding="utf-8")

    assert "findmnt -n -o FSTYPE,OPTIONS --target" in script
    assert "9p" in script
    assert "source 9p mount is not read-only" in script
    assert "output 9p mount is not read-write" in script


def test_ssh_failure_evidence_preserves_stderr_and_remote_exit_diagnostic():
    result = CommandResult(
        argv=["ssh", "sophyane@127.0.0.1", "printf SOPHYANE_GUEST_SSH_OK"],
        exit_code=1, stdout="", stderr="This account is currently not available.\n",
        duration_seconds=0.2, timed_out=False, cancelled=False,
    )

    record = QemuFastAPIExecutor._record(result, "guest-ssh-authenticated")

    assert record["stderr"] == "This account is currently not available.\n"


@pytest.mark.parametrize(("exit_code", "stderr", "expected"), [
    (255, "ssh: connect to host 127.0.0.1 port 2222: Connection refused", "connection_failure"),
    (255, "sophyane@127.0.0.1: Permission denied (publickey).", "key_rejected"),
    (1, "This account is currently not available.", "account_restriction"),
    (1, "id: command not found", "remote_command_failure"),
])
def test_ssh_probe_failure_classification(exit_code, stderr, expected):
    assert QemuFastAPIExecutor._classify_ssh_failure(exit_code, stderr) == expected


def test_ssh_host_key_mismatch_is_classified_as_trust_failure():
    assert QemuFastAPIExecutor._classify_ssh_failure(
        255, "Host key verification failed."
    ) == "host_key_rejected"


def test_qemu_guest_unit_installs_key_before_cloud_init_wait_and_precreates_namespace_paths():
    unit = Path("guest/remote-fastapi.service").read_text(encoding="utf-8")
    tmpfiles = Path("guest/remote-fastapi-tmpfiles.conf").read_text(encoding="utf-8")
    docs = Path("docs/remote-execution-runners.md").read_text(encoding="utf-8")

    assert "After=systemd-tmpfiles-setup.service" in unit
    assert "cloud-final.service" not in unit
    assert "ReadWritePaths=/mnt /opt/sophyane /opt/sophyane-venv /home/sophyane /run" in unit
    assert "/mnt/sophyane-input /mnt/sophyane-output" not in unit
    assert "d /mnt/sophyane-input 0755 root root -" in tmpfiles
    assert "d /mnt/sophyane-output 0755 root root -" in tmpfiles
    assert "remote-fastapi-tmpfiles.conf" in docs


def test_aarch64_qemu_profile_requires_an_uefi_firmware_path(tmp_path):
    executor = QemuFastAPIExecutor(tmp_path / "guest.qcow2", "0" * 64,
                                   qemu_binary="sophyane-qemu-system-aarch64")
    with pytest.raises(ValueError, match="SOPHYANE_QEMU_BIOS"):
        executor._qemu_platform_args(tmp_path / "overlay.qcow2")


def test_qemu_ssh_fails_closed_without_trusted_host_key(tmp_path):
    executor = QemuFastAPIExecutor(tmp_path / "guest.qcow2", "0" * 64)
    with pytest.raises(ValueError, match="trusted SSH host public key"):
        executor._known_hosts_contents(2222)


def test_qemu_ssh_known_hosts_binds_trusted_key_to_forwarded_port(tmp_path):
    executor = QemuFastAPIExecutor(
        tmp_path / "guest.qcow2", "0" * 64,
        qemu_ssh_host_public_key=_TEST_SSH_HOST_KEY,
    )
    assert executor._known_hosts_contents(2222) == f"[127.0.0.1]:2222 {_TEST_SSH_HOST_KEY}\n"


def test_qemu_ssh_known_hosts_ignores_public_key_comment(tmp_path):
    executor = QemuFastAPIExecutor(
        tmp_path / "guest.qcow2", "0" * 64,
        qemu_ssh_host_public_key=_TEST_SSH_HOST_KEY + " pinned-image-host-key",
    )
    assert executor._known_hosts_contents(2222) == f"[127.0.0.1]:2222 {_TEST_SSH_HOST_KEY}\n"


def test_qemu_ssh_rejects_malformed_trusted_host_key(tmp_path):
    executor = QemuFastAPIExecutor(
        tmp_path / "guest.qcow2", "0" * 64,
        qemu_ssh_host_public_key="ssh-ed25519 not-a-key",
    )
    with pytest.raises(ValueError, match="invalid trusted SSH host public key"):
        executor._known_hosts_contents(2222)


def test_qemu_executor_fails_closed_when_guest_source_9p_mount_fails(tmp_path, monkeypatch):
    image = tmp_path / "guest.qcow2"
    image.write_bytes(b"pinned guest image")
    source = tmp_path / "source"
    source.mkdir()
    ssh_calls = []

    class CommandRunner:
        timeout = 5

        def __call__(self, argv, *, cwd, env, cancel):
            if argv[0].endswith("ssh-keygen"):
                key = Path(argv[argv.index("-f") + 1])
                key.write_text("private test key")
                key.with_suffix(".pub").write_text("ssh-ed25519 public test key")
            if argv[0].endswith("/ssh"):
                ssh_calls.append(list(argv))
            return CommandResult(list(argv), 0, "", "", 0.01)

    class GuestWithBrokenMount:
        pid = 12345

        def __init__(self, argv, **kwargs):
            output = Path(next(arg.split("path=", 1)[1].split(",", 1)[0]
                               for arg in argv if "mount_tag=sophyane-output" in arg))
            (output / "qemu-readiness.json").write_text(json.dumps({"stages": {
                "guest_output_mount": {"state": "passed", "diagnostic": "mounted"},
                "guest_source_mount": {"state": "failed", "diagnostic": "9p source mount unavailable"},
            }}), encoding="utf-8")
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    monkeypatch.setattr("sophyane.remote_runner_executors.shutil.which", lambda name: {
        "qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
        "ssh-keygen": "/usr/bin/ssh-keygen", "ssh": "/usr/bin/ssh",
    }.get(name))
    monkeypatch.setattr("sophyane.remote_runner_executors.subprocess.Popen", GuestWithBrokenMount)
    monkeypatch.setattr("sophyane.remote_runner_executors.os.killpg", lambda *_args: None)
    executor = QemuFastAPIExecutor(
        image, hashlib.sha256(image.read_bytes()).hexdigest(),
        qemu_ssh_host_public_key=_TEST_SSH_HOST_KEY,
        command_runner=CommandRunner(), health_timeout=1,
    )

    result = executor(source, {"job_id": "job-" + "e" * 32}, threading.Event())

    checks = {row["label"]: row for row in result["commands"]}
    assert result["passed"] is False
    assert checks["guest-9p-mounts"]["exit_code"] == 1
    assert "source mount unavailable" in checks["guest-9p-mounts"]["diagnostic"]
    assert ssh_calls == []
    assert checks["guest-fastapi-health-from-host"]["exit_code"] is None


def test_qemu_executor_does_not_launch_without_a_trusted_host_key(tmp_path, monkeypatch):
    image = tmp_path / "guest.qcow2"
    image.write_bytes(b"pinned guest image")
    source = tmp_path / "source"
    source.mkdir()
    launches = []
    monkeypatch.setattr("sophyane.remote_runner_executors.shutil.which", lambda name: {
        "qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
        "ssh-keygen": "/usr/bin/ssh-keygen", "ssh": "/usr/bin/ssh",
    }.get(name))
    monkeypatch.setattr("sophyane.remote_runner_executors.subprocess.Popen",
                        lambda *args, **kwargs: launches.append(args))
    executor = QemuFastAPIExecutor(
        image, hashlib.sha256(image.read_bytes()).hexdigest(),
        command_runner=SuccessfulCommandRunner(), health_timeout=1,
    )

    outcome = executor(source, {"job_id": "job-" + "f" * 32}, threading.Event())

    assert outcome["passed"] is False
    assert outcome["error"] == "trusted SSH host public key is required"
    assert launches == []


def test_qemu_ephemeral_keygen_uses_android_safe_host_tool_limits(tmp_path, monkeypatch):
    image = tmp_path / "guest.qcow2"
    image.write_bytes(b"pinned guest image")
    source = tmp_path / "source"
    source.mkdir()
    executor = QemuFastAPIExecutor(
        image, hashlib.sha256(image.read_bytes()).hexdigest(),
        qemu_ssh_host_public_key=_TEST_SSH_HOST_KEY,
        command_runner=BoundedCommandRunner(timeout=15),
    )
    real_which = shutil.which
    monkeypatch.setattr(
        "sophyane.remote_runner_executors.shutil.which",
        lambda name: {"qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
                      "ssh": "/usr/bin/ssh", "ssh-keygen": real_which("ssh-keygen")}.get(name),
    )

    class HostTools:
        def __call__(self, argv, *, cwd, env, cancel):
            if "qemu-img" in argv[0]:
                return CommandResult(list(argv), 1, "stop after keygen", "", 0.01)
            runner = BoundedCommandRunner(timeout=15, address_space_bytes=16 * 1024**3,
                                          data_bytes=2 * 1024**3, process_limit=512)
            return runner(argv, cwd=cwd, env=env, cancel=cancel)

    monkeypatch.setattr(executor, "_qemu_img_command_runner", lambda: HostTools())
    outcome = executor(source, {"job_id": "job-" + "d" * 32}, threading.Event())

    keygen = next(item for item in outcome["commands"] if item["label"] == "qemu-ephemeral-ssh-key-create")
    assert keygen["exit_code"] == 0, keygen


def test_compose_policy_rejects_privileged_or_host_bind_configuration(tmp_path):
    workspace = tmp_path.resolve()
    valid = {
        "services": {
        "database": {"volumes": [], "cpus": 1.0, "mem_limit": "1g", "pids_limit": 128},
            "api": {"ports": [{"host_ip": "127.0.0.1", "published": "43210", "target": 8000}],
                    "volumes": [], "build": {"context": str(workspace)}, "cpus": 1.0, "mem_limit": "1g", "pids_limit": 128},
        },
        "networks": {"default": {"internal": True}},
    }
    DockerComposeDeploymentExecutor._validate_config(valid, workspace, 43210)
    unsafe = json.loads(json.dumps(valid))
    unsafe["services"]["api"]["privileged"] = True
    try:
        DockerComposeDeploymentExecutor._validate_config(unsafe, workspace, 43210)
    except ValueError as error:
        assert "privilege" in str(error)
    else:
        raise AssertionError("privileged compose service was accepted")
