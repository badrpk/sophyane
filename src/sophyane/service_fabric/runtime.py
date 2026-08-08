"""Host capability discovery for Sophyane Service Fabric."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import shutil


@dataclass(frozen=True)
class HostCapabilities:
    platform: str
    machine: str
    android: bool
    root: bool
    proot: bool
    docker: bool
    podman: bool
    low_port_binding_expected: bool
    service_execution: bool
    edge_client: bool


def detect_host_capabilities() -> HostCapabilities:
    prefix = str(
        os.environ.get(
            "PREFIX",
            ""
        )
    )

    android = bool(
        os.environ.get(
            "ANDROID_ROOT"
        )
        or os.environ.get(
            "ANDROID_DATA"
        )
        or "com.termux" in prefix
        or Path(
            "/system/build.prop"
        ).exists()
    )

    root = False

    try:
        root = (
            os.geteuid()
            == 0
        )
    except AttributeError:
        pass

    return HostCapabilities(
        platform=platform.system(),
        machine=platform.machine(),
        android=android,
        root=root,
        proot=bool(
            shutil.which(
                "proot"
            )
        ),
        docker=bool(
            shutil.which(
                "docker"
            )
        ),
        podman=bool(
            shutil.which(
                "podman"
            )
        ),
        low_port_binding_expected=(
            root
            and not android
        ),
        service_execution=True,
        edge_client=True,
    )
