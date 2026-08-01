"""Routing policy for compound agentic software tasks."""
from __future__ import annotations

import re
from dataclasses import dataclass


EXECUTION_VERBS = {
    "implement",
    "build",
    "create",
    "fix",
    "repair",
    "refactor",
    "replace",
    "optimize",
    "benchmark",
    "profile",
    "test",
    "verify",
    "audit",
    "analyze",
    "inspect",
    "review",
    "measure",
    "improve",
    "generate",
    "run",
    "continue",
}

SOFTWARE_TERMS = {
    "repository",
    "repo",
    "project",
    "code",
    "application",
    "api",
    "fastapi",
    "pytest",
    "dockerfile",
    "github actions",
    "mcp",
    "server",
    "architecture",
    "startup",
    "performance",
    "technical debt",
    "tests",
    "backend",
    "runtime",
}

PROTECTED_TERMS = {
    "nifdu": "NIFDU",
    "neuron": "local NIFDU Neuron runtime",
    "sli": "Sophyane Semantic Language Intelligence",
    "sophyane": "Sophyane",
    "mcp": "Model Context Protocol",
}


@dataclass(frozen=True)
class TaskPolicy:
    execution: bool
    compound: bool
    filesystem_only: bool
    protected_context: str


def normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _contains_phrase(text: str, phrase: str) -> bool:
    return phrase in text


def is_execution_request(message: str) -> bool:
    text = normalize(message)
    words = set(re.findall(r"[a-z0-9_+-]+", text))

    verb_hit = bool(words.intersection(EXECUTION_VERBS))
    domain_hit = any(
        _contains_phrase(text, term)
        for term in SOFTWARE_TERMS
    )

    long_loop = any(
        phrase in text
        for phrase in (
            "until all tests pass",
            "until everything passes",
            "continue until",
            "do not stop",
            "keep choosing",
            "take complete ownership",
            "for the next hour",
            "after every logical change",
        )
    )

    return (verb_hit and domain_hit) or long_loop


def is_compound_request(message: str) -> bool:
    text = normalize(message)

    connectors = (
        " and ",
        " then ",
        " after ",
        " until ",
        " while ",
        " one by one",
    )

    action_count = sum(
        1
        for verb in EXECUTION_VERBS
        if re.search(rf"\b{re.escape(verb)}\b", text)
    )

    return action_count >= 2 or sum(
        connector in text
        for connector in connectors
    ) >= 2


def filesystem_only_request(message: str) -> bool:
    text = normalize(message)

    fs_terms = (
        "file",
        "files",
        "folder",
        "folders",
        "directory",
        "directories",
        "storage",
        "duplicate",
        "largest",
        "biggest",
        "oldest",
        "newest",
        "modified",
    )

    non_fs_terms = (
        "dead code",
        "security",
        "architecture",
        "performance bottleneck",
        "refactor",
        "patch",
        "technical debt",
        "tests",
        "pytest",
        "implementation",
        "mcp server",
        "benchmark backend",
        "startup speed",
    )

    has_fs = any(term in text for term in fs_terms)
    has_non_fs = any(term in text for term in non_fs_terms)

    # Compound cleanup requests are still filesystem tasks when every requested
    # operation concerns files/storage.
    storage_workflow = (
        ("mobile" in text or "storage" in text)
        and any(term in text for term in ("largest", "duplicate"))
        and not has_non_fs
    )

    return has_fs and (not has_non_fs or storage_workflow)


def protected_context(message: str) -> str:
    text = normalize(message)
    lines = []

    for term, meaning in PROTECTED_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", text):
            lines.append(
                f"- {term}: preserve exact project meaning as {meaning}; "
                "do not reinterpret it as another vendor product."
            )

    return "\n".join(lines)


def classify(message: str) -> TaskPolicy:
    return TaskPolicy(
        execution=is_execution_request(message),
        compound=is_compound_request(message),
        filesystem_only=filesystem_only_request(message),
        protected_context=protected_context(message),
    )


def execution_prefix(message: str) -> str:
    policy = classify(message)

    parts = [
        "SOPHYANE EXECUTION CONTRACT:",
        "- This is an execution task, not a request for tutorial prose.",
        "- Use only executable JSON actions accepted by the runtime.",
        "- Inspect the real workspace before modifying files.",
        "- Run verification commands and use their actual exit codes.",
        "- Never claim success without execution evidence.",
        "- Preserve working files and stop safely on unrecoverable failure.",
    ]

    if policy.compound:
        parts.extend(
            [
                "- Decompose the request into all requested subgoals.",
                "- Do not satisfy only the first matching keyword.",
                "- Track unfinished acceptance criteria between actions.",
            ]
        )

    if policy.protected_context:
        parts.append("Protected project meanings:")
        parts.append(policy.protected_context)

    try:
        from sophyane.harness_acceptance import render
        acceptance = render(message)
    except Exception:
        acceptance = "- Complete the requested task with execution evidence."

    return (
        "\n".join(parts)
        + "\n\nACCEPTANCE CRITERIA:\n"
        + acceptance
        + "\n\nORIGINAL USER TASK:\n"
        + message
    )


__all__ = [
    "TaskPolicy",
    "classify",
    "execution_prefix",
    "filesystem_only_request",
    "is_compound_request",
    "is_execution_request",
    "normalize",
    "protected_context",
]
