"""Safe workspace selection for agentic build requests."""
from __future__ import annotations

import hashlib
from pathlib import Path


NEW_PROJECT_PHRASES = (
    "create a complete",
    "build a complete",
    "create a new",
    "build a new",
    "starting from scratch",
)


def normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def is_new_project_request(message: str) -> bool:
    text = normalize(message)

    project_terms = (
        "application",
        "app",
        "website",
        "api",
        "service",
        "project",
    )

    creation_terms = (
        "create",
        "build",
        "implement",
        "generate",
        "scaffold",
        "develop",
    )

    explicit_new_project = (
        any(phrase in text for phrase in NEW_PROJECT_PHRASES)
        and any(term in text for term in project_terms)
    )

    # Semantic refinement may rewrite "create a complete" into wording such
    # as "implement a fully functional". Preserve standalone isolation for
    # unmistakable application-generation requests.
    strong_application_request = (
        any(term in text for term in creation_terms)
        and any(term in text for term in project_terms)
        and (
            "fastapi" in text
            or "todo application" in text
            or "dockerfile" in text
            or "github actions" in text
        )
    )

    return explicit_new_project or strong_application_request


def project_slug(message: str) -> str:
    text = normalize(message)

    preferred = (
        ("fastapi", "fastapi-project"),
        ("todo", "todo-application"),
        ("mcp", "mcp-project"),
        ("website", "website-project"),
    )

    parts = [
        name
        for keyword, name in preferred
        if keyword in text
    ]

    if parts:
        return "-".join(dict.fromkeys(parts))

    digest = hashlib.sha256(
        message.encode("utf-8", errors="replace")
    ).hexdigest()[:8]

    return f"generated-project-{digest}"


def select_workspace(
    message: str,
    current: str | Path,
) -> Path:
    current_path = Path(current).expanduser().resolve()

    if not is_new_project_request(message):
        return current_path

    root = (
        Path.home()
        / ".sophyane"
        / "generated-projects"
    )
    root.mkdir(parents=True, exist_ok=True)

    destination = root / project_slug(message)
    destination.mkdir(parents=True, exist_ok=True)

    return destination.resolve()


__all__ = [
    "is_new_project_request",
    "project_slug",
    "select_workspace",
]
