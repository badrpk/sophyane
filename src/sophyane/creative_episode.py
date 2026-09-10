"""Verified creative-product episodic memory.

Sophyane owns construction from verified execution evidence.
Neuron may contribute an advisory perceptual context.
Xerus owns authoritative durable episode persistence.

This module never makes a visual-quality acceptance decision.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

SCHEMA = 1
NAMESPACE = "creative-product-episode"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    target = Path(path).expanduser().resolve()
    return _sha256_bytes(target.read_bytes())


def objective_hash(objective: str) -> str:
    normalized = " ".join(str(objective or "").strip().split())
    return _sha256_bytes(normalized.encode("utf-8"))


def _repo_map_path() -> Path:
    configured = os.environ.get(
        "SOPHYANE_ECOSYSTEM_REPO_MAP",
        "",
    ).strip()

    if configured:
        return Path(configured).expanduser().resolve()

    return (
        Path.cwd()
        / ".sophyane"
        / "ecosystem"
        / "local-repos.json"
    ).resolve()


def _repo_map() -> dict[str, Path]:
    path = _repo_map_path()

    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    repositories = raw.get("repositories", {})

    if not isinstance(repositories, dict):
        return {}

    result: dict[str, Path] = {}

    for name, value in repositories.items():
        candidate = Path(str(value)).expanduser()

        try:
            candidate = candidate.resolve()
        except OSError:
            continue

        result[str(name).casefold()] = candidate

    return result


def _repository(name: str, fallback: Path) -> Path:
    return _repo_map().get(
        name.casefold(),
        fallback.expanduser().resolve(),
    )


@dataclass(frozen=True)
class CreativeEpisode:
    schema: int
    episode_id: str
    created_at: float

    objective_hash: str
    objective: str

    artifact_sha256: str
    screenshot_sha256: str
    parent_artifact_sha256: str

    iteration: int
    provider_id: str

    viewport_width: int
    viewport_height: int
    document_width: int
    document_height: int

    images: int
    broken_images: int
    console_errors: int
    log_errors: int
    horizontal_overflow: bool

    judge_score: int
    critical_issues: int
    unmet_requirements: int
    repair_code: str
    accepted: bool

    previous_score: int | None
    score_delta: int | None

    perceptual_signature: str
    pixel_digest: str
    design_summary: str

    perception_status: str
    perception_error: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _episode_id(
    *,
    objective_digest: str,
    artifact_digest: str,
    screenshot_digest: str,
    iteration: int,
) -> str:
    raw = (
        objective_digest
        + "\0"
        + artifact_digest
        + "\0"
        + screenshot_digest
        + "\0"
        + str(int(iteration))
    )

    return _sha256_bytes(
        raw.encode("utf-8")
    )[:32]


def build_episode(
    *,
    objective: str,
    artifact_path: str | Path,
    screenshot_path: str | Path,
    iteration: int,
    provider_id: str,
    rendered: Any,
    report: dict[str, Any],
    parent_artifact_sha256: str = "",
    previous_score: int | None = None,
    design_summary: str = "",
) -> CreativeEpisode:
    artifact = Path(artifact_path).expanduser().resolve()
    screenshot = Path(screenshot_path).expanduser().resolve()

    if not artifact.is_file():
        raise FileNotFoundError(
            f"creative artifact missing: {artifact}"
        )

    if not screenshot.is_file():
        raise FileNotFoundError(
            f"creative screenshot missing: {screenshot}"
        )

    objective_text = " ".join(
        str(objective or "").strip().split()
    )

    objective_digest = objective_hash(objective_text)
    artifact_digest = sha256_file(artifact)
    screenshot_digest = sha256_file(screenshot)

    score = int(report.get("score", 0) or 0)

    delta = (
        None
        if previous_score is None
        else score - int(previous_score)
    )

    return CreativeEpisode(
        schema=SCHEMA,
        episode_id=_episode_id(
            objective_digest=objective_digest,
            artifact_digest=artifact_digest,
            screenshot_digest=screenshot_digest,
            iteration=iteration,
        ),
        created_at=time.time(),
        objective_hash=objective_digest,
        objective=objective_text,
        artifact_sha256=artifact_digest,
        screenshot_sha256=screenshot_digest,
        parent_artifact_sha256=str(
            parent_artifact_sha256 or ""
        ),
        iteration=int(iteration),
        provider_id=str(provider_id or ""),
        viewport_width=int(
            getattr(rendered, "viewport_width", 0) or 0
        ),
        viewport_height=int(
            getattr(rendered, "viewport_height", 0) or 0
        ),
        document_width=int(
            getattr(rendered, "document_width", 0) or 0
        ),
        document_height=int(
            getattr(rendered, "document_height", 0) or 0
        ),
        images=int(
            getattr(rendered, "images", 0) or 0
        ),
        broken_images=int(
            getattr(rendered, "broken_images", 0) or 0
        ),
        console_errors=int(
            getattr(rendered, "console_errors", 0) or 0
        ),
        log_errors=int(
            getattr(rendered, "log_errors", 0) or 0
        ),
        horizontal_overflow=bool(
            getattr(rendered, "horizontal_overflow", False)
        ),
        judge_score=score,
        critical_issues=int(
            report.get("critical_issues", 0) or 0
        ),
        unmet_requirements=int(
            report.get("unmet_requirements", 0) or 0
        ),
        repair_code=str(
            report.get("repair_code", "") or ""
        ),
        accepted=bool(
            report.get("accepted", False)
        ),
        previous_score=previous_score,
        score_delta=delta,
        perceptual_signature="",
        pixel_digest="",
        design_summary=str(
            design_summary or ""
        ).strip(),
        perception_status="pending",
        perception_error="",
    )


def enrich_with_neuron(
    episode: CreativeEpisode,
    *,
    screenshot_path: str | Path,
) -> CreativeEpisode:
    root = _repository(
        "neuron",
        Path.home() / "badrpk-repos" / "neuron",
    )

    embodiment = root / "embodiment"

    if not embodiment.is_dir():
        return episode

    inserted = False

    if str(embodiment) not in sys.path:
        sys.path.insert(0, str(embodiment))
        inserted = True

    try:
        module = importlib.import_module(
            "perception.perceptual_context"
        )

        builder = module.PerceptualContextBuilder()

        context = builder.build(
            screenshot_path=str(
                Path(screenshot_path)
                .expanduser()
                .resolve()
            ),
            semantic_gist=episode.objective,
        )

        return replace(
            episode,
            perceptual_signature=str(
                context.context_key
            ),
            pixel_digest=str(
                context.pixel_digest
            ),
            perception_status="ok",
            perception_error="",
        )

    except Exception as exc:
        # Neuron perception is advisory. Its failure must not
        # corrupt or suppress verified NIFDU evidence.
        return replace(
            episode,
            perception_status="unavailable",
            perception_error=(
                type(exc).__name__
                + ": "
                + str(exc)
            )[:1000],
        )

    finally:
        if inserted:
            try:
                sys.path.remove(str(embodiment))
            except ValueError:
                pass


def searchable_content(
    episode: CreativeEpisode,
) -> str:
    outcome = (
        "accepted"
        if episode.accepted
        else "rejected"
    )

    parts = [
        "creative product episode",
        episode.objective,
        f"outcome {outcome}",
        f"score {episode.judge_score}",
        f"repair {episode.repair_code or 'NONE'}",
        f"iteration {episode.iteration}",
    ]

    if episode.perceptual_signature:
        parts.append(
            "perceptual context "
            + episode.perceptual_signature
        )

    if episode.design_summary:
        parts.append(
            "design "
            + episode.design_summary
        )

    if episode.perception_status:
        parts.append(
            "perception "
            + episode.perception_status
        )

    return " | ".join(parts)


def persist_to_xerus(
    episode: CreativeEpisode,
) -> dict[str, Any]:
    root = _repository(
        "xerus",
        Path.home() / "badrpk-repos" / "xerus",
    )

    source = root / "src"

    if not source.is_dir():
        return {
            "ok": False,
            "reason": "xerus source unavailable",
        }

    inserted = False

    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
        inserted = True

    try:
        module = importlib.import_module(
            "xerus.memory"
        )

        return module.remember(
            searchable_content(episode),
            namespace=NAMESPACE,
            memory_key=(
                "creative:"
                + episode.episode_id
            ),
            metadata=episode.to_dict(),
        )

    except Exception as exc:
        return {
            "ok": False,
            "reason": (
                type(exc).__name__
                + ": "
                + str(exc)
            ),
        }

    finally:
        if inserted:
            try:
                sys.path.remove(str(source))
            except ValueError:
                pass


def recall_creative_episodes(
    query: str,
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    root = _repository(
        "xerus",
        Path.home() / "badrpk-repos" / "xerus",
    )

    source = root / "src"

    if not source.is_dir():
        return []

    inserted = False

    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
        inserted = True

    try:
        module = importlib.import_module(
            "xerus.memory"
        )

        return list(
            module.recall(
                str(query or ""),
                namespace=NAMESPACE,
                limit=max(
                    1,
                    min(int(limit), 20),
                ),
            )
        )

    except Exception:
        return []

    finally:
        if inserted:
            try:
                sys.path.remove(str(source))
            except ValueError:
                pass


__all__ = [
    "CreativeEpisode",
    "NAMESPACE",
    "build_episode",
    "enrich_with_neuron",
    "objective_hash",
    "persist_to_xerus",
    "recall_creative_episodes",
    "searchable_content",
    "sha256_file",
]
