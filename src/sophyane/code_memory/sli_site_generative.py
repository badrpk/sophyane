"""Bounded generative design intelligence for Sophyane topic sites.

The local LLM is allowed to propose presentation ideas only.

It may NOT:
- create or alter factual claims;
- select a different primary subject;
- replace primary image provenance;
- invent URLs;
- decide whether validation passes;
- write arbitrary final HTML.

The deterministic SLI planner remains authoritative.  The model proposes
creative direction inside a strict JSON contract.  The proposal is then
validated, normalised, reconciled with deterministic intent and converted
back into a bounded executable SitePlan.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Callable, Protocol


Progress = Callable[[str], None]


class TopicLike(Protocol):
    requested_topic: str
    resolved_title: str
    extract: str
    page_url: str


class EntityLike(Protocol):
    title: str
    extract: str
    category: str


class IntentLike(Protocol):
    family: str
    subject_type: str
    narrative_mode: str
    chronology: bool
    metrics: bool
    gallery: bool
    relationship_focus: bool
    density: str
    hero_mode: str
    primary_interaction: str
    confidence: float


@dataclass(frozen=True)
class CreativeBrief:
    subject: str
    requested_topic: str
    family: str
    subject_type: str
    narrative_mode: str
    chronology: bool
    metrics: bool
    gallery: bool
    relationship_focus: bool
    hero_mode: str
    deterministic_interaction: str
    evidence_summary: tuple[str, ...]
    related_entities: tuple[str, ...]
    related_categories: tuple[str, ...]


@dataclass(frozen=True)
class DesignProposal:
    accepted: bool
    generated: bool
    concept: str
    narrative_shape: str
    hero_treatment: str
    feature_title: str
    feature_intro: str
    section_labels: tuple[str, str, str, str]
    layout_strategy: str
    interaction_concepts: tuple[str, ...]
    visual_mood: str
    visual_rhythm: str
    primary_interaction: str
    reason: str = ""


_ALLOWED_LAYOUTS = {
    "research-profile": {
        "milestone-grid",
        "research-ledger",
        "discovery-sequence",
        "evidence-bands",
        "network-narrative",
    },
    "public-life": {
        "era-stack",
        "chapter-sequence",
        "documentary-ledger",
        "public-life-timeline",
        "three-act-biography",
    },
    "sports-career": {
        "career-track",
        "season-arc",
        "milestone-lanes",
        "competitive-timeline",
    },
    "place-guide": {
        "atlas-sequence",
        "district-layers",
        "orientation-grid",
        "journey-sections",
    },
    "organisation-profile": {
        "capability-map",
        "system-layers",
        "institution-ledger",
        "network-sections",
    },
    "culture-profile": {
        "portfolio-sequence",
        "creative-arc",
        "work-ledger",
        "influence-bands",
    },
    "editorial": {
        "editorial-sequence",
        "subject-map",
        "context-ledger",
    },
}


_ALLOWED_INTERACTIONS = {
    "research-profile": {
        "milestone-exploration",
        "research-path",
        "breakthrough-navigation",
        "evidence-navigation",
    },
    "public-life": {
        "chapter-navigation",
        "era-navigation",
        "life-phase-navigation",
    },
    "sports-career": {
        "career-milestones",
        "career-navigation",
        "competitive-phases",
    },
    "place-guide": {
        "guided-exploration",
        "context-navigation",
        "place-layers",
    },
    "organisation-profile": {
        "capability-exploration",
        "system-navigation",
        "relationship-navigation",
    },
    "culture-profile": {
        "work-exploration",
        "creative-navigation",
        "portfolio-navigation",
    },
    "editorial": {
        "story-exploration",
        "context-navigation",
    },
}


def _normalise_text(
    value: Any,
    *,
    limit: int,
) -> str:
    text = " ".join(
        str(
            value
            or ""
        ).strip().split()
    )

    text = re.sub(
        r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
        "",
        text,
    )

    return text[:limit]


def _sentences(
    text: str,
    limit: int = 6,
) -> tuple[str, ...]:
    candidates = [
        " ".join(
            item.strip().split()
        )
        for item in re.split(
            r"(?<=[.!?])\s+|\n+",
            text,
        )
        if len(
            item.strip()
        ) >= 35
    ]

    return tuple(
        item[:420]
        for item in candidates[:limit]
    )


def build_creative_brief(
    source: TopicLike,
    entities: list[EntityLike],
    intent: IntentLike,
) -> CreativeBrief:
    return CreativeBrief(
        subject=_normalise_text(
            source.resolved_title,
            limit=120,
        ),
        requested_topic=_normalise_text(
            source.requested_topic,
            limit=120,
        ),
        family=intent.family,
        subject_type=intent.subject_type,
        narrative_mode=intent.narrative_mode,
        chronology=bool(
            intent.chronology
        ),
        metrics=bool(
            intent.metrics
        ),
        gallery=bool(
            intent.gallery
        ),
        relationship_focus=bool(
            intent.relationship_focus
        ),
        hero_mode=intent.hero_mode,
        deterministic_interaction=(
            intent.primary_interaction
        ),
        evidence_summary=_sentences(
            source.extract,
            7,
        ),
        related_entities=tuple(
            _normalise_text(
                entity.title,
                limit=100,
            )
            for entity in entities[:12]
        ),
        related_categories=tuple(
            dict.fromkeys(
                _normalise_text(
                    entity.category,
                    limit=60,
                )
                for entity in entities[:12]
                if str(
                    entity.category
                    or ""
                ).strip()
            )
        ),
    )


def _brief_prompt(
    brief: CreativeBrief,
) -> str:
    payload = {
        "subject":
            brief.subject,
        "requested_topic":
            brief.requested_topic,
        "deterministic_family":
            brief.family,
        "subject_type":
            brief.subject_type,
        "narrative_mode":
            brief.narrative_mode,
        "chronology":
            brief.chronology,
        "metrics":
            brief.metrics,
        "gallery":
            brief.gallery,
        "relationship_focus":
            brief.relationship_focus,
        "hero_mode":
            brief.hero_mode,
        "required_primary_interaction":
            brief.deterministic_interaction,
        "evidence_summary":
            list(
                brief.evidence_summary
            ),
        "related_entities":
            list(
                brief.related_entities
            ),
        "related_categories":
            list(
                brief.related_categories
            ),
    }

    return (
        "You are Sophyane's bounded local design-intelligence worker.\n"
        "\n"
        "You are NOT writing HTML and you are NOT creating facts.\n"
        "All facts and identity are already grounded by deterministic SLI.\n"
        "\n"
        "Your task is only to propose a distinctive presentation concept "
        "for this specific subject while obeying the deterministic family.\n"
        "\n"
        "Return ONE JSON object only. No markdown. No commentary.\n"
        "\n"
        "Required JSON keys:\n"
        "{\n"
        '  "concept": "short distinctive concept name",\n'
        '  "narrative_shape": "short narrative description",\n'
        '  "hero_treatment": "visual treatment, never identity substitution",\n'
        '  "feature_title": "specific editorial section title",\n'
        '  "feature_intro": "1-2 concise sentences",\n'
        '  "section_labels": ["one", "two", "three", "four"],\n'
        '  "layout_strategy": "one bounded architecture token",\n'
        '  "interaction_concepts": ["one", "optional second"],\n'
        '  "visual_mood": "short mood description",\n'
        '  "visual_rhythm": "short structural rhythm description",\n'
        '  "primary_interaction": "one bounded interaction token"\n'
        "}\n"
        "\n"
        "Rules:\n"
        "- exactly four section_labels;\n"
        "- section labels must describe the supplied evidence, not new facts;\n"
        "- no URLs;\n"
        "- no invented quotations;\n"
        "- no claims not present in evidence;\n"
        "- never propose another person's photo as hero;\n"
        "- the deterministic family cannot change;\n"
        "- prefer a subject-specific concept instead of generic words such "
        "as journey, storyworld, explore, innovation, excellence, future;\n"
        "- keep all values compact;\n"
        "\n"
        "Grounded deterministic brief follows:\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


def _extract_json(
    response: str,
) -> dict[str, Any]:
    text = str(
        response
        or ""
    ).strip()

    if text.startswith(
        "```"
    ):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.I,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

    try:
        parsed = json.loads(
            text
        )

        if isinstance(
            parsed,
            dict,
        ):
            return parsed

    except Exception:
        pass

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if (
        start >= 0
        and end > start
    ):
        parsed = json.loads(
            text[
                start:
                end + 1
            ]
        )

        if isinstance(
            parsed,
            dict,
        ):
            return parsed

    raise ValueError(
        "local model did not return a JSON object"
    )


def _call_local_llm(
    prompt: str,
) -> str:
    """Use Sophyane's real local GGUF provider without cloud rescue.

    A llama-server that is actively loading the configured GGUF is
    treated as a transient state.  We wait for that same server rather
    than starting a competing model copy.
    """
    import time

    from sophyane.providers.base import (
        ProviderError,
    )

    from sophyane.providers.local_gguf import (
        LocalGgufProvider,
    )

    provider = LocalGgufProvider(
        timeout=90,
        temperature=0.45,
        max_tokens=768,
    )

    system_prompt = (
        "You are Sophyane's bounded local design-intelligence worker. "
        "Return exactly one valid JSON object and no markdown. "
        "Do not invent facts, URLs, quotations, identities, images, "
        "or executable code. "
        "Do not change the deterministic semantic family. "
        "Your role is limited to creative presentation planning."
    )

    def generate_once() -> str:
        value = provider.generate(
            prompt,
            system_prompt,
        )

        if not isinstance(
            value,
            str,
        ):
            raise RuntimeError(
                "local GGUF provider returned "
                "a non-text result"
            )

        value = value.strip()

        if not value:
            raise RuntimeError(
                "local GGUF provider returned "
                "empty design output"
            )

        return value

    try:
        return generate_once()

    except ProviderError as error:
        detail = str(
            error
        )

        loading = (
            "loading model"
            in detail.lower()
            or "still loading"
            in detail.lower()
        )

        if not loading:
            raise

        from sophyane.local_server import (
            ensure_server_background,
            failure_detail,
            wait_until_ready,
        )

        started, startup_message = (
            ensure_server_background()
        )

        # The provider/local_server layer owns the process.
        # Never create a second llama-cli/model copy here.
        if not started:
            raise ProviderError(
                "local GGUF design server "
                "could not be prepared: "
                + (
                    failure_detail()
                    or startup_message
                    or detail
                )
            ) from error

        if not wait_until_ready(
            timeout=75.0,
        ):
            raise ProviderError(
                "local GGUF design server "
                "remained unavailable after "
                "the bounded startup wait: "
                + (
                    failure_detail()
                    or startup_message
                    or detail
                )
            ) from error

        # Small readiness-settle interval.  The health endpoint can
        # become visible immediately before chat completion is ready.
        time.sleep(
            0.35
        )

        return generate_once()







_LAYOUT_ALIASES: dict[
    str,
    dict[str, str],
] = {
    "research-profile": {
        "grid":
            "milestone-grid",
        "grid layout":
            "milestone-grid",
        "milestone layout":
            "milestone-grid",
        "milestone grid":
            "milestone-grid",
        "research grid":
            "research-ledger",
        "research layout":
            "research-ledger",
        "research ledger":
            "research-ledger",
        "discovery sequence":
            "discovery-sequence",
        "discovery layout":
            "discovery-sequence",
        "sequence":
            "discovery-sequence",
        "evidence bands":
            "evidence-bands",
        "evidence layout":
            "evidence-bands",
        "network":
            "network-narrative",
        "network layout":
            "network-narrative",
        "network narrative":
            "network-narrative",
    },

    "public-life": {
        "stack":
            "era-stack",
        "era stack":
            "era-stack",
        "timeline":
            "public-life-timeline",
        "timeline layout":
            "public-life-timeline",
        "chapter layout":
            "chapter-sequence",
        "chapter sequence":
            "chapter-sequence",
        "documentary":
            "documentary-ledger",
        "documentary layout":
            "documentary-ledger",
        "biography":
            "three-act-biography",
        "biography layout":
            "three-act-biography",
    },

    "sports-career": {
        "timeline":
            "competitive-timeline",
        "career timeline":
            "competitive-timeline",
        "career track":
            "career-track",
        "track":
            "career-track",
        "season arc":
            "season-arc",
        "milestone layout":
            "milestone-lanes",
        "milestone lanes":
            "milestone-lanes",
    },

    "place-guide": {
        "atlas":
            "atlas-sequence",
        "atlas layout":
            "atlas-sequence",
        "map":
            "orientation-grid",
        "map layout":
            "orientation-grid",
        "grid":
            "orientation-grid",
        "grid layout":
            "orientation-grid",
        "journey":
            "journey-sections",
        "journey layout":
            "journey-sections",
        "district layout":
            "district-layers",
    },

    "organisation-profile": {
        "map":
            "capability-map",
        "capability map":
            "capability-map",
        "system":
            "system-layers",
        "system layout":
            "system-layers",
        "ledger":
            "institution-ledger",
        "institution layout":
            "institution-ledger",
        "network":
            "network-sections",
        "network layout":
            "network-sections",
    },

    "culture-profile": {
        "portfolio":
            "portfolio-sequence",
        "portfolio layout":
            "portfolio-sequence",
        "creative arc":
            "creative-arc",
        "creative layout":
            "creative-arc",
        "ledger":
            "work-ledger",
        "work layout":
            "work-ledger",
        "bands":
            "influence-bands",
        "influence bands":
            "influence-bands",
    },

    "editorial": {
        "editorial":
            "editorial-sequence",
        "editorial layout":
            "editorial-sequence",
        "sequence":
            "editorial-sequence",
        "map":
            "subject-map",
        "subject map":
            "subject-map",
        "ledger":
            "context-ledger",
        "context layout":
            "context-ledger",
    },
}


_INTERACTION_ALIASES: dict[
    str,
    dict[str, str],
] = {
    "research-profile": {
        "research navigation":
            "research-path",
        "research path":
            "research-path",
        "milestone navigation":
            "milestone-exploration",
        "milestone exploration":
            "milestone-exploration",
        "breakthrough navigation":
            "breakthrough-navigation",
        "evidence navigation":
            "evidence-navigation",
    },

    "public-life": {
        "chapter navigation":
            "chapter-navigation",
        "era navigation":
            "era-navigation",
        "life phase navigation":
            "life-phase-navigation",
        "timeline navigation":
            "era-navigation",
    },

    "sports-career": {
        "career navigation":
            "career-navigation",
        "career milestones":
            "career-milestones",
        "milestone navigation":
            "career-milestones",
        "competitive phases":
            "competitive-phases",
    },

    "place-guide": {
        "guided exploration":
            "guided-exploration",
        "context navigation":
            "context-navigation",
        "place layers":
            "place-layers",
        "map navigation":
            "place-layers",
    },

    "organisation-profile": {
        "capability exploration":
            "capability-exploration",
        "system navigation":
            "system-navigation",
        "relationship navigation":
            "relationship-navigation",
    },

    "culture-profile": {
        "work exploration":
            "work-exploration",
        "creative navigation":
            "creative-navigation",
        "portfolio navigation":
            "portfolio-navigation",
    },

    "editorial": {
        "story exploration":
            "story-exploration",
        "context navigation":
            "context-navigation",
    },
}


def _token_key(
    value: str,
) -> str:
    value = _normalise_text(
        value,
        limit=100,
    ).lower()

    value = value.replace(
        "_",
        " ",
    ).replace(
        "-",
        " ",
    )

    value = re.sub(
        r"[^a-z0-9 ]+",
        " ",
        value,
    )

    return " ".join(
        value.split()
    )


def _normalise_bounded_token(
    value: str,
    *,
    family: str,
    allowed: set[str],
    aliases: dict[
        str,
        dict[str, str],
    ],
) -> str:
    """Map natural model wording into a bounded executable token.

    Exact canonical tokens always win.  Only explicit family-specific
    aliases are accepted after that.  Unknown values remain invalid.
    """
    raw = _normalise_text(
        value,
        limit=100,
    ).lower()

    if raw in allowed:
        return raw

    key = _token_key(
        raw
    )

    # Canonical token expressed with spaces rather than hyphens.
    canonical_by_key = {
        _token_key(
            token
        ):
            token
        for token in allowed
    }

    canonical = canonical_by_key.get(
        key
    )

    if canonical:
        return canonical

    mapped = aliases.get(
        family,
        {},
    ).get(
        key
    )

    if (
        mapped
        and mapped in allowed
    ):
        return mapped

    return raw


def _proposal_from_payload(
    brief: CreativeBrief,
    payload: dict[str, Any],
) -> DesignProposal:
    allowed_layouts = _ALLOWED_LAYOUTS.get(
        brief.family,
        _ALLOWED_LAYOUTS[
            "editorial"
        ],
    )

    allowed_interactions = (
        _ALLOWED_INTERACTIONS.get(
            brief.family,
            _ALLOWED_INTERACTIONS[
                "editorial"
            ],
        )
    )

    concept = _normalise_text(
        payload.get(
            "concept"
        ),
        limit=90,
    )

    narrative_shape = _normalise_text(
        payload.get(
            "narrative_shape"
        ),
        limit=180,
    )

    hero_treatment = _normalise_text(
        payload.get(
            "hero_treatment"
        ),
        limit=180,
    )

    feature_title = _normalise_text(
        payload.get(
            "feature_title"
        ),
        limit=120,
    )

    feature_intro = _normalise_text(
        payload.get(
            "feature_intro"
        ),
        limit=320,
    )

    visual_mood = _normalise_text(
        payload.get(
            "visual_mood"
        ),
        limit=160,
    )

    visual_rhythm = _normalise_text(
        payload.get(
            "visual_rhythm"
        ),
        limit=180,
    )

    layout_strategy = _normalise_bounded_token(
        payload.get(
            "layout_strategy"
        ),
        family=brief.family,
        allowed=allowed_layouts,
        aliases=_LAYOUT_ALIASES,
    )

    primary_interaction = _normalise_bounded_token(
        payload.get(
            "primary_interaction"
        ),
        family=brief.family,
        allowed=allowed_interactions,
        aliases=_INTERACTION_ALIASES,
    )

    raw_labels = payload.get(
        "section_labels"
    )

    if not isinstance(
        raw_labels,
        list,
    ):
        raise ValueError(
            "section_labels must be a list"
        )

    labels = tuple(
        _normalise_text(
            value,
            limit=54,
        )
        for value in raw_labels
        if _normalise_text(
            value,
            limit=54,
        )
    )

    if len(labels) != 4:
        raise ValueError(
            "section_labels must contain exactly four non-empty labels"
        )

    raw_interactions = payload.get(
        "interaction_concepts",
        [],
    )

    if not isinstance(
        raw_interactions,
        list,
    ):
        raw_interactions = []

    interaction_concepts = tuple(
        _normalise_text(
            value,
            limit=80,
        )
        for value in raw_interactions[:3]
        if _normalise_text(
            value,
            limit=80,
        )
    )

    required = (
        concept,
        narrative_shape,
        hero_treatment,
        feature_title,
        feature_intro,
        visual_mood,
        visual_rhythm,
    )

    if not all(
        required
    ):
        raise ValueError(
            "proposal contains empty required fields"
        )

    if layout_strategy not in allowed_layouts:
        raise ValueError(
            "unsupported layout_strategy "
            f"for {brief.family}: {layout_strategy}"
        )

    if (
        primary_interaction
        not in allowed_interactions
    ):
        raise ValueError(
            "unsupported primary_interaction "
            f"for {brief.family}: {primary_interaction}"
        )

    forbidden_fragments = (
        "http://",
        "https://",
        "<script",
        "</script",
        "<img",
        "<iframe",
    )

    serialised = json.dumps(
        payload,
        ensure_ascii=False,
    ).lower()

    if any(
        marker in serialised
        for marker in forbidden_fragments
    ):
        raise ValueError(
            "proposal contains forbidden executable or URL material"
        )

    return DesignProposal(
        accepted=True,
        generated=True,
        concept=concept,
        narrative_shape=narrative_shape,
        hero_treatment=hero_treatment,
        feature_title=feature_title,
        feature_intro=feature_intro,
        section_labels=(
            labels[0],
            labels[1],
            labels[2],
            labels[3],
        ),
        layout_strategy=layout_strategy,
        interaction_concepts=(
            interaction_concepts
        ),
        visual_mood=visual_mood,
        visual_rhythm=visual_rhythm,
        primary_interaction=(
            primary_interaction
        ),
    )


def deterministic_design_proposal(
    brief: CreativeBrief,
    *,
    reason: str = "",
) -> DesignProposal:
    defaults: dict[
        str,
        tuple[
            str,
            str,
            str,
            str,
            tuple[
                str,
                str,
                str,
                str,
            ],
            str,
            tuple[str, ...],
            str,
            str,
            str,
        ],
    ] = {
        "research-profile": (
            "Evidence to Breakthrough",
            "research milestones arranged by consequence",
            "identity portrait with restrained evidence framing",
            "Ideas that became milestones.",
            (
                "Research evidence is organised as a progression "
                "from foundations through recognised breakthroughs."
            ),
            (
                "Foundations",
                "Research direction",
                "Breakthroughs",
                "Recognition",
            ),
            "milestone-grid",
            (
                "research-path",
            ),
            "scientific editorial",
            "quiet portrait, dense evidence, major milestone release",
            "milestone-exploration",
        ),
        "public-life": (
            "Public Life in Chapters",
            "successive eras of career and public consequence",
            "identity portrait with documentary treatment",
            "A career told in distinct eras.",
            (
                "The grounded source is organised into successive "
                "public-life phases."
            ),
            (
                "Origins",
                "Career",
                "Public life",
                "Institutions & legacy",
            ),
            "era-stack",
            (
                "era-navigation",
            ),
            "documentary",
            "large chapter transitions followed by supporting evidence",
            "chapter-navigation",
        ),
        "sports-career": (
            "Career Under Pressure",
            "competitive progression through career phases",
            "identity portrait with kinetic framing",
            "The defining stages of the career.",
            (
                "Career evidence is organised around progression "
                "and major competitive phases."
            ),
            (
                "Beginnings",
                "Rise",
                "Peak",
                "After the field",
            ),
            "career-track",
            (
                "career-navigation",
            ),
            "kinetic documentary",
            "fast milestone bands alternating with quieter context",
            "career-milestones",
        ),
        "place-guide": (
            "Layers of Place",
            "orientation followed by cultural and spatial context",
            "environmental hero",
            "Understand the place through layers.",
            (
                "Geographic and cultural evidence is arranged "
                "as a guided exploration."
            ),
            (
                "Orientation",
                "Character",
                "Culture",
                "Connections",
            ),
            "atlas-sequence",
            (
                "place-layers",
            ),
            "spatial editorial",
            "wide orientation followed by compact contextual layers",
            "guided-exploration",
        ),
        "organisation-profile": (
            "Institution as a System",
            "purpose, capability, evolution and relationships",
            "institutional hero treatment",
            "What the institution is built to do.",
            (
                "Grounded evidence is organised around the system "
                "the institution creates and maintains."
            ),
            (
                "Purpose",
                "Capabilities",
                "Evolution",
                "Network",
            ),
            "capability-map",
            (
                "system-navigation",
            ),
            "structured institutional",
            "system overview followed by connected capability sections",
            "capability-exploration",
        ),
        "culture-profile": (
            "Work and Influence",
            "creative development followed by cultural consequence",
            "identity portrait with portfolio treatment",
            "The work before the directory.",
            (
                "The composition prioritises creative development "
                "and cultural context."
            ),
            (
                "Origins",
                "Practice",
                "Defining work",
                "Influence",
            ),
            "portfolio-sequence",
            (
                "creative-navigation",
            ),
            "visual editorial",
            "large work moments alternating with contextual profiles",
            "work-exploration",
        ),
        "editorial": (
            "Context Before Directory",
            "general grounded editorial sequence",
            "subject-safe editorial hero",
            "Context before the directory.",
            (
                "The strongest grounded fragments are arranged "
                "before related profiles."
            ),
            (
                "Overview",
                "Context",
                "Connections",
                "Impact",
            ),
            "editorial-sequence",
            (
                "context-navigation",
            ),
            "balanced editorial",
            "broad context followed by searchable supporting material",
            "story-exploration",
        ),
    }

    (
        concept,
        narrative_shape,
        hero_treatment,
        feature_title,
        feature_intro,
        labels,
        layout_strategy,
        interactions,
        visual_mood,
        visual_rhythm,
        primary_interaction,
    ) = defaults.get(
        brief.family,
        defaults[
            "editorial"
        ],
    )

    return DesignProposal(
        accepted=True,
        generated=False,
        concept=concept,
        narrative_shape=narrative_shape,
        hero_treatment=hero_treatment,
        feature_title=feature_title,
        feature_intro=feature_intro,
        section_labels=labels,
        layout_strategy=layout_strategy,
        interaction_concepts=(
            interactions
        ),
        visual_mood=visual_mood,
        visual_rhythm=visual_rhythm,
        primary_interaction=(
            primary_interaction
        ),
        reason=reason,
    )


def propose_design(
    brief: CreativeBrief,
    progress: Progress,
    *,
    generator: Callable[[str], str] | None = None,
) -> DesignProposal:
    """Request bounded local creativity with one contract-repair attempt.

    Semantic authority remains deterministic.

    A model response that is syntactically or contract-invalid receives
    one tightly bounded correction opportunity. Provider/runtime failures
    do not trigger repeated inference and fall back immediately.
    """
    disabled = str(
        os.environ.get(
            "SOPHYANE_DISABLE_GENERATIVE_SITE_DESIGN",
            "",
        )
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if disabled:
        result = deterministic_design_proposal(
            brief,
            reason=(
                "generative site design disabled by environment"
            ),
        )

        progress(
            "SLI design intelligence: deterministic fallback "
            "(generative design disabled)"
        )

        return result

    generation = (
        generator
        or _call_local_llm
    )

    original_prompt = _brief_prompt(
        brief
    )

    allowed_layouts = sorted(
        _ALLOWED_LAYOUTS.get(
            brief.family,
            _ALLOWED_LAYOUTS[
                "editorial"
            ],
        )
    )

    allowed_interactions = sorted(
        _ALLOWED_INTERACTIONS.get(
            brief.family,
            _ALLOWED_INTERACTIONS[
                "editorial"
            ],
        )
    )

    last_error: Exception | None = None

    prompt = original_prompt

    for attempt in (
        1,
        2,
    ):
        try:
            response = generation(
                prompt
            )

        except Exception as error:
            # Provider/runtime failures are not design-contract mistakes.
            # Do not repeatedly invoke an unavailable or unhealthy model.
            last_error = error

            progress(
                "SLI design intelligence: local provider unavailable; "
                "deterministic fallback"
            )

            break

        try:
            payload = _extract_json(
                response
            )

            proposal = _proposal_from_payload(
                brief,
                payload,
            )

        except ValueError as error:
            last_error = error

            if attempt == 1:
                progress(
                    "SLI design intelligence: proposal rejected; "
                    "requesting one bounded contract repair: "
                    f"{type(error).__name__}: {error}"
                )

                prompt = (
                    original_prompt
                    + "\n\n"
                    + "CORRECTION REQUIRED.\n"
                    + "Your previous JSON proposal was rejected by "
                    + "Sophyane's deterministic validator.\n"
                    + "\n"
                    + "Validator error:\n"
                    + str(
                        error
                    )
                    + "\n\n"
                    + "Return a corrected JSON object only.\n"
                    + "Do not explain the correction.\n"
                    + "Do not add markdown.\n"
                    + "Do not alter facts or subject identity.\n"
                    + "\n"
                    + "For deterministic family "
                    + brief.family
                    + ", layout_strategy MUST resolve to one of:\n"
                    + json.dumps(
                        allowed_layouts,
                        ensure_ascii=False,
                    )
                    + "\n"
                    + "primary_interaction MUST resolve to one of:\n"
                    + json.dumps(
                        allowed_interactions,
                        ensure_ascii=False,
                    )
                    + "\n"
                    + "section_labels MUST contain exactly four "
                    + "non-empty strings.\n"
                    + "Use concise canonical tokens where possible."
                )

                continue

            progress(
                "SLI design intelligence: repaired proposal still "
                "invalid; deterministic fallback: "
                f"{type(error).__name__}: {error}"
            )

            break

        except Exception as error:
            last_error = error

            progress(
                "SLI design intelligence: proposal processing failed; "
                "deterministic fallback: "
                f"{type(error).__name__}: {error}"
            )

            break

        progress(
            "SLI design intelligence: accepted local generative "
            f"proposal '{proposal.concept}'"
            + (
                " after bounded repair"
                if attempt == 2
                else ""
            )
        )

        return proposal

    result = deterministic_design_proposal(
        brief,
        reason=(
            (
                f"{type(last_error).__name__}: "
                f"{last_error}"
            )
            if last_error
            else
            "local design proposal unavailable"
        ),
    )

    return result
