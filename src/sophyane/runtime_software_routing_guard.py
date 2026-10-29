"""Prevent software projects from being intercepted by editable canvas routing."""
from __future__ import annotations


def _is_software_project(message: str) -> bool:
    text = " ".join(str(message or "").lower().split())

    software_terms = (
        "index.html",
        "html",
        "javascript",
        "typescript",
        "python",
        "c++",
        "cpp",
        "source code",
        "browser game",
        "web app",
        "website",
        "api",
        "application",
        "program",
        "script",
        "repository",
        "compile",
        "pytest",
        "unit test",
        "verify it over http",
        "serve over http",
    )
    project_terms = (
        "make",
        "build",
        "create",
        "implement",
        "develop",
        "fix",
        "repair",
        "update",
        "generate",
    )

    return any(term in text for term in software_terms) and any(
        term in text for term in project_terms
    )


def install_software_routing_guard() -> None:
    """Give executable software projects priority over visual canvas sessions."""
    from sophyane import runtime_capability_acquisition_patch as capability

    current = capability._is_editable_session_request
    if getattr(current, "_sophyane_software_routing_guard", False):
        return

    def guarded(message: str) -> bool:
        if _is_software_project(message):
            return False
        return current(message)

    setattr(guarded, "_sophyane_software_routing_guard", True)
    capability._is_editable_session_request = guarded
