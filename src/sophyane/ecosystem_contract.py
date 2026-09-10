"""Canonical Shmry/Sophyane ecosystem contract loader.

Local repositories are authoritative when present.

Public GitHub manifests/README metadata may be used as bounded discovery
evidence when a peer repository is not installed locally.

Remote discovery never implies local execution readiness.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


SCHEMA = "sophyane-ecosystem-v1"

REPOSITORIES: dict[str, dict[str, str]] = {
    "neuron": {
        "owner": "badrpk",
        "repo": "neuron",
        "branch": "main",
    },
    "nifdu": {
        "owner": "badrpk",
        "repo": "nifdu",
        "branch": "master",
    },
    "xerus": {
        "owner": "badrpk",
        "repo": "xerus",
        "branch": "main",
    },
    "huobz": {
        "owner": "badrpk",
        "repo": "huobz",
        "branch": "main",
    },
    "rangoons": {
        "owner": "badrpk",
        "repo": "rangoons",
        "branch": "main",
    },
    "shmry": {
        "owner": "badrpk",
        "repo": "shmry",
        "branch": "main",
    },
    "veyron": {
        "owner": "badrpk",
        "repo": "Veyron",
        "branch": "main",
    },
}


@dataclass(frozen=True)
class EcosystemManifest:
    repository: str
    schema: str = ""
    component: str = ""
    role: str = ""
    capabilities: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    peers: tuple[tuple[str, str], ...] = ()
    transports: tuple[str, ...] = ()
    routing_policy: str = ""
    fallback: str = ""
    source: str = ""
    valid_contract: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)

        data["peers"] = {
            key: value
            for key, value
            in self.peers
        }

        return data


def _remote_enabled() -> bool:
    value = str(
        os.environ.get(
            "SOPHYANE_ECOSYSTEM_REMOTE",
            "1",
        )
        or ""
    ).strip().casefold()

    return value not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


def _remote_url(
    repository: str,
    relative: str,
) -> str:
    item = REPOSITORIES[
        repository.casefold()
    ]

    return (
        "https://raw.githubusercontent.com/"
        f"{item['owner']}/"
        f"{item['repo']}/"
        f"{item['branch']}/"
        f"{relative}"
    )


@lru_cache(maxsize=64)
def _fetch_remote_text_cached(
    repository: str,
    relative: str,
) -> str:
    url = _remote_url(
        repository,
        relative,
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Sophyane-Ecosystem/"
                "sophyane-ecosystem-v1"
            )
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=1.5,
        ) as response:
            raw = response.read(
                256_000
            )
    except (
        OSError,
        TimeoutError,
        urllib.error.URLError,
        urllib.error.HTTPError,
    ):
        return ""

    try:
        return raw.decode(
            "utf-8",
            errors="replace",
        )
    except Exception:
        return ""


def fetch_remote_text(
    repository: str,
    relative: str,
    *,
    loader: Callable[
        [str, str],
        str,
    ] | None = None,
) -> str:
    repository = str(
        repository
        or ""
    ).casefold()

    if repository not in REPOSITORIES:
        return ""

    if loader is not None:
        try:
            return str(
                loader(
                    repository,
                    relative,
                )
                or ""
            )
        except Exception:
            return ""

    if not _remote_enabled():
        return ""

    return _fetch_remote_text_cached(
        repository,
        relative,
    )


def _manifest_from_data(
    repository: str,
    data: object,
    *,
    source: str,
) -> EcosystemManifest | None:
    if not isinstance(
        data,
        dict,
    ):
        return None

    schema = str(
        data.get(
            "schema",
            "",
        )
        or ""
    ).strip()

    component = str(
        data.get(
            "component",
            repository,
        )
        or repository
    ).strip()

    role = str(
        data.get(
            "role",
            "",
        )
        or ""
    ).strip()

    raw_capabilities = data.get(
        "capabilities",
        [],
    )

    capabilities = tuple(
        sorted({
            str(item).strip().casefold()
            for item in (
                raw_capabilities
                if isinstance(
                    raw_capabilities,
                    list,
                )
                else []
            )
            if str(item).strip()
        })
    )

    raw_aliases = data.get(
        "aliases",
        [],
    )

    aliases = tuple(
        sorted({
            str(item).strip().casefold()
            for item in (
                raw_aliases
                if isinstance(
                    raw_aliases,
                    list,
                )
                else []
            )
            if str(item).strip()
        })
    )

    raw_peers = data.get(
        "peers",
        {},
    )

    peers: tuple[tuple[str, str], ...] = ()

    if isinstance(
        raw_peers,
        dict,
    ):
        peers = tuple(
            sorted(
                (
                    str(key).strip().casefold(),
                    str(value).strip().casefold(),
                )
                for key, value
                in raw_peers.items()
                if str(key).strip()
            )
        )

    routing = data.get(
        "routing",
        {},
    )

    if not isinstance(
        routing,
        dict,
    ):
        routing = {}

    raw_transport = routing.get(
        "transport",
        [],
    )

    transports = tuple(
        sorted({
            str(item).strip().casefold()
            for item in (
                raw_transport
                if isinstance(
                    raw_transport,
                    list,
                )
                else []
            )
            if str(item).strip()
        })
    )

    return EcosystemManifest(
        repository=repository,
        schema=schema,
        component=component,
        role=role,
        capabilities=capabilities,
        aliases=aliases,
        peers=peers,
        transports=transports,
        routing_policy=str(
            routing.get(
                "policy",
                "",
            )
            or ""
        ).strip(),
        fallback=str(
            routing.get(
                "fallback",
                "",
            )
            or ""
        ).strip(),
        source=source,
        valid_contract=(
            schema
            == SCHEMA
        ),
    )


def load_local_manifest(
    root: str | Path,
    *,
    repository: str,
) -> EcosystemManifest | None:
    path = (
        Path(root)
        / "ecosystem.json"
    )

    if not path.is_file():
        return None

    try:
        data = json.loads(
            path.read_text(
                errors="ignore"
            )
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None

    return _manifest_from_data(
        repository.casefold(),
        data,
        source="local",
    )


def load_remote_manifest(
    repository: str,
    *,
    loader: Callable[
        [str, str],
        str,
    ] | None = None,
) -> EcosystemManifest | None:
    repository = str(
        repository
        or ""
    ).casefold()

    text = fetch_remote_text(
        repository,
        "ecosystem.json",
        loader=loader,
    )

    if not text:
        return None

    try:
        data = json.loads(
            text
        )
    except (
        ValueError,
        json.JSONDecodeError,
    ):
        return None

    return _manifest_from_data(
        repository,
        data,
        source="github",
    )


def remote_repository_exists(
    repository: str,
    *,
    loader: Callable[
        [str, str],
        str,
    ] | None = None,
) -> bool:
    repository = str(
        repository
        or ""
    ).casefold()

    if repository not in REPOSITORIES:
        return False

    if load_remote_manifest(
        repository,
        loader=loader,
    ) is not None:
        return True

    readme = fetch_remote_text(
        repository,
        "README.md",
        loader=loader,
    )

    return bool(
        readme.strip()
    )


def remote_repository_metadata(
    repository: str,
    *,
    loader: Callable[
        [str, str],
        str,
    ] | None = None,
) -> str:
    return fetch_remote_text(
        repository,
        "README.md",
        loader=loader,
    )[:192_000]


__all__ = [
    "EcosystemManifest",
    "REPOSITORIES",
    "SCHEMA",
    "fetch_remote_text",
    "load_local_manifest",
    "load_remote_manifest",
    "remote_repository_exists",
    "remote_repository_metadata",
]
