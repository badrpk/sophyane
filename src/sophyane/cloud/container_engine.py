"""Container Engine Manager for Sophyane on Android/Linux.

Supports:
  1) Native Docker daemon (docker / docker compose).
  2) Podman / Rootless Podman.
  3) udocker (User-space Docker container execution for Termux/Android without root).
  4) PRoot sandbox environment fallback.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class ContainerEngineStatus:
    has_docker: bool
    has_podman: bool
    has_udocker: bool
    has_proot: bool
    primary_engine: str
    is_android_termux: bool


class ContainerEngine:
    """Manages container runtime execution on phone and desktop hosts."""

    def __init__(self) -> None:
        self.state_dir = Path.home() / ".local" / "share" / "sophyane" / "containers"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def is_termux() -> bool:
        prefix = os.getenv("PREFIX", "")
        return "com.termux" in prefix or Path("/data/data/com.termux").exists()

    def get_status(self) -> ContainerEngineStatus:
        has_docker = shutil.which("docker") is not None
        has_podman = shutil.which("podman") is not None
        has_udocker = shutil.which("udocker") is not None or (self.state_dir / "udocker").exists()
        has_proot = shutil.which("proot") is not None
        termux = self.is_termux()

        if has_docker:
            primary = "docker"
        elif has_podman:
            primary = "podman"
        elif has_udocker:
            primary = "udocker"
        elif has_proot:
            primary = "proot"
        else:
            primary = "none"

        return ContainerEngineStatus(
            has_docker=has_docker,
            has_podman=has_podman,
            has_udocker=has_udocker,
            has_proot=has_proot,
            primary_engine=primary,
            is_android_termux=termux,
        )

    def install_udocker(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Install udocker for user-space Docker container execution on Termux/Android."""
        if shutil.which("udocker"):
            return {"ok": True, "engine": "udocker", "message": "udocker is already available in PATH"}

        if progress:
            progress("Installing udocker user-space container tool via pip...")

        res = subprocess.run([sys.executable, "-m", "pip", "install", "udocker"], text=True, capture_output=True)
        if res.returncode == 0:
            if progress:
                progress("Successfully installed udocker via pip")
            return {"ok": True, "engine": "udocker"}
        return {"ok": False, "engine": "udocker", "error": res.stderr.strip()}

    def run_container(
        self,
        image: str,
        name: str = "",
        ports: list[str] | None = None,
        volumes: list[str] | None = None,
        envs: dict[str, str] | None = None,
        command: list[str] | None = None,
    ) -> dict[str, Any]:
        status = self.get_status()
        engine = status.primary_engine

        if engine in {"docker", "podman"}:
            cmd = [engine, "run", "-d"]
            if name:
                cmd.extend(["--name", name])
            for p in (ports or []):
                cmd.extend(["-p", p])
            for v in (volumes or []):
                cmd.extend(["-v", v])
            for k, val in (envs or {}).items():
                cmd.extend(["-e", f"{k}={val}"])
            cmd.append(image)
            if command:
                cmd.extend(command)

            res = subprocess.run(cmd, text=True, capture_output=True)
            if res.returncode == 0:
                return {"ok": True, "engine": engine, "container_id": res.stdout.strip()}
            return {"ok": False, "engine": engine, "error": res.stderr.strip()}

        elif engine == "udocker":
            udocker_path = shutil.which("udocker") or str(Path.home() / ".local" / "bin" / "udocker")
            c_name = name or f"app-{os.urandom(4).hex()}"
            sub_create = subprocess.run([udocker_path, "create", f"--name={c_name}", image], text=True, capture_output=True)
            if sub_create.returncode != 0:
                return {"ok": False, "engine": "udocker", "error": sub_create.stderr.strip()}
            sub_run = subprocess.run([udocker_path, "run", c_name] + (command or []), text=True, capture_output=True)
            return {"ok": sub_run.returncode == 0, "engine": "udocker", "output": sub_run.stdout, "error": sub_run.stderr}

        return {
            "ok": False,
            "engine": "none",
            "error": "No container engine available. Install Docker, Podman, or run udocker setup.",
        }
