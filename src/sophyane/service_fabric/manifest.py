"""Strict service-manifest schema for Sophyane Service Fabric."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any


_NAME = re.compile(
    r"^[a-z][a-z0-9_-]{0,62}$"
)


@dataclass(frozen=True)
class HealthCheck:
    kind: str = "process"
    host: str = "127.0.0.1"
    port: int = 0
    path: str = "/"
    timeout_seconds: float = 2.0


@dataclass(frozen=True)
class EdgePublication:
    protocol: str
    local_port: int
    public_port: int = 0
    hostname: str = ""
    tls: bool = False


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    command: tuple[str, ...]
    workdir: str = "."
    environment: dict[str, str] = field(
        default_factory=dict
    )
    restart: str = "on-failure"
    health: HealthCheck = field(
        default_factory=HealthCheck
    )
    publish: tuple[EdgePublication, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceManifest:
    name: str
    services: tuple[ServiceSpec, ...]
    version: int = 1


def _require_name(
    value: object,
    *,
    field_name: str,
) -> str:
    text = str(
        value
        or ""
    ).strip()

    if not _NAME.fullmatch(
        text
    ):
        raise ValueError(
            f"invalid {field_name}: {text!r}"
        )

    return text


def _port(
    value: object,
    *,
    allow_zero: bool = False,
) -> int:
    try:
        port = int(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"invalid port: {value!r}"
        ) from error

    minimum = (
        0
        if allow_zero
        else 1
    )

    if not (
        minimum
        <= port
        <= 65535
    ):
        raise ValueError(
            f"invalid port: {port}"
        )

    return port


def _health(
    payload: object,
) -> HealthCheck:
    if payload is None:
        return HealthCheck()

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "health must be an object"
        )

    kind = str(
        payload.get(
            "kind",
            "process",
        )
    ).strip().casefold()

    if kind not in {
        "process",
        "tcp",
        "http",
    }:
        raise ValueError(
            f"unsupported health kind: {kind}"
        )

    port = _port(
        payload.get(
            "port",
            0,
        ),
        allow_zero=True,
    )

    if (
        kind in {
            "tcp",
            "http",
        }
        and port == 0
    ):
        raise ValueError(
            f"{kind} health requires port"
        )

    timeout = float(
        payload.get(
            "timeout_seconds",
            2.0,
        )
    )

    if not (
        0.1
        <= timeout
        <= 60.0
    ):
        raise ValueError(
            "health timeout out of bounds"
        )

    return HealthCheck(
        kind=kind,
        host=str(
            payload.get(
                "host",
                "127.0.0.1",
            )
            or "127.0.0.1"
        ),
        port=port,
        path=str(
            payload.get(
                "path",
                "/",
            )
            or "/"
        ),
        timeout_seconds=timeout,
    )


def _publication(
    payload: object,
) -> EdgePublication:
    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "publish entries must be objects"
        )

    protocol = str(
        payload.get(
            "protocol",
            ""
        )
    ).strip().casefold()

    if protocol not in {
        "tcp",
        "http",
        "https",
    }:
        raise ValueError(
            f"unsupported publication protocol: {protocol}"
        )

    local_port = _port(
        payload.get(
            "local_port"
        )
    )

    public_port = _port(
        payload.get(
            "public_port",
            0,
        ),
        allow_zero=True,
    )

    hostname = str(
        payload.get(
            "hostname",
            ""
        )
    ).strip().casefold()

    if (
        protocol in {
            "http",
            "https",
        }
        and not hostname
        and public_port == 0
    ):
        raise ValueError(
            "HTTP publication requires hostname or public_port"
        )

    return EdgePublication(
        protocol=protocol,
        local_port=local_port,
        public_port=public_port,
        hostname=hostname,
        tls=bool(
            payload.get(
                "tls",
                protocol == "https",
            )
        ),
    )


def _service(
    payload: object,
) -> ServiceSpec:
    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "service must be an object"
        )

    name = _require_name(
        payload.get(
            "name"
        ),
        field_name="service name",
    )

    raw_command = payload.get(
        "command"
    )

    if (
        not isinstance(
            raw_command,
            list,
        )
        or not raw_command
        or not all(
            isinstance(
                token,
                str,
            )
            and token
            for token in raw_command
        )
    ):
        raise ValueError(
            f"service {name}: command must be a non-empty string array"
        )

    restart = str(
        payload.get(
            "restart",
            "on-failure",
        )
    ).strip().casefold()

    if restart not in {
        "no",
        "on-failure",
        "always",
    }:
        raise ValueError(
            f"service {name}: invalid restart policy"
        )

    raw_env = payload.get(
        "environment",
        {}
    )

    if not isinstance(
        raw_env,
        dict,
    ):
        raise ValueError(
            f"service {name}: environment must be an object"
        )

    environment = {
        str(
            key
        ):
        str(
            value
        )
        for key, value in raw_env.items()
    }

    raw_publish = payload.get(
        "publish",
        [],
    )

    if not isinstance(
        raw_publish,
        list,
    ):
        raise ValueError(
            f"service {name}: publish must be an array"
        )

    raw_dependencies = payload.get(
        "depends_on",
        [],
    )

    if not isinstance(
        raw_dependencies,
        list,
    ):
        raise ValueError(
            f"service {name}: depends_on must be an array"
        )

    depends_on = tuple(
        _require_name(
            item,
            field_name="dependency",
        )
        for item in raw_dependencies
    )

    return ServiceSpec(
        name=name,
        command=tuple(
            raw_command
        ),
        workdir=str(
            payload.get(
                "workdir",
                ".",
            )
            or "."
        ),
        environment=environment,
        restart=restart,
        health=_health(
            payload.get(
                "health"
            )
        ),
        publish=tuple(
            _publication(
                item
            )
            for item in raw_publish
        ),
        depends_on=depends_on,
    )


def manifest_from_dict(
    payload: dict[str, Any],
) -> ServiceManifest:
    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "manifest must be an object"
        )

    version = int(
        payload.get(
            "version",
            1,
        )
    )

    if version != 1:
        raise ValueError(
            f"unsupported manifest version: {version}"
        )

    name = _require_name(
        payload.get(
            "name"
        ),
        field_name="manifest name",
    )

    raw_services = payload.get(
        "services"
    )

    if (
        not isinstance(
            raw_services,
            list,
        )
        or not raw_services
    ):
        raise ValueError(
            "manifest requires at least one service"
        )

    services = tuple(
        _service(
            item
        )
        for item in raw_services
    )

    names = [
        item.name
        for item in services
    ]

    if len(
        set(
            names
        )
    ) != len(
        names
    ):
        raise ValueError(
            "duplicate service name"
        )

    name_set = set(
        names
    )

    for service in services:
        unknown = set(
            service.depends_on
        ) - name_set

        if unknown:
            raise ValueError(
                f"service {service.name}: unknown dependencies: "
                + ", ".join(
                    sorted(
                        unknown
                    )
                )
            )

        if service.name in service.depends_on:
            raise ValueError(
                f"service {service.name}: cannot depend on itself"
            )

    return ServiceManifest(
        name=name,
        services=services,
        version=version,
    )


def load_manifest(
    path: Path | str,
) -> ServiceManifest:
    source = Path(
        path
    )

    payload = json.loads(
        source.read_text(
            encoding="utf-8",
        )
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "manifest root must be an object"
        )

    return manifest_from_dict(
        payload
    )
