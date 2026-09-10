"""Badrpk repository capability discovery and ranking.

This module is deliberately provider-neutral.

It answers:

    Which repositories may help with this objective?

It does NOT answer:

    Which LLM/provider should execute the task?

Provider/session authority belongs to the runtime/provider layer.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


BADRPK_REPOSITORIES: tuple[str, ...] = (
    "neuron",
    "nifdu",
    "xerus",
    "huobz",
    "rangoons",
    "shmry",
    "veyron",
)

_METADATA_FILES: tuple[str, ...] = (
    "README.md",
    "README.rst",
    "README.txt",
    "pyproject.toml",
    "package.json",
    "setup.cfg",
    "setup.py",
)

_WORD = re.compile(
    r"[A-Za-z][A-Za-z0-9_.+-]{1,63}"
)

_GENERIC_TERMS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "build",
    "can",
    "code",
    "does",
    "for",
    "from",
    "have",
    "into",
    "make",
    "more",
    "project",
    "repo",
    "repository",
    "sophyane",
    "that",
    "the",
    "this",
    "use",
    "using",
    "want",
    "with",
}


@dataclass(frozen=True)
class RepositoryCapability:
    repository: str
    root: str
    available: bool
    local_available: bool = False
    remote_available: bool = False
    execution_ready: bool = False
    source: str = ""
    role: str = ""
    capabilities: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    transports: tuple[str, ...] = ()
    contract_valid: bool = False
    metadata_files: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    metadata_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankedCapability:
    repository: str
    root: str
    available: bool
    score: float
    lexical_score: float
    experience_score: float
    verified_successes: int
    matched_terms: tuple[str, ...] = ()
    metadata_files: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityPlan:
    objective: str
    repositories: tuple[RankedCapability, ...]
    discovered: tuple[str, ...]
    unavailable: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "repositories": [
                item.to_dict()
                for item in self.repositories
            ],
            "discovered": list(self.discovered),
            "unavailable": list(self.unavailable),
        }


def _tokens(value: object) -> set[str]:
    terms = {
        match.group(0).casefold()
        for match in _WORD.finditer(
            str(value or "")
        )
    }

    return {
        term
        for term in terms
        if (
            len(term) >= 3
            and term not in _GENERIC_TERMS
        )
    }


def _candidate_roots(
    workspace: str | Path | None = None,
) -> tuple[Path, ...]:
    candidates: list[Path] = []

    configured = str(
        os.environ.get(
            "SOPHYANE_BADRPK_ROOT",
            "",
        )
        or ""
    ).strip()

    if configured:
        candidates.append(
            Path(configured).expanduser()
        )

    if workspace is not None:
        root = (
            Path(workspace)
            .expanduser()
            .resolve()
        )

        candidates.extend(
            (
                root,
                root.parent,
                root.parent.parent,
            )
        )

    home = Path.home()

    candidates.extend(
        (
            home,
            home / "badrpk",
            home / "repos",
            home / "projects",
            home / "src",
        )
    )

    unique: list[Path] = []
    seen: set[str] = set()

    for item in candidates:
        try:
            resolved = item.resolve()
        except OSError:
            resolved = item

        key = str(resolved)

        if key in seen:
            continue

        seen.add(key)
        unique.append(resolved)

    return tuple(unique)


def _repo_path(
    repository: str,
    roots: Iterable[Path],
) -> Path | None:
    name = str(repository).strip()

    for root in roots:
        if root.name.casefold() == name.casefold():
            if root.is_dir():
                return root

        candidate = root / name

        if candidate.is_dir():
            return candidate

    return None


def _metadata_text(
    root: Path,
) -> tuple[str, tuple[str, ...]]:
    chunks: list[str] = []
    names: list[str] = []

    for relative in _METADATA_FILES:
        path = root / relative

        if not path.is_file():
            continue

        try:
            text = path.read_text(
                errors="ignore"
            )
        except OSError:
            continue

        if not text.strip():
            continue

        names.append(relative)

        # Keep discovery bounded. Repository source retrieval happens
        # later through the normal context/retrieval system.
        chunks.append(
            text[:64_000]
        )

    return (
        "\n".join(chunks)[:192_000],
        tuple(names),
    )


def discover_badrpk_capabilities(
    *,
    workspace: str | Path | None = None,
    roots: Iterable[str | Path] | None = None,
    remote_loader: Callable[
        [str, str],
        str,
    ] | None = None,
) -> tuple[RepositoryCapability, ...]:
    from sophyane.ecosystem_contract import (
        load_local_manifest,
        load_remote_manifest,
        remote_repository_exists,
        remote_repository_metadata,
    )

    if roots is None:
        search_roots = _candidate_roots(
            workspace
        )
    else:
        search_roots = tuple(
            Path(item).expanduser().resolve()
            for item in roots
        )

    discovered: list[RepositoryCapability] = []

    for repository in BADRPK_REPOSITORIES:
        path = _repo_path(
            repository,
            search_roots,
        )

        local_available = (
            path is not None
        )

        manifest = None
        metadata = ""
        files: tuple[str, ...] = ()

        if path is not None:
            metadata, files = _metadata_text(
                path
            )

            manifest = load_local_manifest(
                path,
                repository=repository,
            )

        remote_available = False

        if manifest is None:
            manifest = load_remote_manifest(
                repository,
                loader=remote_loader,
            )

        if not local_available:
            remote_available = (
                manifest is not None
                or remote_repository_exists(
                    repository,
                    loader=remote_loader,
                )
            )

            if not metadata:
                metadata = (
                    remote_repository_metadata(
                        repository,
                        loader=remote_loader,
                    )
                )

                if metadata:
                    files = (
                        "README.md",
                    )

        role = (
            manifest.role
            if manifest is not None
            else ""
        )

        capabilities = (
            manifest.capabilities
            if manifest is not None
            else ()
        )

        aliases = (
            manifest.aliases
            if manifest is not None
            else ()
        )

        transports = (
            manifest.transports
            if manifest is not None
            else ()
        )

        terms = _tokens(
            metadata
        )

        terms.update(
            _tokens(
                role
            )
        )

        for item in capabilities:
            terms.update(
                _tokens(
                    item
                )
            )

        for item in aliases:
            terms.update(
                _tokens(
                    item
                )
            )

        terms.add(
            repository.casefold()
        )

        available = bool(
            local_available
            or remote_available
        )

        # Remote discovery makes the capability visible to the graph,
        # but only a locally installed peer is directly executable in
        # Phase 2. On-demand peer materialisation arrives in Phase 3.
        execution_ready = bool(
            local_available
        )

        source = (
            "local"
            if local_available
            else (
                "github"
                if remote_available
                else "unavailable"
            )
        )

        discovered.append(
            RepositoryCapability(
                repository=repository,
                root=(
                    str(path)
                    if path is not None
                    else ""
                ),
                available=available,
                local_available=local_available,
                remote_available=remote_available,
                execution_ready=execution_ready,
                source=source,
                role=role,
                capabilities=capabilities,
                aliases=aliases,
                transports=transports,
                contract_valid=bool(
                    manifest
                    and manifest.valid_contract
                ),
                metadata_files=files,
                keywords=tuple(
                    sorted(terms)
                ),
                metadata_excerpt=metadata[:8000],
            )
        )

    return tuple(discovered)


def _default_history_reader(
    *,
    repository_identity: str,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        from sophyane.sli_learner import (
            read_verified_history,
        )

        return list(
            read_verified_history(
                repository_identity=repository_identity,
                limit=limit,
            )
        )
    except Exception:
        return []


def _experience_score(
    repository: str,
    history_reader: Callable[..., list[dict[str, Any]]],
) -> tuple[float, int]:
    records: list[dict[str, Any]] = []

    identities = (
        repository,
        f"badrpk/{repository}",
    )

    for identity in identities:
        try:
            found = history_reader(
                repository_identity=identity,
                limit=16,
            )
        except Exception:
            found = []

        for event in found or []:
            if isinstance(event, dict):
                records.append(event)

    unique: dict[str, dict[str, Any]] = {}

    for event in records:
        key = str(
            event.get("event_key")
            or event.get("trace_id")
            or json.dumps(
                event,
                sort_keys=True,
                default=str,
            )
        )

        unique[key] = event

    verified = tuple(
        event
        for event in unique.values()
        if (
            event.get("accepted") is True
            and str(
                event.get(
                    "verification_state",
                    "",
                )
            ).casefold()
            == "verified"
        )
    )

    if not verified:
        return 0.0, 0

    rewards: list[float] = []

    for event in verified:
        try:
            reward = float(
                event.get(
                    "reward",
                    1.0,
                )
            )
        except (TypeError, ValueError):
            reward = 1.0

        rewards.append(
            max(-1.0, min(1.0, reward))
        )

    average = (
        sum(rewards)
        / max(1, len(rewards))
    )

    # Historical experience should improve ranking,
    # but must not dominate semantic relevance.
    confidence = min(
        1.0,
        math.log2(
            len(verified) + 1
        )
        / 4.0,
    )

    return (
        max(
            -0.25,
            min(
                0.25,
                average
                * confidence
                * 0.25,
            ),
        ),
        len(verified),
    )


def rank_badrpk_capabilities(
    objective: str,
    *,
    workspace: str | Path | None = None,
    capabilities: Iterable[
        RepositoryCapability
    ] | None = None,
    history_reader: Callable[
        ...,
        list[dict[str, Any]],
    ] | None = None,
    limit: int = 4,
) -> tuple[RankedCapability, ...]:
    request_terms = _tokens(
        objective
    )

    catalog = tuple(
        capabilities
        if capabilities is not None
        else discover_badrpk_capabilities(
            workspace=workspace
        )
    )

    reader = (
        history_reader
        or _default_history_reader
    )

    ranked: list[RankedCapability] = []

    for capability in catalog:
        repo_terms = set(
            capability.keywords
        )

        matched = tuple(
            sorted(
                request_terms
                & repo_terms
            )
        )

        direct_reference = (
            capability.repository.casefold()
            in request_terms
        )

        lexical = 0.0

        if request_terms:
            lexical = (
                len(matched)
                / max(
                    1,
                    len(request_terms),
                )
            )

        if direct_reference:
            lexical += 0.75

        # Repository metadata may mention objective words many times,
        # but ranking is intentionally based on unique-term evidence.
        lexical = min(
            1.0,
            lexical,
        )

        experience, successes = (
            _experience_score(
                capability.repository,
                reader,
            )
        )

        if capability.execution_ready:
            availability_bonus = 0.05
        elif capability.remote_available:
            # Remote peers are useful graph/context candidates but should
            # rank just below equivalent locally executable peers.
            availability_bonus = 0.02
        else:
            availability_bonus = -0.50

        score = (
            lexical
            + experience
            + availability_bonus
        )

        reasons: list[str] = []

        if direct_reference:
            reasons.append(
                "explicit_repository_reference"
            )

        if matched:
            reasons.append(
                "semantic_metadata_match"
            )

        if successes:
            reasons.append(
                "verified_execution_history"
            )

        if capability.execution_ready:
            reasons.append(
                "repository_local_execution_ready"
            )
        elif capability.remote_available:
            reasons.append(
                "repository_remote_discoverable"
            )
        else:
            reasons.append(
                "repository_unavailable"
            )

        ranked.append(
            RankedCapability(
                repository=capability.repository,
                root=capability.root,
                available=capability.available,
                score=round(
                    score,
                    6,
                ),
                lexical_score=round(
                    lexical,
                    6,
                ),
                experience_score=round(
                    experience,
                    6,
                ),
                verified_successes=successes,
                matched_terms=matched,
                metadata_files=capability.metadata_files,
                reason=",".join(
                    reasons
                ),
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.score,
            -int(item.available),
            item.repository,
        )
    )

    bounded = max(
        1,
        min(
            int(limit),
            len(ranked)
            if ranked
            else 1,
        ),
    )

    return tuple(
        ranked[:bounded]
    )


def build_capability_plan(
    objective: str,
    *,
    workspace: str | Path | None = None,
    limit: int = 4,
) -> CapabilityPlan:
    catalog = discover_badrpk_capabilities(
        workspace=workspace
    )

    ranked = rank_badrpk_capabilities(
        objective,
        workspace=workspace,
        capabilities=catalog,
        limit=limit,
    )

    available = tuple(
        item.repository
        for item in catalog
        if item.available
    )

    unavailable = tuple(
        item.repository
        for item in catalog
        if not item.available
    )

    return CapabilityPlan(
        objective=str(
            objective or ""
        ),
        repositories=ranked,
        discovered=available,
        unavailable=unavailable,
    )


def capability_plan_dict(
    objective: str,
    *,
    workspace: str | Path | None = None,
    limit: int = 4,
) -> dict[str, Any]:
    return build_capability_plan(
        objective,
        workspace=workspace,
        limit=limit,
    ).to_dict()


__all__ = [
    "BADRPK_REPOSITORIES",
    "CapabilityPlan",
    "RankedCapability",
    "RepositoryCapability",
    "build_capability_plan",
    "capability_plan_dict",
    "discover_badrpk_capabilities",
    "rank_badrpk_capabilities",
]
