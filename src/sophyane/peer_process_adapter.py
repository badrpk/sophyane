"""Bounded local-process adapters for explicitly declared peer operations."""
from __future__ import annotations

import os
import select
import shutil
import subprocess
import time
from pathlib import Path
from typing import Mapping

from .ecosystem_contract import ManifestOperation
from .peer_capability_adapter import PeerCapabilityResult


class LocalPeerProcessAdapter:
    def __init__(
        self,
        repository: str,
        root: Path,
        operations: Mapping[str, ManifestOperation],
    ) -> None:
        self.repository = str(repository).strip().casefold()
        self.root = Path(root).expanduser().resolve()
        self.operations = {
            str(name).strip().casefold(): operation
            for name, operation in operations.items()
        }

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            # Keep only the executable search path from the host environment;
            # do not forward arbitrary user/application secrets.
            "PATH": os.environ.get("PATH", os.defpath),
            "LC_ALL": "C",
            "LANG": "C",
        }

    @staticmethod
    def executable_available(argv: tuple[str, ...]) -> bool:
        executable = argv[0]
        if os.path.isabs(executable) or os.sep in executable:
            return os.path.isfile(executable) and os.access(executable, os.X_OK)
        return shutil.which(
            executable,
            path=os.environ.get("PATH", os.defpath),
        ) is not None

    def invoke(
        self,
        capability: str,
        objective: str,
        workspace: str,
    ) -> PeerCapabilityResult:
        del objective, workspace
        normalized = str(capability or "").strip().casefold()
        operation = self.operations.get(normalized)
        if operation is None:
            return PeerCapabilityResult(
                handled=False,
                ok=False,
                repository=self.repository,
                capability=normalized,
                output="",
                evidence={"reason": "PEER_CAPABILITY_UNSUPPORTED"},
            )

        base_evidence = {
            "repository": self.repository,
            "capability": normalized,
            "argv": list(operation.argv),
            "executable": os.path.basename(operation.argv[0]),
            "shell": False,
        }
        if not self.root.is_dir():
            return PeerCapabilityResult(
                handled=True,
                ok=False,
                repository=self.repository,
                capability=normalized,
                output="",
                evidence={**base_evidence, "reason": "PEER_ROOT_UNAVAILABLE"},
            )
        if not self.executable_available(operation.argv):
            return PeerCapabilityResult(
                handled=True,
                ok=False,
                repository=self.repository,
                capability=normalized,
                output="",
                evidence={**base_evidence, "reason": "PEER_EXECUTABLE_UNAVAILABLE"},
            )

        started = time.monotonic()
        try:
            process = subprocess.Popen(
                list(operation.argv),
                cwd=self.root,
                env=self._environment(),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except (OSError, ValueError) as error:
            return PeerCapabilityResult(
                handled=True,
                ok=False,
                repository=self.repository,
                capability=normalized,
                output=str(error),
                evidence={**base_evidence, "reason": "PEER_PROCESS_START_FAILED"},
            )

        output = bytearray()
        truncated = False
        deadline = started + operation.timeout_seconds
        assert process.stdout is not None
        descriptor = process.stdout.fileno()
        timed_out = False
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                process.kill()
                break
            ready, _, _ = select.select([descriptor], [], [], min(remaining, 0.05))
            if not ready:
                continue
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            if len(output) < operation.max_output_bytes:
                available = operation.max_output_bytes - len(output)
                output.extend(chunk[:available])
                truncated = truncated or len(chunk) > available
            else:
                truncated = True

        if timed_out:
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
        else:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                tail, _ = process.communicate(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                tail, _ = process.communicate()
                timed_out = True
            if tail:
                if len(output) < operation.max_output_bytes:
                    available = operation.max_output_bytes - len(output)
                    output.extend(tail[:available])
                    truncated = truncated or len(tail) > available
                else:
                    truncated = True

        duration_ms = (time.monotonic() - started) * 1000.0
        text = bytes(output).decode("utf-8", errors="replace")
        evidence = {
            **base_evidence,
            "duration_ms": duration_ms,
            "output_truncated": truncated,
            "exit_status": process.returncode,
        }
        if timed_out:
            evidence["reason"] = "PEER_COMMAND_TIMEOUT"
        elif process.returncode != 0:
            evidence["reason"] = "PEER_COMMAND_FAILED"
        return PeerCapabilityResult(
            handled=True,
            ok=not timed_out and process.returncode == 0,
            repository=self.repository,
            capability=normalized,
            output=text,
            evidence=evidence,
        )


__all__ = ["LocalPeerProcessAdapter"]
