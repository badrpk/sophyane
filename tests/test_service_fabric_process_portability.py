from __future__ import annotations

import subprocess
import sys

from sophyane.service_fabric.manifest import (
    ServiceManifest,
    ServiceSpec,
)
from sophyane.service_fabric.supervisor import (
    ServiceSupervisor,
)


def test_supervisor_can_stop_owned_process(
    tmp_path,
) -> None:
    supervisor = ServiceSupervisor(
        workspace=tmp_path,
    )

    spec = ServiceSpec(
        name="portable-worker",
        command=(
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ),
    )

    manifest = ServiceManifest(
        name="portable-test",
        services=(
            spec,
        ),
    )

    started = supervisor.start_manifest(
        manifest
    )

    assert len(started) == 1
    assert started[0].process.poll() is None

    supervisor.stop_all()

    assert started[0].process.poll() is not None
    assert supervisor.running == {}



def test_windows_start_uses_creationflags_not_start_new_session(
    tmp_path,
    monkeypatch,
) -> None:
    supervisor = ServiceSupervisor(
        workspace=tmp_path,
    )

    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(
        "sophyane.service_fabric.supervisor.os.name",
        "nt",
    )

    monkeypatch.setattr(
        "sophyane.service_fabric.supervisor."
        "subprocess.CREATE_NEW_PROCESS_GROUP",
        512,
        raising=False,
    )

    monkeypatch.setattr(
        "sophyane.service_fabric.supervisor."
        "subprocess.Popen",
        fake_popen,
    )

    spec = ServiceSpec(
        name="windows-worker",
        command=(
            "python",
            "-c",
            "print('ok')",
        ),
    )

    running = supervisor.start_service(spec)

    assert running.process.pid == 12345
    assert captured.get("creationflags") == 512
    assert "start_new_session" not in captured


def test_windows_stop_uses_terminate_without_killpg(
    tmp_path,
    monkeypatch,
) -> None:
    from pathlib import Path
    import time

    from sophyane.service_fabric.supervisor import (
        RunningService,
    )

    supervisor = ServiceSupervisor(
        workspace=tmp_path,
    )

    class FakeProcess:
        pid = 23456

        def __init__(self) -> None:
            self.returncode = None
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = 0

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminate_calls += 1
            self.returncode = 0

        def kill(self):
            self.kill_calls += 1
            self.returncode = -9

        def wait(self, timeout=None):
            self.wait_calls += 1
            return self.returncode

    process = FakeProcess()

    spec = ServiceSpec(
        name="windows-worker",
        command=(
            "python",
            "-c",
            "print('ok')",
        ),
    )

    supervisor.running[
        spec.name
    ] = RunningService(
        spec=spec,
        process=process,
        log_path=(
            Path(tmp_path)
            / "worker.log"
        ),
        started_at=time.time(),
    )

    monkeypatch.setattr(
        "sophyane.service_fabric.supervisor.os.name",
        "nt",
    )

    def forbidden_killpg(*args, **kwargs):
        raise AssertionError(
            "os.killpg must not execute on Windows"
        )

    monkeypatch.setattr(
        "sophyane.service_fabric.supervisor.os.killpg",
        forbidden_killpg,
        raising=False,
    )

    assert supervisor.stop_service(
        spec.name
    ) is True

    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert process.wait_calls == 1
    assert spec.name not in supervisor.running


def test_windows_stop_escalates_to_process_kill(
    tmp_path,
    monkeypatch,
) -> None:
    from pathlib import Path
    import time

    from sophyane.service_fabric.supervisor import (
        RunningService,
    )

    supervisor = ServiceSupervisor(
        workspace=tmp_path,
    )

    class SlowProcess:
        pid = 34567

        def __init__(self) -> None:
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = 0

        def poll(self):
            return None

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1

        def wait(self, timeout=None):
            self.wait_calls += 1

            if self.kill_calls == 0:
                raise subprocess.TimeoutExpired(
                    cmd="windows-worker",
                    timeout=timeout,
                )

            return -9

    process = SlowProcess()

    spec = ServiceSpec(
        name="windows-worker",
        command=(
            "python",
            "-c",
            "print('ok')",
        ),
    )

    supervisor.running[
        spec.name
    ] = RunningService(
        spec=spec,
        process=process,
        log_path=(
            Path(tmp_path)
            / "worker.log"
        ),
        started_at=time.time(),
    )

    monkeypatch.setattr(
        "sophyane.service_fabric.supervisor.os.name",
        "nt",
    )

    def forbidden_killpg(*args, **kwargs):
        raise AssertionError(
            "os.killpg must not execute on Windows"
        )

    monkeypatch.setattr(
        "sophyane.service_fabric.supervisor.os.killpg",
        forbidden_killpg,
        raising=False,
    )

    assert supervisor.stop_service(
        spec.name,
        timeout=0.01,
    ) is True

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == 2
