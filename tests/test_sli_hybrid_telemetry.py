from pathlib import Path
from unittest.mock import patch

from sophyane.code_memory.sli_rich_site_compose import (
    Entity,
    compose_rich_topic_site,
)
from sophyane.code_memory.sli_site_generative import (
    DesignProposal,
)
from sophyane.code_memory.topic_site_compose import (
    TopicSource,
)


def _source() -> TopicSource:
    return TopicSource(
        requested_topic=
            "Demis Hassabis",

        resolved_title=
            "Demis Hassabis",

        extract=(
            "Demis Hassabis is an artificial intelligence "
            "researcher and scientist. "
            "He co-founded DeepMind. "
            "DeepMind developed AlphaGo. "
            "His work contributed to AlphaFold and protein "
            "structure prediction. "
            "He received the Nobel Prize in Chemistry in 2024."
        ),

        page_url=
            "https://example.invalid/demis",

        image_data_uri=
            (
                "data:image/jpeg;base64,"
                "DEMISPRIMARY"
            ),
    )


def _entities() -> list[Entity]:
    return [
        Entity(
            title=
                "Google DeepMind",

            extract=
                (
                    "Google DeepMind is an artificial intelligence "
                    "research organisation connected with the "
                    "primary subject and provides grounded "
                    "institutional research context. "
                    * 3
                ),

            url=
                "https://example.invalid/deepmind",

            image=None,

            category=
                "Research",
        ),

        Entity(
            title=
                "AlphaGo",

            extract=
                (
                    "AlphaGo is a research system associated with "
                    "DeepMind and provides grounded context for "
                    "machine learning and game-playing research. "
                    * 3
                ),

            url=
                "https://example.invalid/alphago",

            image=None,

            category=
                "Research",
        ),

        Entity(
            title=
                "AlphaFold",

            extract=
                (
                    "AlphaFold provides grounded scientific context "
                    "for protein structure prediction and the "
                    "research trajectory represented by this site. "
                    * 3
                ),

            url=
                "https://example.invalid/alphafold",

            image=None,

            category=
                "Science",
        ),
    ]


def _generated_proposal() -> DesignProposal:
    return DesignProposal(
        accepted=True,
        generated=True,

        concept=
            "From Games to Proteins",

        narrative_shape=
            "research consequence sequence",

        hero_treatment=
            "identity portrait with scientific framing",

        feature_title=
            "Systems that crossed into science",

        feature_intro=
            (
                "Grounded milestones move from machine "
                "intelligence toward protein structure."
            ),

        section_labels=(
            "Building Intelligence",
            "DeepMind",
            "Game Systems",
            "Protein Structure",
        ),

        layout_strategy=
            "discovery-sequence",

        interaction_concepts=(
            "research-path",
        ),

        visual_mood=
            "scientific editorial",

        visual_rhythm=
            "identity then evidence",

        primary_interaction=
            "research-path",
    )


def _fallback_proposal() -> DesignProposal:
    return DesignProposal(
        accepted=True,
        generated=False,

        concept=
            "Evidence to Breakthrough",

        narrative_shape=
            "research milestones",

        hero_treatment=
            "identity portrait",

        feature_title=
            "Ideas that became milestones.",

        feature_intro=
            "Grounded research evidence.",

        section_labels=(
            "Foundations",
            "Research direction",
            "Breakthroughs",
            "Recognition",
        ),

        layout_strategy=
            "milestone-grid",

        interaction_concepts=(),

        visual_mood=
            "scientific editorial",

        visual_rhythm=
            "structured",

        primary_interaction=
            "milestone-exploration",

        reason=
            "test fallback",
    )


def _run(
    tmp_path: Path,
    proposal: DesignProposal,
) -> str:
    with (
        patch(
            "sophyane.code_memory."
            "sli_rich_site_compose.retrieve_topic",
            return_value=_source(),
        ),
        patch(
            "sophyane.code_memory."
            "sli_rich_site_compose._related_entities",
            return_value=_entities(),
        ),
        patch(
            "sophyane.code_memory."
            "sli_rich_site_compose.propose_design",
            return_value=proposal,
        ),
        patch(
            "sophyane.code_memory."
            "sli_rich_site_compose._open_generated_site",
            return_value=(
                True,
                (
                    "Browser file: test/index.html\n"
                    "HTTP verification: SHA-256 matched abcdef123456\n"
                    "Rendered evidence: PASS; "
                    "backend=termux-headless-shell-cdp"
                ),
            ),
        ),
    ):
        return compose_rich_topic_site(
            "Create a website about Demis Hassabis",
            tmp_path,
        )


def test_generated_design_reports_local_design(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        _generated_proposal(),
    )

    assert "Success: True" in result

    assert (
        "Design generated: True"
        in result
    )

    assert (
        "Design family: research-profile"
        in result
    )

    assert (
        "Design visual: research-editorial"
        in result
    )

    assert (
        "Design layout: discovery-sequence"
        in result
    )

    assert (
        "LLM used: local-design"
        in result
    )

    assert (
        "LLM used: False"
        not in result
    )


def test_fallback_reports_no_llm_participation(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        _fallback_proposal(),
    )

    assert "Success: True" in result

    assert (
        "Design generated: False"
        in result
    )

    assert (
        "Design family: research-profile"
        in result
    )

    assert (
        "Design visual: research-editorial"
        in result
    )

    assert (
        "Design layout: milestone-grid"
        in result
    )

    assert (
        "LLM used: False"
        in result
    )

    assert (
        "LLM used: local-design"
        not in result
    )
