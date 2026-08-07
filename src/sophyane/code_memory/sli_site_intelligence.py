"""Deterministic semantic planning for Sophyane rich topic sites.

This module deliberately does not use an LLM.

Its job is to convert already-grounded topic evidence into a bounded
presentation plan so unrelated subjects are not forced through one
universal website template.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Protocol


class TopicLike(Protocol):
    requested_topic: str
    resolved_title: str
    extract: str


class EntityLike(Protocol):
    title: str
    extract: str
    category: str


@dataclass(frozen=True)
class SiteIntent:
    subject_type: str
    narrative_mode: str
    family: str

    chronology: bool
    metrics: bool
    gallery: bool
    relationship_focus: bool

    density: str
    hero_mode: str
    primary_interaction: str

    confidence: float


@dataclass(frozen=True)
class SitePlan:
    family: str
    visual_family: str

    hero_kicker: str

    feature_eyebrow: str
    feature_title: str
    feature_intro: str

    primary_interaction: str

    section_labels: tuple[
        str,
        str,
        str,
        str,
    ]

    accent: str
    accent2: str

    chronology: bool
    metrics: bool
    gallery: bool

    density: str

    design_generated: bool = False
    design_concept: str = ""
    narrative_shape: str = ""
    hero_treatment: str = ""
    layout_strategy: str = ""
    interaction_concepts: tuple[str, ...] = ()
    visual_mood: str = ""
    visual_rhythm: str = ""


_RESEARCH = {
    "research": 3,
    "researcher": 4,
    "scientist": 4,
    "science": 2,
    "artificial intelligence": 5,
    "machine learning": 5,
    "deepmind": 6,
    "alphafold": 6,
    "alphago": 6,
    "laboratory": 2,
    "lab": 2,
    "protein": 3,
    "chemistry": 3,
    "nobel": 4,
    "algorithm": 3,
    "computer science": 4,
    "technology": 2,
    "engineer": 2,
    "invention": 2,
    "discovery": 2,
}

_PUBLIC_LIFE = {
    "politician": 5,
    "political": 4,
    "prime minister": 7,
    "president": 6,
    "government": 4,
    "minister": 5,
    "parliament": 4,
    "election": 4,
    "party": 3,
    "campaign": 3,
    "public office": 5,
    "activist": 3,
    "philanthropist": 3,
    "cricketer": 3,
    "captain": 2,
    "world cup": 3,
    "career": 2,
}

_SPORT = {
    "cricket": 5,
    "football": 5,
    "tennis": 5,
    "basketball": 5,
    "athlete": 5,
    "player": 3,
    "captain": 3,
    "tournament": 3,
    "world cup": 5,
    "championship": 4,
    "team": 2,
    "coach": 3,
}

_PLACE = {
    "city": 4,
    "country": 3,
    "capital": 4,
    "district": 4,
    "province": 4,
    "region": 3,
    "located": 2,
    "population": 3,
    "geography": 5,
    "tourism": 4,
    "landmark": 4,
    "architecture": 2,
    "river": 2,
    "mountain": 2,
}

_ORGANISATION = {
    "company": 4,
    "corporation": 4,
    "organisation": 4,
    "organization": 4,
    "founded": 2,
    "headquarters": 5,
    "subsidiary": 4,
    "business": 3,
    "revenue": 3,
    "employees": 3,
    "institution": 3,
}

_CULTURE = {
    "artist": 4,
    "actor": 4,
    "musician": 4,
    "writer": 4,
    "author": 4,
    "film": 3,
    "music": 3,
    "novel": 3,
    "album": 3,
    "director": 3,
    "culture": 2,
}


def _normalise(value: str) -> str:
    return " ".join(
        str(
            value
            or ""
        ).lower().split()
    )


def _score(
    text: str,
    vocabulary: dict[str, int],
) -> int:
    score = 0

    for phrase, weight in vocabulary.items():
        if phrase in text:
            score += weight

    return score


def _entity_text(
    entities: Iterable[EntityLike],
) -> str:
    parts: list[str] = []

    for entity in entities:
        parts.extend(
            (
                entity.title,
                entity.extract,
                entity.category,
            )
        )

    return _normalise(
        " ".join(
            parts
        )
    )


def infer_site_intent(
    source: TopicLike,
    entities: list[EntityLike],
) -> SiteIntent:
    """Infer a bounded presentation intent from grounded evidence."""
    primary = _normalise(
        " ".join(
            (
                source.requested_topic,
                source.resolved_title,
                source.extract,
            )
        )
    )

    related = _entity_text(
        entities
    )

    # Primary-source evidence is intentionally weighted more strongly
    # than discovered related entities.
    text = (
        primary
        + " "
        + related
    )

    scores = {
        "research-profile":
            _score(
                primary,
                _RESEARCH,
            )
            * 2
            + _score(
                related,
                _RESEARCH,
            ),

        "public-life":
            _score(
                primary,
                _PUBLIC_LIFE,
            )
            * 2
            + _score(
                related,
                _PUBLIC_LIFE,
            ),

        "sports-career":
            _score(
                primary,
                _SPORT,
            )
            * 2
            + _score(
                related,
                _SPORT,
            ),

        "place-guide":
            _score(
                primary,
                _PLACE,
            )
            * 2
            + _score(
                related,
                _PLACE,
            ),

        "organisation-profile":
            _score(
                primary,
                _ORGANISATION,
            )
            * 2
            + _score(
                related,
                _ORGANISATION,
            ),

        "culture-profile":
            _score(
                primary,
                _CULTURE,
            )
            * 2
            + _score(
                related,
                _CULTURE,
            ),
    }

    family = max(
        scores,
        key=scores.get,
    )

    winning = scores[
        family
    ]

    ordered = sorted(
        scores.values(),
        reverse=True,
    )

    runner_up = (
        ordered[1]
        if len(ordered) > 1
        else 0
    )

    # If there is little semantic evidence, deliberately fall back to
    # the general editorial composition instead of pretending certainty.
    if winning < 5:
        family = "editorial"
        confidence = 0.35
    else:
        margin = max(
            0,
            winning - runner_up,
        )

        confidence = min(
            0.98,
            0.55
            + (
                min(
                    winning,
                    30,
                )
                / 100
            )
            + (
                min(
                    margin,
                    15,
                )
                / 100
            ),
        )

    born = bool(
        re.search(
            r"\bborn\b",
            primary,
        )
    )

    dated = len(
        re.findall(
            r"\b(?:18|19|20)\d{2}\b",
            primary,
        )
    )

    chronology = bool(
        born
        or dated >= 3
        or family
        in {
            "public-life",
            "sports-career",
            "research-profile",
        }
    )

    metrics = bool(
        re.search(
            r"\b\d+(?:\.\d+)?%?\b",
            text,
        )
        or family
        in {
            "research-profile",
            "public-life",
            "sports-career",
            "organisation-profile",
        }
    )

    gallery = bool(
        len(
            entities
        )
        >= 3
    )

    relationship_focus = bool(
        len(
            entities
        )
        >= 5
    )

    if family == "research-profile":
        return SiteIntent(
            subject_type=
                "researcher-or-innovator",

            narrative_mode=
                "breakthrough-arc",

            family=family,

            chronology=chronology,
            metrics=metrics,
            gallery=gallery,

            relationship_focus=
                relationship_focus,

            density=
                "analytical",

            hero_mode=
                "identity-portrait",

            primary_interaction=
                "milestone-exploration",

            confidence=confidence,
        )

    if family == "public-life":
        return SiteIntent(
            subject_type=
                "public-figure",

            narrative_mode=
                "life-phases",

            family=family,

            chronology=True,
            metrics=metrics,
            gallery=gallery,

            relationship_focus=
                relationship_focus,

            density=
                "documentary",

            hero_mode=
                "identity-portrait",

            primary_interaction=
                "chapter-navigation",

            confidence=confidence,
        )

    if family == "sports-career":
        return SiteIntent(
            subject_type=
                "athlete",

            narrative_mode=
                "career-arc",

            family=family,

            chronology=True,
            metrics=True,
            gallery=gallery,

            relationship_focus=
                relationship_focus,

            density=
                "kinetic",

            hero_mode=
                "identity-portrait",

            primary_interaction=
                "career-milestones",

            confidence=confidence,
        )

    if family == "place-guide":
        return SiteIntent(
            subject_type=
                "place",

            narrative_mode=
                "exploration-guide",

            family=family,

            chronology=False,
            metrics=True,
            gallery=gallery,

            relationship_focus=False,

            density=
                "spatial",

            hero_mode=
                "environment",

            primary_interaction=
                "guided-exploration",

            confidence=confidence,
        )

    if family == "organisation-profile":
        return SiteIntent(
            subject_type=
                "organisation",

            narrative_mode=
                "institutional-profile",

            family=family,

            chronology=chronology,
            metrics=True,
            gallery=gallery,

            relationship_focus=True,

            density=
                "structured",

            hero_mode=
                "institutional",

            primary_interaction=
                "capability-exploration",

            confidence=confidence,
        )

    if family == "culture-profile":
        return SiteIntent(
            subject_type=
                "cultural-subject",

            narrative_mode=
                "portfolio-story",

            family=family,

            chronology=chronology,
            metrics=False,
            gallery=True,

            relationship_focus=
                relationship_focus,

            density=
                "visual",

            hero_mode=
                "identity-portrait",

            primary_interaction=
                "work-exploration",

            confidence=confidence,
        )

    return SiteIntent(
        subject_type=
            "general-topic",

        narrative_mode=
            "editorial-directory",

        family=
            "editorial",

        chronology=
            chronology,

        metrics=
            metrics,

        gallery=
            gallery,

        relationship_focus=
            relationship_focus,

        density=
            "balanced",

        hero_mode=
            "editorial",

        primary_interaction=
            "story-exploration",

        confidence=
            confidence,
    )


def build_site_plan(
    source: TopicLike,
    entities: list[EntityLike],
) -> SitePlan:
    intent = infer_site_intent(
        source,
        entities,
    )

    if intent.family == "research-profile":
        return SitePlan(
            family=
                intent.family,

            visual_family=
                "research-editorial",

            hero_kicker=
                "Research · discovery · consequence",

            feature_eyebrow=
                "Research arc",

            feature_title=
                "Ideas that became milestones.",

            feature_intro=
                (
                    "The primary source is reorganised "
                    "as a sequence of research, institutions "
                    "and recognised breakthroughs."
                ),

            primary_interaction=
                intent.primary_interaction,

            section_labels=(
                "Foundations",
                "Research direction",
                "Breakthroughs",
                "Recognition",
            ),

            accent=
                "#70d7ff",

            accent2=
                "#8e7dff",

            chronology=
                intent.chronology,

            metrics=
                intent.metrics,

            gallery=
                intent.gallery,

            density=
                intent.density,
        )

    if intent.family == "public-life":
        return SitePlan(
            family=
                intent.family,

            visual_family=
                "documentary-biography",

            hero_kicker=
                "Life · career · public consequence",

            feature_eyebrow=
                "Life chapters",

            feature_title=
                "A career told in distinct eras.",

            feature_intro=
                (
                    "The source is arranged as successive "
                    "phases rather than a generic profile grid."
                ),

            primary_interaction=
                intent.primary_interaction,

            section_labels=(
                "Origins",
                "Career",
                "Public life",
                "Institutions & legacy",
            ),

            accent=
                "#ffb45f",

            accent2=
                "#e96b5f",

            chronology=True,

            metrics=
                intent.metrics,

            gallery=
                intent.gallery,

            density=
                intent.density,
        )

    if intent.family == "sports-career":
        return SitePlan(
            family=
                intent.family,

            visual_family=
                "sport-documentary",

            hero_kicker=
                "Competition · career · milestones",

            feature_eyebrow=
                "Career trajectory",

            feature_title=
                "The defining stages of the journey.",

            feature_intro=
                (
                    "Career evidence is organised around "
                    "progression and major competitive phases."
                ),

            primary_interaction=
                intent.primary_interaction,

            section_labels=(
                "Beginnings",
                "Rise",
                "Peak",
                "After the field",
            ),

            accent=
                "#a7ef68",

            accent2=
                "#53d7b1",

            chronology=True,

            metrics=True,

            gallery=
                intent.gallery,

            density=
                intent.density,
        )

    if intent.family == "place-guide":
        return SitePlan(
            family=
                intent.family,

            visual_family=
                "place-atlas",

            hero_kicker=
                "Place · culture · context",

            feature_eyebrow=
                "Orientation",

            feature_title=
                "Understand the place through layers.",

            feature_intro=
                (
                    "Geographic and cultural context is "
                    "presented as a guide rather than a biography."
                ),

            primary_interaction=
                intent.primary_interaction,

            section_labels=(
                "Orientation",
                "Character",
                "Culture",
                "Connections",
            ),

            accent=
                "#72dfb4",

            accent2=
                "#5aa8ff",

            chronology=False,

            metrics=True,

            gallery=
                intent.gallery,

            density=
                intent.density,
        )

    if intent.family == "organisation-profile":
        return SitePlan(
            family=
                intent.family,

            visual_family=
                "institutional-system",

            hero_kicker=
                "Institution · capability · influence",

            feature_eyebrow=
                "Organisation map",

            feature_title=
                "What the institution is built to do.",

            feature_intro=
                (
                    "The source is organised around purpose, "
                    "capabilities, evolution and relationships."
                ),

            primary_interaction=
                intent.primary_interaction,

            section_labels=(
                "Purpose",
                "Capabilities",
                "Evolution",
                "Network",
            ),

            accent=
                "#65d8df",

            accent2=
                "#f2c35f",

            chronology=
                intent.chronology,

            metrics=True,

            gallery=
                intent.gallery,

            density=
                intent.density,
        )

    if intent.family == "culture-profile":
        return SitePlan(
            family=
                intent.family,

            visual_family=
                "culture-portfolio",

            hero_kicker=
                "Work · influence · cultural context",

            feature_eyebrow=
                "Creative arc",

            feature_title=
                "The work before the directory.",

            feature_intro=
                (
                    "The composition prioritises creative "
                    "development and cultural context."
                ),

            primary_interaction=
                intent.primary_interaction,

            section_labels=(
                "Origins",
                "Practice",
                "Defining work",
                "Influence",
            ),

            accent=
                "#f08ac4",

            accent2=
                "#ffc45f",

            chronology=
                intent.chronology,

            metrics=False,

            gallery=True,

            density=
                intent.density,
        )

    return SitePlan(
        family=
            "editorial",

        visual_family=
            "storyworld-editorial",

        hero_kicker=
            "Internet-grounded editorial experience",

        feature_eyebrow=
            "Subject map",

        feature_title=
            "Context before the directory.",

        feature_intro=
            (
                "Sophyane organised the strongest source "
                "fragments before exposing related profiles."
            ),

        primary_interaction=
            intent.primary_interaction,

        section_labels=(
            "Overview",
            "Context",
            "Connections",
            "Impact",
        ),

        accent=
            "#ffb45f",

        accent2=
            "#e66395",

        chronology=
            intent.chronology,

        metrics=
            intent.metrics,

        gallery=
            intent.gallery,

        density=
            intent.density,
    )


def apply_design_proposal(
    plan: SitePlan,
    proposal,
) -> SitePlan:
    """Apply bounded creative direction without changing semantic authority."""
    if not getattr(
        proposal,
        "accepted",
        False,
    ):
        return plan

    raw_labels = tuple(
        str(
            item
            or ""
        ).strip()
        for item in getattr(
            proposal,
            "section_labels",
            (),
        )
    )

    labels = (
        raw_labels
        if (
            len(raw_labels) == 4
            and all(
                raw_labels
            )
        )
        else plan.section_labels
    )

    proposed_interaction = str(
        getattr(
            proposal,
            "primary_interaction",
            "",
        )
        or ""
    ).strip()

    if not proposed_interaction:
        proposed_interaction = (
            plan.primary_interaction
        )

    return SitePlan(
        # Deterministic authority.
        family=plan.family,
        visual_family=plan.visual_family,

        # Bounded creative fields.
        hero_kicker=(
            str(
                getattr(
                    proposal,
                    "concept",
                    "",
                )
                or plan.hero_kicker
            ).strip()
            or plan.hero_kicker
        ),
        feature_eyebrow=(
            plan.feature_eyebrow
        ),
        feature_title=(
            str(
                getattr(
                    proposal,
                    "feature_title",
                    "",
                )
                or plan.feature_title
            ).strip()
            or plan.feature_title
        ),
        feature_intro=(
            str(
                getattr(
                    proposal,
                    "feature_intro",
                    "",
                )
                or plan.feature_intro
            ).strip()
            or plan.feature_intro
        ),
        primary_interaction=(
            proposed_interaction
        ),
        section_labels=(
            labels[0],
            labels[1],
            labels[2],
            labels[3],
        ),

        # Deterministic visual/safety decisions remain fixed.
        accent=plan.accent,
        accent2=plan.accent2,
        chronology=plan.chronology,
        metrics=plan.metrics,
        gallery=plan.gallery,
        density=plan.density,

        # Design evidence.
        design_generated=bool(
            getattr(
                proposal,
                "generated",
                False,
            )
        ),
        design_concept=str(
            getattr(
                proposal,
                "concept",
                "",
            )
            or ""
        ).strip(),
        narrative_shape=str(
            getattr(
                proposal,
                "narrative_shape",
                "",
            )
            or ""
        ).strip(),
        hero_treatment=str(
            getattr(
                proposal,
                "hero_treatment",
                "",
            )
            or ""
        ).strip(),
        layout_strategy=str(
            getattr(
                proposal,
                "layout_strategy",
                "",
            )
            or ""
        ).strip(),
        interaction_concepts=tuple(
            str(
                item
            ).strip()
            for item in getattr(
                proposal,
                "interaction_concepts",
                (),
            )
            if str(
                item
            ).strip()
        ),
        visual_mood=str(
            getattr(
                proposal,
                "visual_mood",
                "",
            )
            or ""
        ).strip(),
        visual_rhythm=str(
            getattr(
                proposal,
                "visual_rhythm",
                "",
            )
            or ""
        ).strip(),
    )
