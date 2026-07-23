"""Instruction-led recursive improvement for editable visual scenes.

This module does not generate raster images. It teaches Sophyane to:

1. extract explicit user requirements;
2. plan bounded scene operations;
3. evaluate requirement coverage;
4. identify unmet requirements;
5. improve the scene recursively;
6. stop on satisfaction, stagnation or a strict iteration limit;
7. preserve a machine-readable improvement audit.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re
from typing import Any, Callable


Operation = dict[str, Any]
Scene = dict[str, Any]


_COLOURS = {
    "dark brown": "#4a2b18",
    "light brown": "#a8754f",
    "brown": "#7a4b2a",
    "black": "#111827",
    "white": "#ffffff",
    "green": "#15803d",
    "blue": "#2563eb",
    "red": "#dc2626",
    "beige": "#e8dcc8",
    "cream": "#f4ead7",
    "gold": "#b68b2e",
}

_KNOWN_PEOPLE = {
    "jinnah": "Muhammad Ali Jinnah",
    "muhammad ali jinnah": "Muhammad Ali Jinnah",
    "quaid e azam": "Muhammad Ali Jinnah",
    "quaid-e-azam": "Muhammad Ali Jinnah",
    "allama iqbal": "Allama Muhammad Iqbal",
    "iqbal": "Allama Muhammad Iqbal",
    "fatima jinnah": "Fatima Jinnah",
}

_CREATION_WORDS = {
    "make",
    "create",
    "design",
    "draw",
    "generate",
    "produce",
    "build",
}

_VISUAL_WORDS = {
    "portrait",
    "poster",
    "illustration",
    "logo",
    "wallpaper",
    "canvas",
    "visual",
    "design",
    "scene",
    "picture",
    "image",
}

_EDIT_WORDS = {
    "change",
    "make",
    "add",
    "remove",
    "move",
    "resize",
    "increase",
    "reduce",
    "larger",
    "bigger",
    "smaller",
    "background",
    "attire",
    "clothes",
    "clothing",
    "pose",
    "sit",
    "stand",
    "chair",
    "left",
    "right",
    "up",
    "down",
}


def normalise_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def is_visual_instruction(request: str) -> bool:
    """Classify visual instructions without depending on one named person."""

    text = normalise_text(request)
    words = set(re.findall(r"[a-z0-9-]+", text))

    return bool(
        words.intersection(_VISUAL_WORDS)
        or words.intersection(_EDIT_WORDS)
        or (
            words.intersection(_CREATION_WORDS)
            and any(name in text for name in _KNOWN_PEOPLE)
        )
    )


@dataclass(frozen=True)
class Requirement:
    key: str
    expected: Any
    target: str = "subject"
    source: str = ""
    weight: float = 1.0


@dataclass
class Evaluation:
    score: float
    satisfied: list[str] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImprovementResult:
    scene: Scene
    operations: list[Operation]
    evaluation: Evaluation
    iterations: int
    stop_reason: str
    audit: list[dict[str, Any]]


def _subject(scene: Scene) -> dict[str, Any]:
    for element in scene.get("elements", []):
        if str(element.get("id")) == "subject":
            return element

    return {}


def _element(scene: Scene, element_id: str) -> dict[str, Any]:
    for element in scene.get("elements", []):
        if str(element.get("id")) == element_id:
            return element

    return {}


def _extract_person(raw: str, text: str) -> str | None:
    for alias, canonical in sorted(
        _KNOWN_PEOPLE.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if alias in text:
            return canonical

    patterns = (
        r"(?:portrait|picture|image|illustration)\s+of\s+"
        r"([A-Za-z][A-Za-z .'-]{1,70})",
        r"(?:make|create|draw|generate|design)\s+"
        r"([A-Za-z][A-Za-z .'-]{1,70}?)\s+"
        r"(?:portrait|picture|image|illustration)",
    )

    stop_words = {
        "a",
        "an",
        "the",
        "editable",
        "realistic",
        "beautiful",
        "professional",
        "full",
        "large",
        "small",
    }

    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)

        if not match:
            continue

        candidate = " ".join(match.group(1).strip(" ,.-").split())
        parts = candidate.split()

        while parts and parts[0].lower() in stop_words:
            parts.pop(0)

        candidate = " ".join(parts[:8]).strip()

        if candidate:
            return candidate

    return None


def extract_requirements(
    request: str,
    scene: Scene,
) -> list[Requirement]:
    """Convert explicit language into independently testable requirements."""

    raw = str(request or "").strip()
    text = normalise_text(raw)
    requirements: list[Requirement] = []

    person = _extract_person(raw, text)

    if person:
        requirements.append(
            Requirement(
                key="person",
                expected=person,
                source="requested portrait subject",
                weight=2.0,
            )
        )

    attire_patterns = (
        (
            (
                "pakistani attire",
                "pakistani clothes",
                "pakistani clothing",
                "sherwani",
            ),
            "traditional Pakistani sherwani",
        ),
        (
            ("formal suit", "business suit"),
            "formal suit",
        ),
        (
            ("casual clothes", "casual attire"),
            "casual attire",
        ),
    )

    for phrases, value in attire_patterns:
        if any(phrase in text for phrase in phrases):
            requirements.append(
                Requirement(
                    key="attire",
                    expected=value,
                    source="requested attire",
                )
            )
            break

    if any(
        phrase in text
        for phrase in (
            "sitting",
            "seated",
            "sit on",
            "sits on",
            "seat him",
            "seat her",
        )
    ):
        requirements.append(
            Requirement(
                key="pose",
                expected="seated",
                source="requested seated pose",
            )
        )
    elif any(
        phrase in text
        for phrase in (
            "standing",
            "stand up",
            "make him stand",
            "make her stand",
        )
    ):
        requirements.append(
            Requirement(
                key="pose",
                expected="standing",
                source="requested standing pose",
            )
        )

    colour_pattern = (
        r"dark brown|light brown|brown|black|white|green|blue|red|"
        r"beige|cream|gold"
    )

    # Accept both:
    #   "change the background to blue"
    #   "with a blue background"
    background_match = re.search(
        rf"(?:background|backdrop)"
        rf"(?:\s+colour|\s+color)?"
        rf"\s*(?:to|is|should be|must be|:)?\s*"
        rf"(?P<after>{colour_pattern})",
        text,
    )

    if background_match is None:
        background_match = re.search(
            rf"(?P<before>{colour_pattern})"
            rf"\s+(?:colour\s+|color\s+)?"
            rf"(?:background|backdrop)",
            text,
        )

    if background_match:
        background_colour = (
            background_match.groupdict().get("after")
            or background_match.groupdict().get("before")
        )

        requirements.append(
            Requirement(
                key="canvas.background",
                target="canvas",
                expected=_COLOURS[background_colour],
                source="requested background colour",
            )
        )

    if "chair" in text:
        chair_colour = "#7a4b2a"

        for name in sorted(_COLOURS, key=len, reverse=True):
            if name in text:
                chair_colour = _COLOURS[name]
                break

        requirements.append(
            Requirement(
                key="element.exists",
                target="chair",
                expected=True,
                source="requested chair",
            )
        )
        requirements.append(
            Requirement(
                key="colour",
                target="chair",
                expected=chair_colour,
                source="requested chair colour",
                weight=0.5,
            )
        )

    movement_requested = "move" in text or "place" in text

    if movement_requested:
        target = "chair" if "chair" in text else "subject"

        if "left" in text:
            requirements.append(
                Requirement(
                    key="position.horizontal",
                    target=target,
                    expected="left",
                    source="requested left placement",
                )
            )
        elif "right" in text:
            requirements.append(
                Requirement(
                    key="position.horizontal",
                    target=target,
                    expected="right",
                    source="requested right placement",
                )
            )

        if "higher" in text or "move up" in text:
            requirements.append(
                Requirement(
                    key="position.vertical",
                    target=target,
                    expected="upper",
                    source="requested upward placement",
                )
            )
        elif "lower" in text or "move down" in text:
            requirements.append(
                Requirement(
                    key="position.vertical",
                    target=target,
                    expected="lower",
                    source="requested downward placement",
                )
            )

    if any(
        phrase in text
        for phrase in (
            "larger",
            "bigger",
            "increase size",
            "make it large",
            "make him large",
            "make her large",
        )
    ):
        target = "chair" if "chair" in text else "subject"
        current = _element(scene, target)
        requirements.append(
            Requirement(
                key="minimum_size",
                target=target,
                expected={
                    "width": round(float(current.get("width", 200)) * 1.15),
                    "height": round(float(current.get("height", 200)) * 1.15),
                },
                source="requested larger size",
            )
        )

    if any(
        phrase in text
        for phrase in (
            "smaller",
            "reduce size",
            "make it small",
            "make him small",
            "make her small",
        )
    ):
        target = "chair" if "chair" in text else "subject"
        current = _element(scene, target)
        requirements.append(
            Requirement(
                key="maximum_size",
                target=target,
                expected={
                    "width": round(float(current.get("width", 200)) * 0.85),
                    "height": round(float(current.get("height", 200)) * 0.85),
                },
                source="requested smaller size",
            )
        )

    unique: dict[tuple[str, str], Requirement] = {}

    for requirement in requirements:
        unique[(requirement.target, requirement.key)] = requirement

    return list(unique.values())


def _value_for_requirement(
    scene: Scene,
    requirement: Requirement,
) -> Any:
    if requirement.target == "canvas":
        if requirement.key.startswith("canvas."):
            return scene.get("canvas", {}).get(
                requirement.key.split(".", 1)[1]
            )

        return scene.get("canvas", {}).get(requirement.key)

    item = _element(scene, requirement.target)

    if requirement.key == "element.exists":
        return bool(item)

    if requirement.key == "position.horizontal":
        canvas_width = float(scene.get("canvas", {}).get("width", 900))
        x = float(item.get("x", canvas_width / 2))

        if x < canvas_width * 0.42:
            return "left"

        if x > canvas_width * 0.58:
            return "right"

        return "centre"

    if requirement.key == "position.vertical":
        canvas_height = float(scene.get("canvas", {}).get("height", 900))
        y = float(item.get("y", canvas_height / 2))

        if y < canvas_height * 0.42:
            return "upper"

        if y > canvas_height * 0.58:
            return "lower"

        return "centre"

    if requirement.key in {"minimum_size", "maximum_size"}:
        return {
            "width": float(item.get("width", 0)),
            "height": float(item.get("height", 0)),
        }

    return item.get(requirement.key)


def _matches(actual: Any, requirement: Requirement) -> bool:
    expected = requirement.expected

    if requirement.key == "minimum_size":
        return bool(
            isinstance(actual, dict)
            and actual.get("width", 0) >= expected["width"]
            and actual.get("height", 0) >= expected["height"]
        )

    if requirement.key == "maximum_size":
        return bool(
            isinstance(actual, dict)
            and actual.get("width", 0) <= expected["width"]
            and actual.get("height", 0) <= expected["height"]
        )

    if isinstance(expected, str) and isinstance(actual, str):
        return normalise_text(actual) == normalise_text(expected)

    return actual == expected


def evaluate_scene(
    scene: Scene,
    requirements: list[Requirement],
) -> Evaluation:
    """Measure explicit instruction coverage, not subjective aesthetics."""

    if not requirements:
        return Evaluation(
            score=0.0,
            unmet=["No supported explicit visual requirement was extracted."],
            details={"requirements": []},
        )

    satisfied: list[str] = []
    unmet: list[str] = []
    details: dict[str, Any] = {}
    earned = 0.0
    total = 0.0

    for requirement in requirements:
        label = f"{requirement.target}.{requirement.key}"
        actual = _value_for_requirement(scene, requirement)
        matched = _matches(actual, requirement)
        total += requirement.weight

        if matched:
            earned += requirement.weight
            satisfied.append(label)
        else:
            unmet.append(label)

        details[label] = {
            "expected": deepcopy(requirement.expected),
            "actual": deepcopy(actual),
            "matched": matched,
            "source": requirement.source,
            "weight": requirement.weight,
        }

    return Evaluation(
        score=round(earned / total, 6) if total else 0.0,
        satisfied=satisfied,
        unmet=unmet,
        details=details,
    )


def plan_operations(
    scene: Scene,
    requirements: list[Requirement],
    evaluation: Evaluation,
) -> list[Operation]:
    """Plan only operations needed for currently unmet requirements."""

    operations: list[Operation] = []
    unmet = set(evaluation.unmet)
    canvas = scene.get("canvas", {})
    canvas_width = float(canvas.get("width", 900))
    canvas_height = float(canvas.get("height", 900))

    for requirement in requirements:
        label = f"{requirement.target}.{requirement.key}"

        if label not in unmet:
            continue

        if requirement.target == "canvas":
            path = requirement.key.split(".", 1)[-1]
            operations.append(
                {
                    "op": "set_canvas",
                    "path": path,
                    "value": deepcopy(requirement.expected),
                    "reason": requirement.source,
                }
            )
            continue

        if requirement.key == "element.exists":
            if requirement.target == "chair":
                operations.append(
                    {
                        "op": "add",
                        "element": {
                            "id": "chair",
                            "type": "chair",
                            "x": canvas_width / 2,
                            "y": canvas_height * 0.74,
                            "width": 440,
                            "height": 250,
                            "colour": "#7a4b2a",
                            "z": 4,
                        },
                        "reason": requirement.source,
                    }
                )

                subject = _subject(scene)

                if subject.get("pose") != "seated":
                    operations.append(
                        {
                            "op": "set",
                            "element_id": "subject",
                            "path": "pose",
                            "value": "seated",
                            "reason": "chair requires a coherent seated pose",
                        }
                    )
            continue

        if requirement.key == "position.horizontal":
            target_x = (
                canvas_width * 0.30
                if requirement.expected == "left"
                else canvas_width * 0.70
            )
            operations.append(
                {
                    "op": "set",
                    "element_id": requirement.target,
                    "path": "x",
                    "value": round(target_x),
                    "reason": requirement.source,
                }
            )
            continue

        if requirement.key == "position.vertical":
            target_y = (
                canvas_height * 0.30
                if requirement.expected == "upper"
                else canvas_height * 0.70
            )
            operations.append(
                {
                    "op": "set",
                    "element_id": requirement.target,
                    "path": "y",
                    "value": round(target_y),
                    "reason": requirement.source,
                }
            )
            continue

        if requirement.key in {"minimum_size", "maximum_size"}:
            operations.extend(
                [
                    {
                        "op": "set",
                        "element_id": requirement.target,
                        "path": "width",
                        "value": requirement.expected["width"],
                        "reason": requirement.source,
                    },
                    {
                        "op": "set",
                        "element_id": requirement.target,
                        "path": "height",
                        "value": requirement.expected["height"],
                        "reason": requirement.source,
                    },
                ]
            )
            continue

        operations.append(
            {
                "op": "set",
                "element_id": requirement.target,
                "path": requirement.key,
                "value": deepcopy(requirement.expected),
                "reason": requirement.source,
            }
        )

    deduplicated: list[Operation] = []
    seen: set[tuple[Any, ...]] = set()

    for operation in operations:
        identity = (
            operation.get("op"),
            operation.get("element_id"),
            operation.get("path"),
            repr(operation.get("value")),
            repr(operation.get("element")),
        )

        if identity in seen:
            continue

        seen.add(identity)
        deduplicated.append(operation)

    return deduplicated


def improve_scene_until_satisfied(
    request: str,
    scene: Scene,
    apply_operations: Callable[[Scene, list[Operation]], Scene],
    *,
    threshold: float = 1.0,
    max_iterations: int = 6,
) -> ImprovementResult:
    """Run a safe, bounded plan/evaluate/improve loop."""

    requirements = extract_requirements(request, scene)

    if not requirements:
        raise ValueError(
            "No supported explicit visual requirement was extracted."
        )

    candidate = deepcopy(scene)
    all_operations: list[Operation] = []
    audit: list[dict[str, Any]] = []
    previous_signature: tuple[Any, ...] | None = None
    stop_reason = "iteration_limit"
    evaluation = evaluate_scene(candidate, requirements)

    for iteration in range(max(1, int(max_iterations)) + 1):
        evaluation = evaluate_scene(candidate, requirements)

        audit.append(
            {
                "iteration": iteration,
                "score": evaluation.score,
                "satisfied": list(evaluation.satisfied),
                "unmet": list(evaluation.unmet),
            }
        )

        if evaluation.score >= threshold:
            stop_reason = "requirements_satisfied"
            break

        operations = plan_operations(
            candidate,
            requirements,
            evaluation,
        )

        if not operations:
            stop_reason = "no_safe_improvement"
            break

        signature = tuple(
            (
                operation.get("op"),
                operation.get("element_id"),
                operation.get("path"),
                repr(operation.get("value")),
                repr(operation.get("element")),
            )
            for operation in operations
        )

        if signature == previous_signature:
            stop_reason = "stagnation_detected"
            break

        previous_signature = signature
        candidate = apply_operations(candidate, operations)
        all_operations.extend(deepcopy(operations))
    else:
        evaluation = evaluate_scene(candidate, requirements)

    evaluation = evaluate_scene(candidate, requirements)

    return ImprovementResult(
        scene=candidate,
        operations=all_operations,
        evaluation=evaluation,
        iterations=len(audit),
        stop_reason=stop_reason,
        audit=audit,
    )
