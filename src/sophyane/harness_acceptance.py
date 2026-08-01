"""Acceptance-criteria extraction for multi-step harness requests."""
from __future__ import annotations

import re


def normalize(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def criteria(message: str) -> list[str]:
    text = normalize(message)
    lower = text.casefold()
    selected: list[str] = []

    rules = (
        ("authentication", "Authentication is implemented and tested."),
        ("sqlite", "SQLite persistence is implemented."),
        ("tests", "Automated tests exist and pass."),
        ("dockerfile", "Dockerfile exists and is syntactically valid."),
        ("github actions", "GitHub Actions workflow exists."),
        ("readme", "README documents setup and usage."),
        ("dead code", "Dead-code findings are reported with file names."),
        ("duplicate logic", "Duplicate logic is distinguished from duplicate files."),
        ("performance bottleneck", "Performance bottlenecks are supported by evidence."),
        ("security", "Security findings include severity and exact locations."),
        ("20 largest", "The 20 largest files are listed."),
        ("duplicates larger than 50 mb", "Only duplicate groups above 50 MB are selected."),
        ("reclaimable", "Reclaimable storage is calculated without deleting files."),
        ("cleanup plan", "A non-destructive cleanup plan is produced."),
        ("mcp server", "An MCP server is implemented or upgraded."),
        ("every deterministic", "All registered deterministic capabilities are represented."),
        ("mcp client", "An MCP client-level handshake/tool-call verification is run."),
        ("pytest", "Pytest is executed using the active Python environment."),
        ("benchmark", "Benchmarks use measured values, not invented claims."),
        ("latency", "Latency is measured."),
        ("throughput", "Throughput is measured."),
        ("ram", "RAM use is measured where supported."),
        ("cpu", "CPU use is measured where supported."),
        ("startup time", "Startup time is measured."),
        ("technical debt", "Technical debt is prioritized."),
        ("preserving behaviour", "The full test suite passes after refactoring."),
        ("architecture", "Architecture components and interfaces are documented."),
        ("implementation roadmap", "An ordered implementation roadmap is produced."),
        ("30%", "Before/after measurements prove or disprove the 30% target."),
        ("next hour", "A durable mission is created for repeated work."),
        ("until i interrupt", "The loop supports external interruption."),
    )

    for marker, criterion in rules:
        if marker in lower and criterion not in selected:
            selected.append(criterion)

    # Preserve explicit sequential clauses as additional criteria.
    for fragment in re.split(
        r"\b(?:then|and then|after that|until)\b",
        text,
        flags=re.I,
    ):
        cleaned = fragment.strip(" ,.;:")
        if len(cleaned) >= 12:
            candidate = cleaned[0].upper() + cleaned[1:]
            if candidate not in selected:
                selected.append(candidate)

    return selected[:30]


def render(message: str) -> str:
    items = criteria(message)

    if not items:
        return "- Complete the requested task with execution evidence."

    return "\n".join(
        f"- [ ] {item}"
        for item in items
    )


__all__ = ["criteria", "render"]
