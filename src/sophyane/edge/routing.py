"""Desired public-to-local routes for Sophyane Edge."""
from __future__ import annotations

from dataclasses import dataclass

from sophyane.service_fabric.manifest import (
    ServiceManifest,
)


@dataclass(frozen=True)
class EdgeRoute:
    service: str
    protocol: str
    local_host: str
    local_port: int
    public_port: int
    hostname: str
    tls: bool


def routes_from_manifest(
    manifest: ServiceManifest,
) -> tuple[EdgeRoute, ...]:
    routes = []

    for service in manifest.services:
        for publication in service.publish:
            routes.append(
                EdgeRoute(
                    service=service.name,
                    protocol=publication.protocol,
                    local_host="127.0.0.1",
                    local_port=publication.local_port,
                    public_port=publication.public_port,
                    hostname=publication.hostname,
                    tls=publication.tls,
                )
            )

    return tuple(
        routes
    )
