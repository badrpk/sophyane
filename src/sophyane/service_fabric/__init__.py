"""Sophyane phone-native service fabric.

The service fabric provides a Docker/Podman-like service lifecycle at the
Sophyane orchestration level without pretending Android grants Linux kernel
container capabilities that are unavailable to the current process.

Core model:

    manifest
        -> validated service specification
        -> local unprivileged process
        -> managed state / health
        -> optional Sophyane Edge publication metadata

Public privileged ports remain the responsibility of an edge host or a host
with the required kernel privileges.
"""

from .manifest import (
    EdgePublication,
    HealthCheck,
    ServiceManifest,
    ServiceSpec,
    load_manifest,
)
from .runtime import (
    HostCapabilities,
    detect_host_capabilities,
)
from .supervisor import (
    ServiceSupervisor,
)

__all__ = [
    "EdgePublication",
    "HealthCheck",
    "HostCapabilities",
    "ServiceManifest",
    "ServiceSpec",
    "ServiceSupervisor",
    "detect_host_capabilities",
    "load_manifest",
]
