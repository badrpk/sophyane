"""Intent-driven deterministic visualization capability.

This module is provider-agnostic and mode-agnostic.

Its responsibilities are deliberately narrow:

user intent
    -> visualization intent classification
    -> grounded numeric data extraction
    -> deterministic chart selection
    -> PNG + JSON artifacts

It must never invent numeric data merely to satisfy graph intent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
from typing import Iterable


# SOPHYANE_VISUALIZATION_INTENT_V1


@dataclass(frozen=True)
class VisualizationIntent:
    requested: bool
    explicit: bool
    chart_type: str
    reason: str


@dataclass(frozen=True)
class DataPoint:
    label: str
    value: float


_EXPLICIT_GRAPH_PATTERNS = (
    r"\bgraph\b",
    r"\bchart\b",
    r"\bplot\b",
    r"\bvisuali[sz]e\b",
    r"\bvisual comparison\b",
    r"\bline graph\b",
    r"\bline chart\b",
    r"\bbar graph\b",
    r"\bbar chart\b",
    r"\bpie chart\b",
    r"\bscatter(?:\s+plot)?\b",
)


_IMPLICIT_VISUAL_PATTERNS = (
    r"\bshow\s+(?:me\s+)?(?:the\s+)?flow\b",
    r"\bshow\s+how\s+(?:this|it)\s+works\s+visually\b",
    r"\bshow\s+(?:me\s+)?how\b.*\bchanged\b",
    r"\bshow\s+(?:me\s+)?the\s+trend\b",
    r"\bshow\s+(?:me\s+)?the\s+growth\b",
    r"\bcompare\b.*\bvisually\b",
    r"\bshow\b.*\bover\s+time\b",
    r"\btrend\s+over\b",
    r"\bmonthly\s+trend\b",
    r"\byearly\s+trend\b",
    r"\bquarterly\s+trend\b",
)


_NON_VISUAL_EXPLANATION_PATTERNS = (
    r"\bwhat\s+is\s+(?:a\s+)?graph\s+database\b",
    r"\bexplain\s+(?:a\s+)?graph\b",
    r"\bwhat\s+does\s+this\s+(?:graph|chart)\s+mean\b",
    r"\bexplain\s+matplotlib\b",
)


_TIME_WORDS = (
    "month",
    "monthly",
    "year",
    "yearly",
    "day",
    "daily",
    "week",
    "weekly",
    "quarter",
    "quarterly",
    "over time",
    "trend",
    "changed",
    "growth",
)


def detect_visualization_intent(
    request: str,
) -> VisualizationIntent:
    """Classify explicit or semantically obvious visualization intent."""

    text = str(
        request
        or ""
    ).strip()

    lowered = text.casefold()

    if not lowered:
        return VisualizationIntent(
            requested=False,
            explicit=False,
            chart_type="",
            reason="empty request",
        )

    if any(
        re.search(
            pattern,
            lowered,
        )
        for pattern in _NON_VISUAL_EXPLANATION_PATTERNS
    ):
        return VisualizationIntent(
            requested=False,
            explicit=False,
            chart_type="",
            reason="explanatory graph reference",
        )

    explicit = any(
        re.search(
            pattern,
            lowered,
        )
        for pattern in _EXPLICIT_GRAPH_PATTERNS
    )

    implicit = any(
        re.search(
            pattern,
            lowered,
        )
        for pattern in _IMPLICIT_VISUAL_PATTERNS
    )

    if not (
        explicit
        or implicit
    ):
        return VisualizationIntent(
            requested=False,
            explicit=False,
            chart_type="",
            reason="no visualization intent",
        )

    if (
        "scatter" in lowered
        or (
            "relationship" in lowered
            and " vs " in lowered
        )
    ):
        chart_type = "scatter"

    elif (
        "pie" in lowered
        or "share of" in lowered
        or "percentage split" in lowered
        or "composition" in lowered
    ):
        chart_type = "pie"

    elif (
        "bar" in lowered
        or "compare" in lowered
        or "ranking" in lowered
        or "ranked" in lowered
    ):
        chart_type = "bar"

    elif any(
        word in lowered
        for word in _TIME_WORDS
    ):
        chart_type = "line"

    else:
        chart_type = "bar"

    return VisualizationIntent(
        requested=True,
        explicit=explicit,
        chart_type=chart_type,
        reason=(
            "explicit visualization request"
            if explicit
            else "implicit visualization request"
        ),
    )


_LABEL_VALUE_PATTERN = re.compile(
    r"""
    (?P<label>
        [A-Za-z][A-Za-z0-9_./() -]{0,80}?
    )
    \s*
    (?:
        [:=-]
        |
        \bis\b
    )
    \s*
    (?P<value>
        [-+]?
        (?:\d+(?:,\d{3})*|\d*)
        (?:\.\d+)?
    )
    (?:
        \s*
        (?P<suffix>
            %
            |k
            |m
            |b
        )
    )?
    (?=
        \s*(?:,|;|\n|$)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


_SIMPLE_NUMBER_PATTERN = re.compile(
    r"""
    (?<![\w.])
    [-+]?
    (?:\d+(?:,\d{3})*|\d+)
    (?:\.\d+)?
    (?:%|[kKmMbB])?
    (?![\w.])
    """,
    re.VERBOSE,
)


def _numeric_value(
    raw: str,
) -> float:
    value = str(
        raw
    ).strip()

    suffix = ""

    if (
        value
        and value[-1:].casefold()
        in {
            "k",
            "m",
            "b",
            "%",
        }
    ):
        suffix = value[-1:].casefold()
        value = value[:-1]

    number = float(
        value.replace(
            ",",
            "",
        )
    )

    multiplier = {
        "": 1.0,
        "%": 1.0,
        "k": 1_000.0,
        "m": 1_000_000.0,
        "b": 1_000_000_000.0,
    }[
        suffix
    ]

    return number * multiplier


def extract_grounded_points(
    request: str,
) -> list[DataPoint]:
    """Extract numeric data that is visibly present in the request.

    This intentionally does not infer or manufacture missing numbers.
    """

    text = str(
        request
        or ""
    )

    points: list[DataPoint] = []

    for match in _LABEL_VALUE_PATTERN.finditer(
        text
    ):
        raw_value = (
            match.group(
                "value"
            )
            or ""
        )

        suffix = (
            match.group(
                "suffix"
            )
            or ""
        )

        if not raw_value.strip():
            continue

        try:
            value = _numeric_value(
                raw_value
                + suffix
            )
        except ValueError:
            continue

        if not math.isfinite(
            value
        ):
            continue

        label = (
            match.group(
                "label"
            )
            or ""
        ).strip(
            " ,;:-"
        )

        if not label:
            continue

        points.append(
            DataPoint(
                label=label,
                value=value,
            )
        )

    if points:
        return points

    #
    # Fallback for requests like:
    #
    #   plot 10, 20, 18, 35
    #
    # The values are grounded but unlabeled, so deterministic ordinal labels
    # are safe.
    #
    matches = list(
        _SIMPLE_NUMBER_PATTERN.finditer(
            text
        )
    )

    if len(matches) < 2:
        return []

    values: list[float] = []

    for match in matches:
        try:
            value = _numeric_value(
                match.group(0)
            )
        except ValueError:
            continue

        if math.isfinite(
            value
        ):
            values.append(
                value
            )

    if len(values) < 2:
        return []

    return [
        DataPoint(
            label=str(
                index
            ),
            value=value,
        )
        for index, value in enumerate(
            values,
            start=1,
        )
    ]


def _safe_slug(
    value: str,
) -> str:
    slug = re.sub(
        r"[^a-zA-Z0-9]+",
        "-",
        str(
            value
            or ""
        ).strip(),
    ).strip(
        "-"
    ).lower()

    return (
        slug[:64]
        or "visualization"
    )


def render_visualization(
    *,
    request: str,
    workspace: Path,
    title: str = "",
) -> dict[str, object]:
    """Render grounded request data into PNG + JSON artifacts."""

    intent = detect_visualization_intent(
        request
    )

    if not intent.requested:
        return {
            "handled": False,
            "reason": intent.reason,
        }

    points = extract_grounded_points(
        request
    )

    if not points:
        return {
            "handled": False,
            "reason": (
                "visualization requested but no grounded "
                "numeric data was available"
            ),
            "intent": asdict(
                intent
            ),
        }

    workspace = Path(
        workspace
    ).expanduser().resolve()

    artifact_dir = (
        workspace
        / "artifacts"
    )

    artifact_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    chart_title = (
        str(
            title
            or ""
        ).strip()
        or "Sophyane visualization"
    )

    stem = _safe_slug(
        chart_title
    )

    png_path = (
        artifact_dir
        / f"{stem}.png"
    )

    json_path = (
        artifact_dir
        / f"{stem}.json"
    )

    payload = {
        "version": 1,
        "source": "user-grounded",
        "intent": asdict(
            intent
        ),
        "title": chart_title,
        "chart_type": intent.chart_type,
        "points": [
            asdict(
                point
            )
            for point in points
        ],
    }

    json_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    #
    # Import matplotlib lazily so ordinary Sophyane requests do not acquire
    # visualization startup cost.
    #
    try:
        import matplotlib

        matplotlib.use(
            "Agg"
        )

        import matplotlib.pyplot as plt

    except Exception as error:
        return {
            "handled": False,
            "reason": (
                "visualization renderer unavailable: "
                + type(
                    error
                ).__name__
                + ": "
                + str(
                    error
                )
            ),
            "json_path": str(
                json_path
            ),
            "intent": asdict(
                intent
            ),
        }

    labels = [
        point.label
        for point in points
    ]

    values = [
        point.value
        for point in points
    ]

    fig, ax = plt.subplots(
        figsize=(
            9,
            5,
        )
    )

    try:
        if intent.chart_type == "line":
            ax.plot(
                labels,
                values,
                marker="o",
            )

        elif intent.chart_type == "pie":
            if any(
                value < 0
                for value in values
            ):
                raise ValueError(
                    "pie chart values cannot be negative"
                )

            if sum(
                values
            ) <= 0:
                raise ValueError(
                    "pie chart total must be positive"
                )

            ax.pie(
                values,
                labels=labels,
                autopct="%1.1f%%",
            )

        elif intent.chart_type == "scatter":
            #
            # A one-series label/value request does not contain a second
            # numeric variable. Preserve grounding and render ordinal x-values
            # rather than fabricating a relationship.
            #
            x_values = list(
                range(
                    1,
                    len(
                        values
                    )
                    + 1,
                )
            )

            ax.scatter(
                x_values,
                values,
            )

            ax.set_xticks(
                x_values,
                labels,
            )

        else:
            ax.bar(
                labels,
                values,
            )

        ax.set_title(
            chart_title
        )

        if intent.chart_type != "pie":
            ax.set_ylabel(
                "Value"
            )

            ax.tick_params(
                axis="x",
                labelrotation=30,
            )

        fig.tight_layout()

        fig.savefig(
            png_path,
            dpi=160,
        )

    finally:
        plt.close(
            fig
        )

    if not png_path.is_file():
        raise RuntimeError(
            "visualization PNG was not materialized"
        )

    if png_path.stat().st_size <= 0:
        raise RuntimeError(
            "visualization PNG is empty"
        )

    return {
        "handled": True,
        "intent": asdict(
            intent
        ),
        "chart_type": intent.chart_type,
        "point_count": len(
            points
        ),
        "png_path": str(
            png_path
        ),
        "json_path": str(
            json_path
        ),
        "source": "user-grounded",
    }


def visualization_response_text(
    result: dict[str, object],
) -> str:
    """Render a concise TUI response for a completed visualization."""

    if not bool(
        result.get(
            "handled"
        )
    ):
        return ""

    return "\n".join(
        (
            "◆ Sophyane visualization",
            (
                "  Chart: "
                + str(
                    result.get(
                        "chart_type",
                        "",
                    )
                )
            ),
            (
                "  Data points: "
                + str(
                    result.get(
                        "point_count",
                        0,
                    )
                )
            ),
            (
                "  Source: "
                + str(
                    result.get(
                        "source",
                        "grounded",
                    )
                )
            ),
            "  Verified: yes",
            "",
            "  Graph:",
            (
                "  "
                + str(
                    result.get(
                        "png_path",
                        "",
                    )
                )
            ),
            "",
            "  Data:",
            (
                "  "
                + str(
                    result.get(
                        "json_path",
                        "",
                    )
                )
            ),
        )
    )


__all__ = [
    "DataPoint",
    "VisualizationIntent",
    "detect_visualization_intent",
    "extract_grounded_points",
    "render_visualization",
    "visualization_response_text",
]
