"""Generic task understanding and execution planning for Sophyane.

This module converts a natural-language request into a reusable task contract.
It contains no product-specific handlers such as make_snake_game().
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


WORKER_ALIASES = {
    "nifdu": "nifdu",
    "neuron": "neuron",
    "gemini": "gemini",
    "local model": "local_gguf",
    "local llm": "local_gguf",
    "sophyane": "sophyane",
}


ACTION_PATTERNS = (
    ("create", r"\b(?:create|make|build|generate|develop|write)\b"),
    ("modify", r"\b(?:modify|edit|update|improve|change|refactor)\b"),
    ("fix", r"\b(?:fix|repair|debug|resolve|correct)\b"),
    ("inspect", r"\b(?:inspect|check|analyze|review|audit|diagnose)\b"),
    ("run", r"\b(?:run|execute|start|launch)\b"),
    ("open", r"\b(?:open|display|show)\b"),
    ("test", r"\b(?:test|verify|validate|confirm)\b"),
)


ARTIFACT_PATTERNS = (
    # Specific artifact classes must be checked before broad delivery
    # words such as "browser", "application", or "project".
    ("game", r"\b(?:game|snake|chess|tetris|pong|tic tac)\b"),
    ("data_analysis", r"\b(?:analysis|analyze|benchmark|dataset|csv|statistics|chart)\b"),
    ("document", r"\b(?:document|report|article|letter|proposal|pdf)\b"),
    ("script", r"\b(?:script|bash|shell|python script)\b"),
    ("web_application", r"\b(?:website|web app|html|browser|dashboard|landing page)\b"),
    ("software_project", r"\b(?:application|program|software|project|api|service)\b"),
)


@dataclass(frozen=True)
class SuccessCondition:
    condition_id: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class PlannedAction:
    action_id: str
    capability: str
    description: str
    depends_on: tuple[str, ...] = ()
    mutating: bool = False
    timeout_seconds: int = 30
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskContract:
    task_id: str
    original_request: str
    goal: str
    requested_worker: str
    task_kind: str
    primary_action: str
    workspace: str
    requirements: tuple[str, ...]
    success_conditions: tuple[SuccessCondition, ...]
    actions: tuple[PlannedAction, ...]
    max_attempts: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_request(message: str) -> str:
    text = " ".join(str(message or "").strip().split())
    replacements = {
        "sytem": "system",
        "configration": "configuration",
        "noe": "now",
    }

    words: list[str] = []

    for raw in text.split():
        prefix = raw[: len(raw) - len(raw.lstrip("\"'([{"))]
        suffix = raw[len(raw.rstrip("\"'.,?!:;)]}")) :]
        core = raw.strip("\"'.,?!:;()[]{}").casefold()
        corrected = replacements.get(core, core)

        if corrected:
            words.append(prefix + corrected + suffix)

    return " ".join(words).strip()


def detect_worker(text: str) -> str:
    lowered = text.casefold()

    for phrase, worker in WORKER_ALIASES.items():
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return worker

    return "auto"


def detect_primary_action(text: str) -> str:
    lowered = text.casefold()

    for action, pattern in ACTION_PATTERNS:
        if re.search(pattern, lowered, flags=re.I):
            return action

    return "answer"


def detect_task_kind(text: str) -> str:
    lowered = text.casefold()

    for kind, pattern in ARTIFACT_PATTERNS:
        if re.search(pattern, lowered, flags=re.I):
            return kind

    if any(
        word in lowered
        for word in ("file", "folder", "directory", "storage")
    ):
        return "filesystem"

    return "general"


def extract_workspace(text: str, task_kind: str) -> str:
    path_match = re.search(
        r"(?<![\w.-])"
        r"((?:apps|projects|src|docs|tests|output)/"
        r"[A-Za-z0-9._/-]+)",
        text,
    )

    if path_match:
        candidate = path_match.group(1).rstrip(".,;:")
        candidate_path = Path(candidate)

        # The task workspace is a directory. When the user names an entry
        # file such as index.html, use its parent directory as workspace.
        if candidate_path.suffix:
            parent = candidate_path.parent
            return str(parent) if str(parent) != "." else "projects/task"

        return candidate

    slug_source = re.sub(
        r"\b(?:tell|ask|use|nifdu|neuron|sophyane|to|please)\b",
        " ",
        text,
        flags=re.I,
    )
    words = re.findall(r"[a-zA-Z0-9]+", slug_source.casefold())[:6]
    slug = "-".join(words) or "task"

    base = {
        "web_application": "apps",
        "game": "apps",
        "software_project": "apps",
        "document": "output/documents",
        "script": "scripts/generated",
        "data_analysis": "output/analysis",
    }.get(task_kind, "projects")

    return f"{base}/{slug}"


def extract_requirements(text: str, task_kind: str) -> tuple[str, ...]:
    requirements: list[str] = []

    cues = (
        ("mobile responsive", ("mobile", "phone", "responsive", "touch")),
        ("open in browser", ("open", "browser")),
        ("start local HTTP server", ("server", "http")),
        ("include working controls", ("controls", "interaction", "buttons")),
        ("include visible state feedback", ("score", "status", "feedback")),
        ("include restart behavior", ("restart", "reset")),
        ("run validation", ("verify", "validate", "test", "working")),
    )

    lowered = text.casefold()

    for requirement, terms in cues:
        if all(term in lowered for term in terms):
            requirements.append(requirement)
        elif len(terms) > 2 and any(term in lowered for term in terms):
            requirements.append(requirement)

    if task_kind in {"web_application", "game"}:
        defaults = (
            "produce a complete entry page",
            "avoid missing local assets",
            "validate generated markup and scripts",
        )
        requirements.extend(defaults)

    return tuple(dict.fromkeys(requirements))


def success_conditions_for(
    task_kind: str,
    primary_action: str,
    requirements: Iterable[str],
) -> tuple[SuccessCondition, ...]:
    conditions: list[SuccessCondition] = []

    if primary_action in {"create", "modify", "fix"}:
        conditions.append(
            SuccessCondition(
                "artifact_exists",
                "Expected output artifacts exist on disk.",
            )
        )

    if task_kind in {"web_application", "game"}:
        conditions.extend(
            (
                SuccessCondition(
                    "entry_file_exists",
                    "A complete browser entry file exists.",
                ),
                SuccessCondition(
                    "static_validation",
                    "Markup and script validation passes.",
                ),
            )
        )

    requirement_text = " ".join(requirements).casefold()

    if "http" in requirement_text or "browser" in requirement_text:
        conditions.append(
            SuccessCondition(
                "http_success",
                "The local HTTP endpoint returns a successful response.",
            )
        )

    if "browser" in requirement_text:
        conditions.append(
            SuccessCondition(
                "browser_open_attempted",
                "A browser launch is attempted using a native capability.",
            )
        )

    if not conditions:
        conditions.append(
            SuccessCondition(
                "grounded_result",
                "The final answer is supported by tool or runtime evidence.",
            )
        )

    return tuple(conditions)


def actions_for(
    *,
    task_kind: str,
    primary_action: str,
    workspace: str,
    requirements: Iterable[str],
) -> tuple[PlannedAction, ...]:
    actions: list[PlannedAction] = []

    actions.append(
        PlannedAction(
            action_id="inspect",
            capability="workspace.inspect",
            description="Inspect existing workspace and relevant files.",
            mutating=False,
            timeout_seconds=10,
            inputs={"workspace": workspace},
        )
    )

    previous = "inspect"

    if primary_action in {"create", "modify", "fix"}:
        actions.append(
            PlannedAction(
                action_id="produce",
                capability="worker.produce_artifact",
                description="Ask the selected worker to produce or repair artifacts.",
                depends_on=(previous,),
                mutating=True,
                timeout_seconds=45,
                inputs={"workspace": workspace},
            )
        )
        previous = "produce"

    if task_kind in {"web_application", "game"}:
        actions.append(
            PlannedAction(
                action_id="validate",
                capability="artifact.validate_web",
                description="Validate entry file, markup, scripts and local assets.",
                depends_on=(previous,),
                mutating=False,
                timeout_seconds=20,
                inputs={"workspace": workspace},
            )
        )
        previous = "validate"

    requirement_text = " ".join(requirements).casefold()

    if "http" in requirement_text or "browser" in requirement_text:
        actions.append(
            PlannedAction(
                action_id="serve",
                capability="http.start_server",
                description="Start a bounded local HTTP server.",
                depends_on=(previous,),
                mutating=False,
                timeout_seconds=10,
                inputs={"workspace": workspace, "host": "127.0.0.1"},
            )
        )

        actions.append(
            PlannedAction(
                action_id="http_check",
                capability="http.check",
                description="Verify the generated artifact over HTTP.",
                depends_on=("serve",),
                mutating=False,
                timeout_seconds=10,
            )
        )
        previous = "http_check"

    if "browser" in requirement_text:
        actions.append(
            PlannedAction(
                action_id="open_browser",
                capability="browser.open",
                description="Open the verified local URL in the browser.",
                depends_on=(previous,),
                mutating=False,
                timeout_seconds=10,
            )
        )

    return tuple(actions)


def derive_goal(text: str, worker: str) -> str:
    clean = re.sub(
        r"^\s*(?:tell|ask|use)\s+"
        r"(?:nifdu|neuron|sophyane|gemini)\s+to\s+",
        "",
        text,
        flags=re.I,
    ).strip(" .")

    if not clean:
        clean = text.strip(" .")

    worker_prefix = "" if worker == "auto" else f" using {worker}"
    return f"{clean}{worker_prefix}".strip()


def understand_request(message: str) -> TaskContract:
    original = str(message or "").strip()

    if not original:
        raise ValueError("Task request is empty.")

    normalized = normalize_request(original)
    worker = detect_worker(normalized)
    primary_action = detect_primary_action(normalized)
    task_kind = detect_task_kind(normalized)
    workspace = extract_workspace(original, task_kind)
    requirements = extract_requirements(normalized, task_kind)
    conditions = success_conditions_for(
        task_kind,
        primary_action,
        requirements,
    )
    actions = actions_for(
        task_kind=task_kind,
        primary_action=primary_action,
        workspace=workspace,
        requirements=requirements,
    )

    return TaskContract(
        task_id=uuid.uuid4().hex[:12],
        original_request=original,
        goal=derive_goal(original, worker),
        requested_worker=worker,
        task_kind=task_kind,
        primary_action=primary_action,
        workspace=workspace,
        requirements=requirements,
        success_conditions=conditions,
        actions=actions,
    )


def format_contract(contract: TaskContract) -> str:
    lines = [
        f"Task: {contract.task_id}",
        f"Goal: {contract.goal}",
        f"Worker: {contract.requested_worker}",
        f"Kind: {contract.task_kind}",
        f"Action: {contract.primary_action}",
        f"Workspace: {contract.workspace}",
        "",
        "Execution plan:",
    ]

    for index, action in enumerate(contract.actions, start=1):
        dependency = (
            f" after {', '.join(action.depends_on)}"
            if action.depends_on
            else ""
        )
        lines.append(
            f"{index}. {action.capability}{dependency}: "
            f"{action.description}"
        )

    lines.append("")
    lines.append("Success conditions:")

    for condition in contract.success_conditions:
        lines.append(f"- {condition.description}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="sophyane-task",
        description="Inspect Sophyane's generic task understanding.",
    )
    parser.add_argument("request", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    contract = understand_request(" ".join(args.request))

    if args.json:
        print(json.dumps(contract.to_dict(), indent=2))
    else:
        print(format_contract(contract))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
