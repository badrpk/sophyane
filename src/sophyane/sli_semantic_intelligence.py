"""Deterministic semantic intelligence for SLI code memory.

This module adds an LLM-free semantic pipeline:

request
  -> intent concepts
  -> capability decomposition
  -> per-capability chunk retrieval
  -> compatibility reranking
  -> coverage contract
  -> artifact validation feedback

It does not contain product templates and does not call an LLM.
"""
from __future__ import annotations

import math
import re

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


# ------------------------------------------------------------------
# Generic capability ontology
# ------------------------------------------------------------------

CAPABILITY_ONTOLOGY: dict[str, dict[str, Any]] = {
    "document_shell": {
        "concepts": {
            "html",
            "website",
            "webpage",
            "web app",
            "browser",
            "frontend",
            "page",
            "ui",
            "interface",
        },
        "signals": {
            "<!doctype",
            "<html",
            "<head",
            "<body",
        },
        "preferred_languages": {"html"},
        "placements": {
            "html_document",
            "document",
            "compound",
            "fragment",
        },
    },

    "presentation": {
        "concepts": {
            "style",
            "responsive",
            "layout",
            "design",
            "interface",
            "ui",
            "dashboard",
            "website",
            "webpage",
            "game",
        },
        "signals": {
            "<style",
            "display:",
            "grid",
            "flex",
            "media",
            "class=",
        },
        "preferred_languages": {"css", "html"},
        "placements": {
            "style",
            "html_document",
            "compound",
        },
    },

    "application_state": {
        "concepts": {
            "state",
            "game",
            "quiz",
            "form",
            "calculator",
            "dashboard",
            "todo",
            "task",
            "editor",
            "simulation",
            "score",
            "progress",
        },
        "signals": {
            "let ",
            "const ",
            "state",
            "score",
            "current",
            "reset",
            "update",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "python",
        },
        "placements": {
            "script",
            "function",
            "module",
            "compound",
        },
    },

    "user_input": {
        "concepts": {
            "interactive",
            "playable",
            "game",
            "quiz",
            "form",
            "input",
            "button",
            "keyboard",
            "mouse",
            "touch",
            "controls",
            "click",
            "answer",
        },
        "signals": {
            "addeventlistener",
            "onclick",
            "onkeydown",
            "keydown",
            "keyup",
            "pointerdown",
            "pointerup",
            "touchstart",
            "mousedown",
            "<input",
            "<button",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "html",
        },
        "placements": {
            "script",
            "function",
            "html_document",
            "compound",
        },
    },

    "rendering": {
        "concepts": {
            "game",
            "canvas",
            "drawing",
            "animation",
            "simulation",
            "chart",
            "visual",
            "render",
            "browser",
            "interactive",
        },
        "signals": {
            "<canvas",
            "getcontext",
            "fillrect",
            "drawimage",
            "innerhtml",
            "textcontent",
            "appendchild",
            "render",
            "draw",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "html",
        },
        "placements": {
            "script",
            "function",
            "html_document",
            "compound",
        },
    },

    "time_loop": {
        "concepts": {
            "game",
            "animation",
            "simulation",
            "timer",
            "clock",
            "playable",
            "moving",
            "loop",
            "real time",
        },
        "signals": {
            "requestanimationframe",
            "setinterval",
            "settimeout",
            "tick",
            "loop",
            "animate",
            "update",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "python",
        },
        "placements": {
            "script",
            "function",
            "module",
            "compound",
        },
    },

    "rules_and_validation": {
        "concepts": {
            "game",
            "quiz",
            "answer",
            "correct",
            "incorrect",
            "validate",
            "check",
            "rules",
            "win",
            "lose",
            "collision",
            "missing",
        },
        "signals": {
            "if ",
            "validate",
            "correct",
            "incorrect",
            "collision",
            "answer",
            "check",
            "match",
            "includes",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "python",
        },
        "placements": {
            "function",
            "script",
            "module",
            "compound",
        },
    },

    "progress_feedback": {
        "concepts": {
            "game",
            "quiz",
            "score",
            "progress",
            "feedback",
            "result",
            "correct",
            "incorrect",
            "status",
            "message",
        },
        "signals": {
            "score",
            "progress",
            "feedback",
            "status",
            "message",
            "textcontent",
            "innerhtml",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "html",
        },
        "placements": {
            "script",
            "function",
            "html_document",
            "compound",
        },
    },

    "lifecycle_control": {
        "concepts": {
            "game",
            "quiz",
            "restart",
            "reset",
            "start",
            "stop",
            "next",
            "new",
            "play again",
            "clear",
        },
        "signals": {
            "restart",
            "reset",
            "initialize",
            "init",
            "start",
            "stop",
            "next",
            "newgame",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "python",
            "html",
        },
        "placements": {
            "function",
            "script",
            "module",
            "html_document",
            "compound",
        },
    },

    "data_model": {
        "concepts": {
            "list",
            "record",
            "database",
            "data",
            "dataset",
            "question",
            "sentence",
            "letter",
            "word",
            "task",
            "todo",
            "item",
            "inventory",
        },
        "signals": {
            "array",
            "list",
            "items",
            "data",
            "questions",
            "sentences",
            "words",
            "objects",
            "json",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "python",
            "json",
        },
        "placements": {
            "module",
            "script",
            "function",
            "compound",
        },
    },

    "persistence": {
        "concepts": {
            "save",
            "persist",
            "storage",
            "remember",
            "history",
            "database",
            "localstorage",
        },
        "signals": {
            "localstorage",
            "sessionstorage",
            "json.dump",
            "json.load",
            "write_text",
            "read_text",
            "database",
        },
        "preferred_languages": {
            "javascript",
            "typescript",
            "python",
        },
        "placements": {
            "module",
            "script",
            "function",
            "compound",
        },
    },

    # SOPHYANE_OPERATIONAL_CAPABILITY_ONTOLOGY_V1
    "process_supervision": {
        "concepts": {
            "process",
            "processes",
            "background process",
            "daemon",
            "service",
            "monitor",
            "monitoring",
            "supervise",
            "supervision",
            "pid",
            "long-running",
        },
        "signals": {
            "subprocess",
            "popen",
            "poll(",
            "pid",
            "psutil",
            "process",
            "kill(",
            "terminate(",
            "wait(",
        },
        "preferred_languages": {
            "python",
            "shell",
            "bash",
        },
        "placements": {
            "python_module",
            "module",
            "function",
            "script",
            "compound",
        },
    },

    "log_diagnostics": {
        "concepts": {
            "log",
            "logs",
            "crash log",
            "daemon log",
            "stderr",
            "stdout",
            "diagnose",
            "diagnostic",
            "failure",
        },
        "signals": {
            "read_text",
            "open(",
            "stderr",
            "stdout",
            "tail",
            "journalctl",
            "log",
            "traceback",
        },
        "preferred_languages": {
            "python",
            "shell",
            "bash",
        },
        "placements": {
            "python_module",
            "module",
            "function",
            "script",
            "compound",
        },
    },

    "resource_diagnostics": {
        "concepts": {
            "memory",
            "out-of-memory",
            "oom",
            "resource",
            "resources",
            "cpu",
            "memory pressure",
            "diagnose",
        },
        "signals": {
            "memory",
            "rss",
            "psutil",
            "oom",
            "resource",
            "getrusage",
            "/proc/",
        },
        "preferred_languages": {
            "python",
            "shell",
            "bash",
        },
        "placements": {
            "python_module",
            "module",
            "function",
            "script",
            "compound",
        },
    },

    "network_port_diagnostics": {
        "concepts": {
            "port",
            "port-binding",
            "bind",
            "binding",
            "socket",
            "listen",
            "conflict",
            "address in use",
        },
        "signals": {
            "socket",
            "bind(",
            "listen(",
            "ss ",
            "netstat",
            "lsof",
            "address already in use",
            "eaddrinuse",
        },
        "preferred_languages": {
            "python",
            "shell",
            "bash",
        },
        "placements": {
            "python_module",
            "module",
            "function",
            "script",
            "compound",
        },
    },

    "safe_command_execution": {
        "concepts": {
            "shell",
            "command",
            "commands",
            "script",
            "scripts",
            "execute",
            "corrective",
            "remediation",
            "safe",
            "safety",
            "guardrails",
        },
        "signals": {
            "subprocess.run",
            "subprocess.Popen",
            "shlex",
            "shell=False",
            "check=True",
            "timeout=",
            "allowlist",
            "denylist",
        },
        "preferred_languages": {
            "python",
            "shell",
            "bash",
        },
        "placements": {
            "python_module",
            "module",
            "function",
            "script",
            "compound",
        },
    },

    "http_endpoint": {
        "concepts": {
            "api",
            "endpoint",
            "route",
            "fastapi",
            "flask",
            "express",
            "starlette",
            "health",
            "server",
            "http",
        },
        "signals": {
            "@app.get",
            "@app.post",
            "app.get(",
            "app.post(",
            "route(",
            "fastapi(",
            "flask(",
            "router",
        },
        "preferred_languages": {
            "python",
            "javascript",
            "typescript",
        },
        "placements": {
            "python_module",
            "module",
            "function",
            "script",
            "compound",
        },
    },

    "error_handling": {
        "concepts": {
            "error",
            "exception",
            "failure",
            "invalid",
            "fallback",
            "recover",
            "safe",
            "validation",
        },
        "signals": {
            "try:",
            "except ",
            "catch",
            "throw",
            "raise",
            "error",
            "invalid",
        },
        "preferred_languages": {
            "python",
            "javascript",
            "typescript",
        },
        "placements": {
            "function",
            "module",
            "script",
            "compound",
        },
    },

    "entry_point": {
        "concepts": {
            "application",
            "app",
            "program",
            "script",
            "run",
            "server",
            "cli",
            "main",
        },
        "signals": {
            "__main__",
            "main(",
            "DOMContentLoaded",
            "window.onload",
            "initialize",
            "init(",
        },
        "preferred_languages": {
            "python",
            "javascript",
            "typescript",
            "html",
        },
        "placements": {
            "python_module",
            "module",
            "script",
            "html_document",
            "compound",
        },
    },
}


STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "build",
    "by",
    "code",
    "complete",
    "create",
    "develop",
    "for",
    "from",
    "generate",
    "implement",
    "in",
    "into",
    "it",
    "make",
    "of",
    "on",
    "one",
    "produce",
    "project",
    "requested",
    "self",
    "that",
    "the",
    "this",
    "to",
    "using",
    "with",
    "write",
}


@dataclass
class CapabilityRequirement:
    name: str
    importance: float
    reasons: list[str] = field(default_factory=list)
    query: str = ""
    selected_ids: list[str] = field(default_factory=list)
    best_score: float = 0.0
    covered: bool = False


@dataclass
class SemanticPlan:
    request: str
    concepts: list[str]
    capabilities: list[CapabilityRequirement]
    target_language: str | None = None
    target_artifact: str | None = None

    @property
    def required_names(self) -> list[str]:
        return [item.name for item in self.capabilities]

    @property
    def coverage(self) -> float:
        total = sum(item.importance for item in self.capabilities)
        if total <= 0:
            return 1.0
        covered = sum(
            item.importance
            for item in self.capabilities
            if item.covered
        )
        return covered / total


@dataclass
class ChunkMatch:
    chunk_id: str
    score: float
    capability: str
    language: str
    path: str
    placement: str
    source: str


def normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9_+#.-]+", normalize(text))
    return [
        word
        for word in words
        if len(word) >= 2 and word not in STOPWORDS
    ]


def extract_concepts(request: str) -> list[str]:
    normalized = normalize(request)
    concepts = set(tokenize(normalized))

    phrase_candidates = {
        "web app",
        "web page",
        "missing letter",
        "missing sentence",
        "health endpoint",
        "task manager",
        "local storage",
        "real time",
        "play again",
        "user input",
    }

    for phrase in phrase_candidates:
        if phrase in normalized:
            concepts.add(phrase)

    return sorted(concepts)


def infer_target(request: str) -> tuple[str | None, str | None]:
    text = normalize(request)

    if any(
        term in text
        for term in {
            "html",
            "website",
            "webpage",
            "web page",
            "web app",
            "browser",
            "game",
            "frontend",
            "dashboard",
        }
    ):
        return "javascript", "browser_application"

    if any(
        term in text
        for term in {
            "fastapi",
            "flask",
            "python",
            ".py",
            "pytest",
        }
    ):
        return "python", "python_application"

    if any(
        term in text
        for term in {
            "express",
            "node",
            "javascript",
            ".js",
        }
    ):
        return "javascript", "javascript_application"

    # SOPHYANE_GENERIC_OPERATIONAL_TARGET_V1
    #
    # Infer an executable software target from strong operational/tool
    # construction evidence even when the user does not name a language.
    #
    # Keep informational daemon/process questions untyped.
    constructive = any(
        marker in text
        for marker in (
            "build ",
            "create ",
            "develop ",
            "generate ",
            "implement ",
            "produce ",
            "provide ",
            "write ",
            "construct ",
        )
    )

    operational_software = any(
        cue in text
        for cue in (
            "terminal agent",
            "terminal-access agent",
            "daemon monitoring",
            "daemon tool",
            "operations agent",
            "operational agent",
            "shell automation",
            "automation tool",
            "command-line tool",
            "command line tool",
            "process monitoring",
            "background process",
            "corrective shell",
        )
    )

    if constructive and operational_software:
        return "python", "python_application"

    return None, None


def _capability_importance(
    name: str,
    request: str,
    concept_overlap: int,
) -> float:
    text = normalize(request)
    importance = 1.0 + min(concept_overlap * 0.25, 1.0)

    if name == "document_shell":
        importance += 0.5

    if name in {
        "user_input",
        "application_state",
        "rules_and_validation",
    } and any(
        term in text
        for term in {
            "game",
            "interactive",
            "quiz",
            "playable",
            "form",
        }
    ):
        importance += 1.0

    if name in {
        "rendering",
        "time_loop",
    } and any(
        term in text
        for term in {
            "game",
            "animation",
            "simulation",
            "playable",
            "canvas",
        }
    ):
        importance += 0.8

    if name == "http_endpoint" and any(
        term in text
        for term in {
            "api",
            "endpoint",
            "fastapi",
            "flask",
            "express",
            "health",
        }
    ):
        importance += 1.2

    return importance


def build_semantic_plan(request: str) -> SemanticPlan:
    concepts = extract_concepts(request)
    concept_set = set(concepts)
    text = normalize(request)
    target_language, target_artifact = infer_target(request)

    requirements: list[CapabilityRequirement] = []

    for name, definition in CAPABILITY_ONTOLOGY.items():
        ontology_concepts = {
            normalize(value)
            for value in definition["concepts"]
        }

        overlap_terms = {
            term
            for term in ontology_concepts
            if term in text or term in concept_set
        }

        if not overlap_terms:
            continue

        importance = _capability_importance(
            name,
            request,
            len(overlap_terms),
        )

        query_terms = sorted(
            set(concepts)
            | ontology_concepts
            | {
                signal.strip("<>{}():; ")
                for signal in definition["signals"]
            }
        )

        requirements.append(
            CapabilityRequirement(
                name=name,
                importance=importance,
                reasons=sorted(overlap_terms),
                query=" ".join(
                    term
                    for term in query_terms
                    if term
                ),
            )
        )

    required_names = {item.name for item in requirements}

    # Generic architectural dependencies.
    if target_artifact == "browser_application":
        dependency_names = {
            "document_shell",
            "presentation",
            "application_state",
            "entry_point",
        }

        if any(
            term in text
            for term in {
                "game",
                "interactive",
                "quiz",
                "playable",
                "form",
            }
        ):
            dependency_names |= {
                "user_input",
                "rules_and_validation",
                "progress_feedback",
                "lifecycle_control",
            }

        if any(
            term in text
            for term in {
                "game",
                "animation",
                "simulation",
                "canvas",
                "drawing",
            }
        ):
            dependency_names |= {
                "rendering",
                "time_loop",
            }

        if any(
            term in text
            for term in {
                "letter",
                "sentence",
                "word",
                "question",
                "task",
                "todo",
                "item",
            }
        ):
            dependency_names.add("data_model")

        for name in dependency_names:
            if name in required_names:
                continue

            definition = CAPABILITY_ONTOLOGY[name]
            requirements.append(
                CapabilityRequirement(
                    name=name,
                    importance=_capability_importance(
                        name,
                        request,
                        0,
                    ),
                    reasons=["architectural dependency"],
                    query=(
                        " ".join(concepts)
                        + " "
                        + " ".join(definition["concepts"])
                        + " "
                        + " ".join(definition["signals"])
                    ),
                )
            )

    if target_artifact in {
        "python_application",
        "javascript_application",
    }:
        for name in {"entry_point", "error_handling"}:
            if name in {item.name for item in requirements}:
                continue

            definition = CAPABILITY_ONTOLOGY[name]
            requirements.append(
                CapabilityRequirement(
                    name=name,
                    importance=1.2,
                    reasons=["architectural dependency"],
                    query=(
                        " ".join(concepts)
                        + " "
                        + " ".join(definition["signals"])
                    ),
                )
            )

    requirements.sort(
        key=lambda item: (-item.importance, item.name)
    )

    return SemanticPlan(
        request=request,
        concepts=concepts,
        capabilities=requirements,
        target_language=target_language,
        target_artifact=target_artifact,
    )


def _chunk_id(chunk: Any) -> str:
    for attribute in ("id", "chunk_id", "uid"):
        value = getattr(chunk, attribute, None)
        if value:
            return str(value)

    return ""


def _chunk_placement(chunk: Any) -> str:
    metadata = getattr(chunk, "meta", None) or {}
    return str(metadata.get("placement") or "")


def _is_test_chunk(chunk: Any) -> bool:
    path = str(getattr(chunk, "path", "") or "").lower()
    name = Path(path.split("::")[0]).name

    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or "/tests/" in path.replace("\\", "/")
        or "::test_" in path
        or "fixture" in name
    )


def _chunk_semantic_score(
    chunk: Any,
    requirement: CapabilityRequirement,
    plan: SemanticPlan,
) -> float:
    definition = CAPABILITY_ONTOLOGY[requirement.name]

    text = normalize(getattr(chunk, "text", "") or "")
    path = normalize(getattr(chunk, "path", "") or "")
    source = normalize(getattr(chunk, "source", "") or "")
    language = normalize(getattr(chunk, "language", "") or "")
    placement = normalize(_chunk_placement(chunk))
    weight = float(getattr(chunk, "weight", 1.0) or 1.0)

    request_terms = set(tokenize(plan.request))
    capability_terms = set(tokenize(requirement.query))
    text_terms = set(tokenize(text[:100_000]))

    request_overlap = len(request_terms & text_terms)
    capability_overlap = len(capability_terms & text_terms)

    request_ratio = (
        request_overlap / max(1, len(request_terms))
    )
    capability_ratio = (
        capability_overlap / max(1, len(capability_terms))
    )

    signal_hits = sum(
        signal.lower() in text
        for signal in definition["signals"]
    )

    score = 0.0
    score += request_ratio * 2.5
    score += capability_ratio * 3.0
    score += min(signal_hits * 0.45, 3.0)
    score += math.log1p(max(weight, 0.0)) * 0.35

    if language in definition["preferred_languages"]:
        score += 0.8

    if placement in definition["placements"]:
        score += 0.7

    if plan.target_language and language == plan.target_language:
        score += 0.7

    # SOPHYANE_PYTHON_SEMANTIC_EXECUTION_FIT_V1
    #
    # Semantic relevance identifies WHAT code is useful. For a Python
    # application, ranking must also account for whether that retrieved
    # evidence can participate directly in executable composition.
    #
    # This deliberately changes ranking rather than bypassing it:
    # request/capability overlap and ontology signals remain authoritative.
    if (
        plan.target_language == "python"
        and language == "python"
    ):
        raw_source = str(
            getattr(chunk, "text", "")
            or ""
        )

        source_bytes = len(
            raw_source.encode(
                "utf-8",
                errors="replace",
            )
        )

        executable = False

        if (
            raw_source.strip()
            and source_bytes <= 16_000
            and not _is_test_chunk(chunk)
        ):
            try:
                compile(
                    raw_source,
                    f"<semantic-chunk:{_chunk_id(chunk)}>",
                    "exec",
                )
                executable = True
            except (
                SyntaxError,
                ValueError,
                TypeError,
            ):
                executable = False

        if executable:
            # Executable components that already fit the downstream Python
            # assembler are substantially more useful than equally relevant
            # whole repositories/modules that assembly must later discard.
            score += 2.4

            if (
                placement == "function"
                or "::" in str(
                    getattr(chunk, "path", "")
                    or ""
                )
            ):
                score += 0.8

            if source_bytes <= 4_000:
                score += 0.5

        elif source_bytes > 16_000:
            # Oversized evidence remains retrievable, but should not dominate
            # executable alternatives for artifact construction.
            score -= min(
                3.5,
                1.5
                + (
                    source_bytes - 16_000
                )
                / 50_000,
            )

        if (
            str(
                getattr(chunk, "path", "")
                or ""
            ).startswith("compound::")
            or "/* RICH CHUNK:" in raw_source
        ):
            # Rich bundles are excellent retrieval evidence but are not
            # executable Python components themselves.
            score -= 1.5

    if requirement.name in path:
        score += 0.5

    # Prefer implementation chunks over tests and framework trivia.
    if _is_test_chunk(chunk):
        score -= 2.2

    if any(
        marker in path
        for marker in {
            "prompt_builder",
            "validationerror",
            "test_response",
            "test_callable",
            "test_platform",
        }
    ):
        score -= 1.4

    if source.startswith("merge") and signal_hits:
        score += 0.3

    if len(text) < 30:
        score -= 0.8

    return score


def retrieve_for_capability(
    store: Any,
    plan: SemanticPlan,
    requirement: CapabilityRequirement,
    *,
    limit: int = 6,
    minimum_score: float = 0.75,
) -> list[ChunkMatch]:
    matches: list[ChunkMatch] = []

    for chunk in store.chunks.values():
        score = _chunk_semantic_score(
            chunk,
            requirement,
            plan,
        )

        if score < minimum_score:
            continue

        matches.append(
            ChunkMatch(
                chunk_id=_chunk_id(chunk),
                score=score,
                capability=requirement.name,
                language=str(
                    getattr(chunk, "language", "") or ""
                ),
                path=str(
                    getattr(chunk, "path", "") or ""
                ),
                placement=_chunk_placement(chunk),
                source=str(
                    getattr(chunk, "source", "") or ""
                ),
            )
        )

    matches.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    # Diversity selection: avoid filling every capability with chunks from
    # the same source/path family.
    selected: list[ChunkMatch] = []
    seen_paths: set[str] = set()
    seen_sources: dict[str, int] = {}

    for match in matches:
        path_family = match.path.split("::")[0]
        source_count = seen_sources.get(match.source, 0)

        if path_family in seen_paths:
            continue

        if source_count >= 2:
            continue

        selected.append(match)
        seen_paths.add(path_family)
        seen_sources[match.source] = source_count + 1

        if len(selected) >= limit:
            break

    requirement.selected_ids = [
        match.chunk_id
        for match in selected
        if match.chunk_id
    ]

    requirement.best_score = (
        selected[0].score
        if selected
        else 0.0
    )

    requirement.covered = bool(
        selected
        and requirement.best_score >= minimum_score
    )

    return selected


def retrieve_semantic_plan(
    store: Any,
    request: str,
    *,
    per_capability: int = 6,
) -> tuple[SemanticPlan, dict[str, list[ChunkMatch]]]:
    plan = build_semantic_plan(request)
    matches: dict[str, list[ChunkMatch]] = {}

    for requirement in plan.capabilities:
        matches[requirement.name] = retrieve_for_capability(
            store,
            plan,
            requirement,
            limit=per_capability,
        )

    return plan, matches


def capability_contract(
    plan: SemanticPlan,
    matches: dict[str, list[ChunkMatch]],
) -> str:
    lines = [
        "SLI semantic capability contract:",
        f"- Target artifact: {plan.target_artifact or 'general code'}",
        f"- Target language: {plan.target_language or 'infer from request'}",
        f"- Concepts: {', '.join(plan.concepts) or 'none'}",
        "- Required capabilities:",
    ]

    for requirement in plan.capabilities:
        selected = matches.get(requirement.name, [])
        ids = [
            match.chunk_id
            for match in selected[:4]
            if match.chunk_id
        ]

        lines.append(
            "  - "
            + requirement.name
            + f" [importance={requirement.importance:.2f}; "
            + f"best={requirement.best_score:.2f}; "
            + f"covered={requirement.covered}]"
        )

        lines.append(
            "    evidence chunks: "
            + (
                ", ".join(ids)
                if ids
                else "none"
            )
        )

        definition = CAPABILITY_ONTOLOGY[requirement.name]
        lines.append(
            "    expected signals: "
            + ", ".join(
                sorted(definition["signals"])[:10]
            )
        )

    lines.extend(
        [
            "- Assemble only implementation chunks relevant to these "
            "capabilities.",
            "- Exclude tests, fixtures, prompt builders and unrelated "
            "framework internals unless explicitly requested.",
            "- Every high-importance capability must be represented in "
            "the resulting artifact.",
            "- Produce complete runnable files, not fragments or "
            "placeholders.",
        ]
    )

    return "\n".join(lines)


def enrich_with_semantics(
    request: str,
    store: Any,
) -> tuple[str, SemanticPlan, dict[str, list[ChunkMatch]]]:
    plan, matches = retrieve_semantic_plan(
        store,
        request,
    )

    contract = capability_contract(
        plan,
        matches,
    )

    semantic_request = (
        str(request).strip()
        + "\n\n"
        + contract
    )

    return semantic_request, plan, matches


def artifact_capability_coverage(
    plan: SemanticPlan,
    files: Iterable[Path],
) -> tuple[float, dict[str, bool], list[str]]:
    combined_parts: list[str] = []

    for path in files:
        try:
            if path.stat().st_size > 1_500_000:
                continue

            combined_parts.append(
                path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).lower()
            )
        except Exception:
            continue

    combined = "\n".join(combined_parts)
    coverage_map: dict[str, bool] = {}
    missing: list[str] = []

    total_importance = sum(
        requirement.importance
        for requirement in plan.capabilities
    )

    covered_importance = 0.0

    for requirement in plan.capabilities:
        definition = CAPABILITY_ONTOLOGY[requirement.name]

        signal_count = sum(
            signal.lower() in combined
            for signal in definition["signals"]
        )

        minimum_signals = 1

        if requirement.name in {
            "user_input",
            "application_state",
            "rules_and_validation",
        }:
            minimum_signals = 2

        covered = signal_count >= minimum_signals
        coverage_map[requirement.name] = covered

        if covered:
            covered_importance += requirement.importance
        else:
            missing.append(requirement.name)

    ratio = (
        covered_importance / total_importance
        if total_importance
        else 1.0
    )

    return ratio, coverage_map, missing


def semantic_diagnostic(
    store: Any,
    request: str,
) -> str:
    plan, matches = retrieve_semantic_plan(
        store,
        request,
    )

    lines = [
        f"Request: {request}",
        f"Target: {plan.target_artifact}",
        f"Language: {plan.target_language}",
        f"Concepts: {', '.join(plan.concepts)}",
        "Capabilities:",
    ]

    for requirement in plan.capabilities:
        lines.append(
            f"  {requirement.name}: "
            f"importance={requirement.importance:.2f} "
            f"covered={requirement.covered} "
            f"best={requirement.best_score:.3f}"
        )

        for match in matches.get(requirement.name, [])[:3]:
            lines.append(
                f"    score={match.score:.3f} "
                f"lang={match.language} "
                f"placement={match.placement} "
                f"path={match.path[:100]}"
            )

    return "\n".join(lines)


__all__ = [
    "CAPABILITY_ONTOLOGY",
    "CapabilityRequirement",
    "ChunkMatch",
    "SemanticPlan",
    "artifact_capability_coverage",
    "build_semantic_plan",
    "capability_contract",
    "enrich_with_semantics",
    "extract_concepts",
    "retrieve_for_capability",
    "retrieve_semantic_plan",
    "semantic_diagnostic",
]

# =====================================================================
# STRICT EXECUTION-DOMAIN COMPATIBILITY — installed automatically
# =====================================================================

_BROWSER_LANGUAGES = {
    "html",
    "css",
    "javascript",
    "typescript",
    "jsx",
    "tsx",
}

_BROWSER_CAPABILITY_LANGUAGES = {
    "document_shell": {"html"},
    "presentation": {"html", "css", "javascript", "typescript"},
    "application_state": {"javascript", "typescript"},
    "user_input": {"html", "javascript", "typescript"},
    "rendering": {"html", "javascript", "typescript"},
    "time_loop": {"javascript", "typescript"},
    "rules_and_validation": {"javascript", "typescript"},
    "progress_feedback": {"html", "javascript", "typescript"},
    "lifecycle_control": {"javascript", "typescript"},
    "data_model": {"javascript", "typescript"},
    "entry_point": {"html", "javascript", "typescript"},
    "persistence": {"javascript", "typescript"},
}

_PYTHON_CAPABILITY_LANGUAGES = {
    "http_endpoint": {"python"},
    "entry_point": {"python"},
    "error_handling": {"python"},
    "rules_and_validation": {"python"},
    "data_model": {"python"},
    "persistence": {"python"},
}

_STRICT_SIGNALS = {
    "document_shell": (
        "<!doctype",
        "<html",
        "<body",
    ),
    "presentation": (
        "<style",
        "display:",
        "grid",
        "flex",
        "class=",
    ),
    "application_state": (
        "let ",
        "const ",
        "state",
        "score",
        "current",
    ),
    "user_input": (
        "addeventlistener",
        "onclick",
        "onkeydown",
        "keydown",
        "keyup",
        "pointerdown",
        "touchstart",
        "<input",
        "<button",
    ),
    "rendering": (
        "<canvas",
        "getcontext",
        "fillrect",
        "drawimage",
        "innerhtml",
        "textcontent",
        "appendchild",
        "render",
        "draw",
    ),
    "time_loop": (
        "requestanimationframe",
        "setinterval",
        "settimeout",
        "animate",
        "tick",
        "gameLoop".lower(),
    ),
    "rules_and_validation": (
        "if ",
        "correct",
        "incorrect",
        "answer",
        "validate",
        "collision",
        "match",
        "check",
    ),
    "progress_feedback": (
        "score",
        "progress",
        "feedback",
        "status",
        "message",
        "textcontent",
    ),
    "lifecycle_control": (
        "restart",
        "reset",
        "initialize",
        "init(",
        "start",
        "next",
    ),
    "data_model": (
        "const ",
        "let ",
        "array",
        "items",
        "data",
        "questions",
        "sentences",
        "words",
        "json",
    ),
    "entry_point": (
        "domcontentloaded",
        "window.onload",
        "<script",
        "__main__",
        "main(",
        "initialize",
        "init(",
    ),
    "http_endpoint": (
        "@app.get",
        "@app.post",
        "fastapi(",
        "apirouter(",
        "app.get(",
        "app.post(",
        "jsonresponse",
    ),
    "error_handling": (
        "try:",
        "except ",
        "raise ",
    ),
}

_DISALLOWED_PATH_PARTS = {
    "/tests/",
    "\\tests\\",
    "::test_",
    "test_",
    ".test.js",
    "fixture",
    "prompt_builder",
    "validationerror",
}

_FRAMEWORK_INTERNAL_PATHS = {
    "/fastapi/fastapi/applications.py",
    "/fastapi/fastapi/routing.py",
    "/fastapi/fastapi/params.py",
    "/fastapi/fastapi/dependencies/",
    "/flask/src/flask/",
    "/express/lib/",
    "/starlette/starlette/",
}


def _strict_normalize_language(value) -> str:
    language = str(value or "").strip().lower()

    aliases = {
        "js": "javascript",
        "ts": "typescript",
        "py": "python",
        "htm": "html",
    }

    return aliases.get(language, language)


def _strict_chunk_text(chunk) -> str:
    return str(getattr(chunk, "text", "") or "").lower()


def _strict_chunk_path(chunk) -> str:
    return str(getattr(chunk, "path", "") or "").lower()


def _strict_is_disallowed_chunk(chunk) -> bool:
    path = _strict_chunk_path(chunk)
    name = Path(path.split("::")[0]).name.lower()

    if (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
    ):
        return True

    return any(part in path for part in _DISALLOWED_PATH_PARTS)


def _strict_is_framework_internal(chunk) -> bool:
    path = _strict_chunk_path(chunk).replace("\\", "/")
    return any(part in path for part in _FRAMEWORK_INTERNAL_PATHS)


def _strict_allowed_languages(plan, capability: str) -> set[str] | None:
    if plan.target_artifact == "browser_application":
        return _BROWSER_CAPABILITY_LANGUAGES.get(
            capability,
            _BROWSER_LANGUAGES,
        )

    if plan.target_language == "python":
        return _PYTHON_CAPABILITY_LANGUAGES.get(
            capability,
            {"python"},
        )

    if plan.target_language:
        return {str(plan.target_language).lower()}

    return None


# SOPHYANE_STRICT_SIGNAL_BOUNDARIES_V3
def _strict_signal_present(
    text: str,
    signal: str,
) -> bool:
    """Match one semantic signal without identifier-substring collisions.

    Signals may intentionally contain syntax such as ``poll(``,
    ``timeout=``, ``subprocess.run`` or ``/proc/``.  Boundary checks
    therefore apply only to identifier-like edges of the signal rather
    than tokenizing the entire source language.
    """
    import re

    haystack = str(text or "")
    needle = str(signal or "")

    if not needle:
        return False

    escaped = re.escape(
        needle
    )

    left_boundary = (
        r"(?<![A-Za-z0-9_])"
        if (
            needle[0].isalnum()
            or needle[0] == "_"
        )
        else ""
    )

    right_boundary = (
        r"(?![A-Za-z0-9_])"
        if (
            needle[-1].isalnum()
            or needle[-1] == "_"
        )
        else ""
    )

    return bool(
        re.search(
            left_boundary
            + escaped
            + right_boundary,
            haystack,
            flags=re.IGNORECASE,
        )
    )


def _strict_signal_count(chunk, capability: str) -> int:
    text = _strict_chunk_text(chunk)
    signals = _STRICT_SIGNALS.get(capability)

    if not signals:
        definition = CAPABILITY_ONTOLOGY.get(capability, {})
        signals = tuple(definition.get("signals", ()))

    return sum(
        _strict_signal_present(
            text,
            str(signal),
        )
        for signal in signals
    )


def _strict_minimum_signals(capability: str) -> int:
    if capability in {
        "user_input",
        "application_state",
        "rules_and_validation",
    }:
        return 2

    return 1


# SOPHYANE_DISCRIMINATIVE_CAPABILITY_ADMISSION_V1
#
# Ontology signals are useful ranking evidence, but several signals are
# intentionally broad vocabulary ("process", "log", "error", "if ", ...).
# A broad token must not, by itself, prove that a chunk IMPLEMENTS the
# requested capability.
#
# Strong signals describe an operation or mechanism characteristic of the
# capability. Weak signals remain useful as supporting evidence and inside
# _chunk_semantic_score(), but cannot independently establish admission.
_STRICT_STRONG_SIGNALS = {
    "log_diagnostics": {
        "read_text",
        "tail",
        "journalctl",
        "traceback",
    },
    "network_port_diagnostics": {
        "eaddrinuse",
        "address already in use",
        "socket",
        "netstat",
        "lsof",
        "bind(",
        "listen(",
    },
    "process_supervision": {
        "terminate(",
        "poll(",
        "psutil",
        "pid",
        "wait(",
        "kill(",
        "subprocess",
        "popen",
    },
    "safe_command_execution": {
        "timeout=",
        "shell=false",
        "shlex",
        "subprocess.popen",
        "allowlist",
        "subprocess.run",
        "check=true",
        "denylist",
    },
    "resource_diagnostics": {
        "rss",
        "psutil",
        "getrusage",
        "/proc/",
        "oom",
    },
    "entry_point": {
        "__main__",
        "domcontentloaded",
        "window.onload",
        "main(",
    },
    "error_handling": {
        "except ",
        "try:",
        "catch",
        "raise ",
        "throw",
    },
    "rules_and_validation": {
        "validate",
        "incorrect",
        "collision",
    },
}


def _strict_signal_hits(
    chunk,
    capability: str,
) -> set[str]:
    """Return normalized ontology signals present in the chunk."""
    text = _strict_chunk_text(chunk)
    signals = _STRICT_SIGNALS.get(capability)

    if not signals:
        definition = CAPABILITY_ONTOLOGY.get(capability, {})
        signals = tuple(definition.get("signals", ()))

    return {
        str(signal).lower()
        for signal in signals
        if _strict_signal_present(
            text,
            str(signal),
        )
    }


def _strict_strong_signal_count(
    chunk,
    capability: str,
) -> int:
    hits = _strict_signal_hits(chunk, capability)
    strong = {
        str(signal).lower()
        for signal in _STRICT_STRONG_SIGNALS.get(
            capability,
            set(),
        )
    }
    return len(hits & strong)



# SOPHYANE_BEHAVIORAL_CAPABILITY_ADMISSION_V2
#
# A behavioral capability is established by complementary evidence roles,
# not by repeated vocabulary from one role.  For example, merely spawning
# a process does not establish supervision; lifecycle observation/control
# must also be present.
#
# Each tuple is one evidence role.  Every role must have at least one hit.
_STRICT_BEHAVIORAL_EVIDENCE_GROUPS = {
    "process_supervision": (
        {
            "popen",
            "subprocess",
            "pid",
            "psutil",
        },
        {
            "poll(",
            "wait(",
            "terminate(",
            "kill(",
        },
    ),
    "safe_command_execution": (
        {
            "subprocess.run",
            "subprocess.popen",
        },
        {
            "shell=false",
            "timeout=",
            "allowlist",
            "denylist",
            "shlex",
        },
    ),
    "log_diagnostics": (
        {
            "journalctl",
            "read_text",
            "tail",
        },
        {
            "log",
            "stderr",
            "stdout",
            "traceback",
        },
    ),
}


def _strict_behavioral_group_hits(
    chunk,
    capability: str,
) -> tuple[set[str], ...]:
    """Return matching signals for each required behavioral evidence role."""
    groups = _STRICT_BEHAVIORAL_EVIDENCE_GROUPS.get(
        capability,
        (),
    )

    if not groups:
        return ()

    text = _strict_chunk_text(chunk)

    return tuple(
        {
            str(signal).lower()
            for signal in group
            if _strict_signal_present(
                text,
                str(signal),
            )
        }
        for group in groups
    )


def _strict_has_behavioral_evidence(
    chunk,
    capability: str,
) -> bool:
    """Require evidence from every role defined for a behavioral capability."""
    groups = _STRICT_BEHAVIORAL_EVIDENCE_GROUPS.get(
        capability,
    )

    if not groups:
        return True

    hits = _strict_behavioral_group_hits(
        chunk,
        capability,
    )

    return bool(hits) and all(hits)


def _strict_has_discriminative_evidence(
    chunk,
    capability: str,
) -> bool:
    """Whether evidence is specific enough to establish the capability."""
    signal_count = _strict_signal_count(chunk, capability)

    if signal_count < _strict_minimum_signals(capability):
        return False

    strong_signals = _STRICT_STRONG_SIGNALS.get(capability)

    # Capabilities without a specialized evidence policy retain the existing
    # ontology contract.
    if not strong_signals:
        return True

    strong_count = _strict_strong_signal_count(
        chunk,
        capability,
    )

    if strong_count >= 1:
        return _strict_has_behavioral_evidence(
            chunk,
            capability,
        )

    # Multiple broad signals may support ranking but are not sufficient to
    # prove implementation of capabilities for which we have discriminative
    # operational evidence.
    return False


# Preserve the original planner once.
if "_SLI_ORIGINAL_BUILD_SEMANTIC_PLAN" not in globals():
    _SLI_ORIGINAL_BUILD_SEMANTIC_PLAN = build_semantic_plan


def build_semantic_plan(request: str) -> SemanticPlan:
    """Build a plan and remove capabilities outside the target domain."""
    plan = _SLI_ORIGINAL_BUILD_SEMANTIC_PLAN(request)

    if plan.target_artifact == "browser_application":
        forbidden = {
            "http_endpoint",
            "web_server",
            "error_handling",
        }

        plan.capabilities = [
            requirement
            for requirement in plan.capabilities
            if requirement.name not in forbidden
        ]

    elif plan.target_language == "python":
        # A Python API request must not acquire browser-document duties.
        forbidden = {
            "document_shell",
            "presentation",
            "rendering",
            "user_input",
            "time_loop",
            "progress_feedback",
            "lifecycle_control",
        }

        plan.capabilities = [
            requirement
            for requirement in plan.capabilities
            if requirement.name not in forbidden
        ]

    return plan


def retrieve_for_capability(
    store,
    plan: SemanticPlan,
    requirement: CapabilityRequirement,
    *,
    limit: int = 6,
    minimum_score: float = 0.75,
) -> list[ChunkMatch]:
    """Retrieve only chunks compatible with target language and role."""
    allowed_languages = _strict_allowed_languages(
        plan,
        requirement.name,
    )

    ranked: list[tuple[object, float]] = []

    for chunk in store.chunks.values():
        if _strict_is_disallowed_chunk(chunk):
            continue

        language = _strict_normalize_language(
            getattr(chunk, "language", "")
        )

        if allowed_languages and language not in allowed_languages:
            continue

        signal_count = _strict_signal_count(
            chunk,
            requirement.name,
        )

        if not _strict_has_discriminative_evidence(
            chunk,
            requirement.name,
        ):
            continue

        # API assembly must use endpoint implementations, not framework
        # implementation internals.
        if (
            plan.target_language == "python"
            and requirement.name == "http_endpoint"
            and _strict_is_framework_internal(chunk)
        ):
            continue

        score = _chunk_semantic_score(
            chunk,
            requirement,
            plan,
        )

        # Strict admission already established capability compatibility.
        # _chunk_semantic_score() already rewards ontology signal hits, so do
        # not reward the same raw signal count a second time here.
        score += 1.0

        strong_signal_count = _strict_strong_signal_count(
            chunk,
            requirement.name,
        )
        if strong_signal_count:
            score += min(
                0.25 * strong_signal_count,
                0.75,
            )

        placement = _chunk_placement(chunk).lower()
        definition = CAPABILITY_ONTOLOGY.get(
            requirement.name,
            {},
        )

        if placement in definition.get("placements", set()):
            score += 0.75

        # Penalize huge compiled vendor bundles: useful as acquisition
        # sources, poor as reusable composition units.
        text_size = len(str(getattr(chunk, "text", "") or ""))

        if text_size > 100_000:
            score -= 2.5
        elif text_size > 40_000:
            score -= 1.2

        if score >= minimum_score:
            ranked.append((chunk, score))

    ranked.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    selected: list[ChunkMatch] = []
    seen_paths: set[str] = set()
    seen_sources: dict[str, int] = {}

    for chunk, score in ranked:
        path = str(getattr(chunk, "path", "") or "")
        path_family = path.split("::")[0]
        source = str(getattr(chunk, "source", "") or "")

        if path_family in seen_paths:
            continue

        if seen_sources.get(source, 0) >= 2:
            continue

        chunk_id = _chunk_id(chunk)

        if not chunk_id:
            continue

        selected.append(
            ChunkMatch(
                chunk_id=chunk_id,
                score=score,
                capability=requirement.name,
                language=str(
                    getattr(chunk, "language", "") or ""
                ),
                path=path,
                placement=_chunk_placement(chunk),
                source=source,
            )
        )

        seen_paths.add(path_family)
        seen_sources[source] = seen_sources.get(source, 0) + 1

        if len(selected) >= limit:
            break

    requirement.selected_ids = [
        match.chunk_id for match in selected
    ]
    requirement.best_score = (
        selected[0].score if selected else 0.0
    )
    requirement.covered = bool(selected)

    return selected


def retrieve_semantic_plan(
    store,
    request: str,
    *,
    per_capability: int = 6,
):
    """Retrieve a plan whose coverage means compatible evidence exists."""
    plan = build_semantic_plan(request)
    matches: dict[str, list[ChunkMatch]] = {}

    for requirement in plan.capabilities:
        selected = retrieve_for_capability(
            store,
            plan,
            requirement,
            limit=per_capability,
        )
        matches[requirement.name] = selected

    return plan, matches


# FINAL STRICT SEMANTIC EVIDENCE BOUNDARY
# This definition intentionally overrides earlier retrieval functions.

_FINAL_BROWSER_ALLOWED = {
    "document_shell": {"html"},
    "presentation": {"html", "css", "javascript", "typescript"},
    "application_state": {"javascript", "typescript"},
    "user_input": {"html", "javascript", "typescript"},
    "rendering": {"html", "javascript", "typescript"},
    "time_loop": {"javascript", "typescript"},
    "rules_and_validation": {"javascript", "typescript"},
    "progress_feedback": {"html", "javascript", "typescript"},
    "lifecycle_control": {"javascript", "typescript"},
    "data_model": {"javascript", "typescript"},
    "entry_point": {"html", "javascript", "typescript"},
    "persistence": {"javascript", "typescript"},
}

_FINAL_SIGNALS = {
    "document_shell": (
        "<html",
        "<body",
    ),
    "presentation": (
        "<style",
        "display:",
        "class=",
    ),
    "application_state": (
        "let ",
        "const ",
        "state",
        "score",
        "current",
    ),
    "user_input": (
        "addeventlistener",
        "onclick",
        "onkeydown",
        "keydown",
        "keyup",
        "pointerdown",
        "touchstart",
        "<input",
        "<button",
    ),
    "rendering": (
        "<canvas",
        "getcontext",
        "textcontent",
        "innerhtml",
        "appendchild",
        "render",
        "draw",
    ),
    "time_loop": (
        "requestanimationframe",
        "setinterval",
        "settimeout",
        "animate",
        "tick",
        "loop",
    ),
    "rules_and_validation": (
        "if ",
        "answer",
        "correct",
        "incorrect",
        "validate",
        "check",
        "match",
        "collision",
    ),
    "progress_feedback": (
        "score",
        "progress",
        "feedback",
        "status",
        "message",
        "textcontent",
    ),
    "lifecycle_control": (
        "restart",
        "reset",
        "initialize",
        "start",
        "next",
    ),
    "data_model": (
        "const ",
        "let ",
        "array",
        "items",
        "questions",
        "sentences",
        "words",
        "data",
    ),
    "entry_point": (
        "<script",
        "domcontentloaded",
        "window.onload",
        "initialize",
        "init(",
    ),
    "http_endpoint": (
        "@app.get",
        "@app.post",
        "fastapi(",
        "apirouter(",
        "app.get(",
        "app.post(",
    ),
    "error_handling": (
        "try:",
        "except ",
        "raise ",
    ),
}


def _final_language(value) -> str:
    language = str(value or "").strip().lower()

    return {
        "js": "javascript",
        "ts": "typescript",
        "py": "python",
        "htm": "html",
    }.get(language, language)


def _final_disallowed_path(path: str) -> bool:
    value = str(path or "").lower().replace("\\", "/")
    filename = Path(value.split("::")[0]).name

    return (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith(".test.js")
        or "/tests/" in value
        or "::test_" in value
        or "fixture" in filename
        or "prompt_builder" in value
        or "validationerror" in value
    )


def _final_framework_internal(path: str) -> bool:
    value = str(path or "").lower().replace("\\", "/")

    internals = (
        "/fastapi/fastapi/applications.py",
        "/fastapi/fastapi/routing.py",
        "/fastapi/fastapi/params.py",
        "/fastapi/fastapi/dependencies/",
        "/starlette/starlette/",
        "/flask/src/flask/",
        "/express/lib/",
    )

    return any(item in value for item in internals)


def _final_minimum_signals(capability: str) -> int:
    if capability in {
        "user_input",
        "application_state",
        "rules_and_validation",
    }:
        return 2

    return 1


def _final_compatible(
    chunk,
    plan,
    capability: str,
) -> bool:
    language = _final_language(
        getattr(chunk, "language", "")
    )
    path = str(getattr(chunk, "path", "") or "")
    text = str(getattr(chunk, "text", "") or "").lower()

    if _final_disallowed_path(path):
        return False

    if plan.target_artifact == "browser_application":
        allowed = _FINAL_BROWSER_ALLOWED.get(
            capability,
            {"html", "css", "javascript", "typescript"},
        )

        if language not in allowed:
            return False

    elif plan.target_language == "python":
        if language != "python":
            return False

        if (
            capability == "http_endpoint"
            and _final_framework_internal(path)
        ):
            return False

    # SOPHYANE_FINAL_ONTOLOGY_SIGNAL_AUTHORITY_V2
    #
    # Strict final signals are capability-specific overrides, not a
    # closed whitelist. New/general semantic capabilities inherit their
    # executable evidence signals from the canonical ontology.
    signals = _FINAL_SIGNALS.get(
        capability
    )

    if signals is None:
        definition = CAPABILITY_ONTOLOGY.get(
            capability,
            {},
        )

        signals = tuple(
            str(signal).lower()
            for signal in definition.get(
                "signals",
                (),
            )
            if str(signal).strip()
        )

    count = sum(
        signal in text
        for signal in signals
    )

    return count >= _final_minimum_signals(
        capability
    )


if "_FINAL_ORIGINAL_BUILD_PLAN" not in globals():
    _FINAL_ORIGINAL_BUILD_PLAN = build_semantic_plan


def build_semantic_plan(request: str) -> SemanticPlan:
    plan = _FINAL_ORIGINAL_BUILD_PLAN(request)

    if plan.target_artifact == "browser_application":
        forbidden = {
            "http_endpoint",
            "web_server",
            "error_handling",
        }

        plan.capabilities = [
            requirement
            for requirement in plan.capabilities
            if requirement.name not in forbidden
        ]

    elif plan.target_language == "python":
        forbidden = {
            "document_shell",
            "presentation",
            "rendering",
            "user_input",
            "time_loop",
            "progress_feedback",
            "lifecycle_control",
        }

        plan.capabilities = [
            requirement
            for requirement in plan.capabilities
            if requirement.name not in forbidden
        ]

    return plan


def retrieve_semantic_plan(
    store,
    request: str,
    *,
    per_capability: int = 6,
):
    """Retrieve semantic evidence through the canonical capability boundary."""
    plan = build_semantic_plan(request)
    matches: dict[str, list[ChunkMatch]] = {}

    for requirement in plan.capabilities:
        selected = retrieve_for_capability(
            store,
            plan,
            requirement,
            limit=per_capability,
        )
        matches[requirement.name] = selected

    return plan, matches
