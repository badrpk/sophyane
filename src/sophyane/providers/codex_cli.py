"""Read-only local CLI intelligence providers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Any

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)


_STATE_ROOT = (
    Path.home()
    / ".local"
    / "state"
    / "sophyane"
    / "codex-cli-sessions"
)

_SESSION_LOCK = threading.Lock()

_AGY_PROOT_EXECUTABLE = "/data/data/com.termux/files/usr/bin/proot-distro"
_AGY_EXECUTABLE = "/root/.local/bin/agy"


def agy_command(workspace: str | Path | None = None) -> list[str]:
    launcher = os.environ.get("SOPHYANE_AGY_PROOT", _AGY_PROOT_EXECUTABLE)
    executable = os.environ.get("SOPHYANE_AGY_CLI", _AGY_EXECUTABLE)
    work_dir = ["--work-dir", str(workspace)] if workspace is not None else []
    return [launcher, "login", *work_dir, "debian", "--", executable]


def agy_available() -> bool:
    command = agy_command()
    rootfs_executable = (
        Path("/data/data/com.termux/files/usr/var/lib/proot-distro/containers/debian/rootfs")
        / command[-1].lstrip("/")
    )
    return Path(command[0]).is_file() and rootfs_executable.is_file()


def _workspace_key(workspace: Path) -> str:
    return hashlib.sha256(
        str(workspace).encode("utf-8")
    ).hexdigest()[:24]


def _session_path(workspace: Path) -> Path:
    return (
        _STATE_ROOT
        / f"{_workspace_key(workspace)}.json"
    )


def _load_session(workspace: Path) -> str:
    path = _session_path(workspace)

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
    ):
        return ""

    if (
        payload.get("workspace")
        != str(workspace)
        or payload.get("sandbox")
        != "read-only"
        or payload.get("contract_version")
        != "mutation-proposal-v2"
    ):
        return ""

    return str(
        payload.get("thread_id")
        or ""
    ).strip()


def _save_session(
    workspace: Path,
    thread_id: str,
) -> None:
    _STATE_ROOT.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )

    target = _session_path(workspace)
    temporary = target.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(
            {
                "workspace": str(workspace),
                "thread_id": thread_id,
                "sandbox": "read-only",
                "contract_version": "mutation-proposal-v2",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.chmod(
        temporary,
        0o600,
    )

    temporary.replace(
        target
    )


def _thread_id(stdout: str) -> str:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") != "thread.started":
            continue

        value = (
            event.get("thread_id")
            or event.get("threadId")
        )

        if not value and isinstance(
            event.get("thread"),
            dict,
        ):
            value = event["thread"].get("id")

        if value:
            return str(value).strip()

    return ""


class CodexCliProvider(Provider):
    """Codex CLI reviewer with persistent per-workspace context."""

    metadata = ProviderMetadata(
        provider_id="codex_cli",
        display_name="Codex CLI",
        default_model="codex-default",
        environment_variable="",
        requires_api_key=False,
    )

    provider_id = "codex_cli"

    def __init__(
        self,
        *,
        model: str = "codex-default",
        timeout: int = 300,
        workspace: str | Path | None = None,
        **_: Any,
    ) -> None:
        self.model = str(
            model
            or "codex-default"
        )
        self.timeout = max(
            30,
            int(timeout),
        )
        self.workspace = Path(
            workspace
            or Path.cwd()
        ).expanduser().resolve()

        executable = (
            os.environ.get(
                "SOPHYANE_CODEX_CLI"
            )
            or shutil.which("codex")
            or ""
        )

        if not executable:
            raise ProviderError(
                "Codex CLI executable was not found"
            )

        self.executable = str(
            executable
        )

    def _prompt(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        return (
            "SOPHYANE MODE 4-3 CODEX CLI AUTHORITY\n"
            "You are a non-mutating intelligence/reviewer provider.\n"
            "Never directly edit files, run mutating commands, commit, push, "
            "or claim unverified execution.\n"
            "For an explicit implementation request, you MAY propose an exact "
            "workspace-relative write_file, append_file, mkdir, or run_command "
            "JSON action for Sophyane's verified executor to apply. Return the "
            "action rather than refusing solely because it changes files.\n"
            "Return only the requested user-facing or structured response.\n\n"
            "SYSTEM CONTRACT:\n"
            + str(system_prompt or "").strip()
            + "\n\nCURRENT REQUEST:\n"
            + str(prompt or "").strip()
        )

    def _command(
        self,
        *,
        output_file: Path,
        thread_id: str,
    ) -> list[str]:
        common = [
            "--json",
            "--output-last-message",
            str(output_file),
            "--config",
            'approval_policy="never"',
            "--config",
            'model_reasoning_effort="low"',
        ]

        configured_model = str(
            os.environ.get(
                "SOPHYANE_CODEX_MODEL"
            )
            or ""
        ).strip()

        if configured_model:
            common.extend(
                [
                    "--model",
                    configured_model,
                ]
            )

        if thread_id:
            return [
                self.executable,
                "exec",
                "resume",
                *common,
                thread_id,
                "-",
            ]

        return [
            self.executable,
            "exec",
            "--sandbox",
            "read-only",
            "--cd",
            str(self.workspace),
            "--color",
            "never",
            *common,
            "-",
        ]

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> str:
        request = self._prompt(
            prompt,
            system_prompt,
        )

        with _SESSION_LOCK:
            thread_id = "" if os.environ.get("SOPHYANE_CODEX_FRESH") == "1" else _load_session(self.workspace)

            with tempfile.TemporaryDirectory(
                prefix="sophyane-codex-"
            ) as directory:
                output_file = (
                    Path(directory)
                    / "last-message.txt"
                )

                command = self._command(
                    output_file=output_file,
                    thread_id=thread_id,
                )

                try:
                    completed = subprocess.run(
                        command,
                        input=request,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=self.workspace,
                        timeout=self.timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    raise ProviderError(
                        "Codex CLI timed out after "
                        f"{self.timeout} seconds"
                    ) from error
                except OSError as error:
                    raise ProviderError(
                        f"Codex CLI could not start: {error}"
                    ) from error

                if completed.returncode != 0:
                    detail = (
                        completed.stderr.strip()
                        or completed.stdout.strip()
                        or "no diagnostic output"
                    )

                    raise ProviderError(
                        "Codex CLI failed with status "
                        f"{completed.returncode}: "
                        f"{detail[-2000:]}"
                    )

                text = ""

                try:
                    text = output_file.read_text(
                        encoding="utf-8"
                    ).strip()
                except OSError:
                    pass

                if not text:
                    raise ProviderError(
                        "Codex CLI returned an empty response"
                    )

                if not thread_id:
                    started_thread = _thread_id(
                        completed.stdout
                    )

                    if not started_thread:
                        raise ProviderError(
                            "Codex CLI response did not include "
                            "a persistent thread identifier"
                        )

                    _save_session(
                        self.workspace,
                        started_thread,
                    )

                return text


class AntigravityProvider(Provider):
    """AGY one-shot intelligence provider, constrained to plan/sandbox mode."""

    metadata = ProviderMetadata(
        provider_id="agy", display_name="Antigravity (AGY)",
        default_model="agy-default", environment_variable="", requires_api_key=False,
    )
    provider_id = "agy"

    def __init__(self, *, model: str = "agy-default", timeout: int = 300,
                 workspace: str | Path | None = None, **_: Any) -> None:
        self.model = str(model or "agy-default")
        self.timeout = max(30, int(timeout))
        self.workspace = Path(workspace or Path.cwd()).expanduser().resolve()
        self.command_prefix = agy_command(self.workspace)
        if not agy_available():
            raise ProviderError("Antigravity (AGY) runtime was not found")

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        request = (
            "SOPHYANE MODE 4-4 ANTIGRAVITY AUTHORITY\n"
            "Operate read-only. Do not edit files or run mutating commands.\n\n"
            "SYSTEM CONTRACT:\n" + str(system_prompt or "").strip()
            + "\n\nCURRENT REQUEST:\n" + str(prompt or "").strip()
        )
        command = [
            *self.command_prefix, "-p", request, "--mode", "plan",
            "--output-format", "json", "--print-timeout", f"{self.timeout}s",
            "--sandbox",
        ]
        configured_model = str(os.environ.get("SOPHYANE_AGY_MODEL") or "").strip()
        if configured_model:
            command.extend(["--model", configured_model])
        try:
            completed = subprocess.run(
                command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.workspace, timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ProviderError(
                f"Antigravity (AGY) timed out after {self.timeout} seconds"
            ) from error
        except OSError as error:
            raise ProviderError(f"Antigravity (AGY) could not start: {error}") from error
        if completed.returncode != 0:
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()

            parsed = None
            if stdout:
                try:
                    candidate = json.loads(stdout)
                    if isinstance(candidate, dict):
                        parsed = candidate
                except json.JSONDecodeError:
                    pass

            if parsed is not None:
                diagnostic = (
                    parsed.get("error")
                    or parsed.get("message")
                    or parsed.get("stop_reason")
                    or "no JSON diagnostic"
                )
                detail = (
                    f"agy_status={parsed.get('status')!r}; "
                    f"response_present={bool(str(parsed.get('response') or '').strip())}; "
                    f"diagnostic={str(diagnostic)[-1200:]}; "
                    f"stderr={stderr[-600:] if stderr else '<empty>'}"
                )
            else:
                detail = (
                    f"stdout={stdout[-1200:] if stdout else '<empty>'}; "
                    f"stderr={stderr[-800:] if stderr else '<empty>'}"
                )

            raise ProviderError(
                f"Antigravity (AGY) failed with status "
                f"{completed.returncode}: {detail}"
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ProviderError("Antigravity (AGY) returned invalid JSON") from error
        response = str(payload.get("response") or "").strip()
        status = str(payload.get("status") or "").strip()
        if status != "SUCCESS" or not response:
            diagnostic = (
                payload.get("error")
                or payload.get("message")
                or payload.get("stop_reason")
                or "no diagnostic output"
            )
            raise ProviderError(
                "Antigravity (AGY) returned no successful response: "
                f"status={status or '<missing>'}; "
                f"response_present={bool(response)}; "
                f"diagnostic={str(diagnostic)[-1500:]}"
            )
        return response
