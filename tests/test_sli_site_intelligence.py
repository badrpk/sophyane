from sophyane.code_memory.sli_rich_site_compose import (
    Entity,
    _render,
)
from sophyane.code_memory.sli_site_intelligence import (
    build_site_plan,
    infer_site_intent,
)
from sophyane.code_memory.topic_site_compose import (
    TopicSource,
)


def _entity(
    title: str,
    category: str,
) -> Entity:
    return Entity(
        title=title,
        extract=(
            f"{title} provides related contextual evidence. "
            * 6
        ),
        url=(
            "https://example.invalid/"
            + title.lower().replace(
                " ",
                "-",
            )
        ),
        image=None,
        category=category,
    )


def _demis() -> TopicSource:
    return TopicSource(
        requested_topic=
            "Demis Hassabis",

        resolved_title=
            "Demis Hassabis",

        extract=(
            "Demis Hassabis is a British artificial intelligence "
            "researcher and scientist. "
            "He co-founded DeepMind and worked on machine learning. "
            "DeepMind developed AlphaGo. "
            "His research contributed to AlphaFold and protein "
            "structure prediction. "
            "He received the Nobel Prize in Chemistry in 2024. "
            "His career spans computer science, technology, "
            "research and scientific discovery."
        ),

        page_url=
            (
                "https://en.wikipedia.org/"
                "wiki/Demis_Hassabis"
            ),

        image_data_uri=
            (
                "data:image/jpeg;base64,"
                "DEMISPRIMARY"
            ),
    )


def _imran() -> TopicSource:
    return TopicSource(
        requested_topic=
            "Imran Khan Niazi",

        resolved_title=
            "Imran Khan",

        extract=(
            "Imran Khan is a Pakistani former cricketer, "
            "philanthropist and politician. "
            "He captained Pakistan in the 1992 Cricket World Cup. "
            "After cricket he founded a philanthropic hospital. "
            "He founded a political party and later served as "
            "prime minister of Pakistan from 2018 to 2022. "
            "His public career includes sport, elections, "
            "politics and government."
        ),

        page_url=
            (
                "https://en.wikipedia.org/"
                "wiki/Imran_Khan"
            ),

        image_data_uri=
            (
                "data:image/jpeg;base64,"
                "IMRANPRIMARY"
            ),
    )


def test_demis_routes_to_research_architecture() -> None:
    entities = [
        _entity(
            "DeepMind",
            "Research",
        ),
        _entity(
            "AlphaFold",
            "Science",
        ),
        _entity(
            "AlphaGo",
            "Research",
        ),
    ]

    intent = infer_site_intent(
        _demis(),
        entities,
    )

    plan = build_site_plan(
        _demis(),
        entities,
    )

    assert intent.family == "research-profile"

    assert (
        plan.visual_family
        ==
        "research-editorial"
    )

    document = _render(
        _demis(),
        entities,
    )

    assert (
        'data-layout-family="research-profile"'
        in document
    )

    assert 'id="research-arc"' in document

    assert 'id="life-chapters"' not in document


def test_imran_routes_to_public_life_architecture() -> None:
    entities = [
        _entity(
            "Pakistan cricket team",
            "Sport",
        ),
        _entity(
            "Shaukat Khanum",
            "Philanthropy",
        ),
        _entity(
            "Government of Pakistan",
            "Politics",
        ),
    ]

    intent = infer_site_intent(
        _imran(),
        entities,
    )

    plan = build_site_plan(
        _imran(),
        entities,
    )

    assert intent.family == "public-life"

    assert (
        plan.visual_family
        ==
        "documentary-biography"
    )

    document = _render(
        _imran(),
        entities,
    )

    assert (
        'data-layout-family="public-life"'
        in document
    )

    assert 'id="life-chapters"' in document

    assert 'class="phase-stack"' in document

    assert 'id="research-arc"' not in document


def test_demis_and_imran_have_different_plans() -> None:
    demis = build_site_plan(
        _demis(),
        [
            _entity(
                "DeepMind",
                "Research",
            ),
            _entity(
                "AlphaFold",
                "Science",
            ),
            _entity(
                "Nobel Prize",
                "Recognition",
            ),
        ],
    )

    imran = build_site_plan(
        _imran(),
        [
            _entity(
                "Pakistan cricket team",
                "Sport",
            ),
            _entity(
                "Prime Minister",
                "Politics",
            ),
            _entity(
                "Shaukat Khanum",
                "Philanthropy",
            ),
        ],
    )

    assert demis.family != imran.family

    assert (
        demis.visual_family
        !=
        imran.visual_family
    )

    assert (
        demis.primary_interaction
        !=
        imran.primary_interaction
    )


def test_related_person_still_cannot_replace_primary_hero() -> None:
    source = _demis()

    wrong = (
        "data:image/jpeg;base64,"
        "WRONGPERSON"
    )

    entities = [
        Entity(
            title=
                "Related Person",

            extract=
                (
                    "Related contextual profile. "
                    * 8
                ),

            url=
                "https://example.invalid/related",

            image=
                wrong,

            category=
                "Research",
        )
    ]

    document = _render(
        source,
        entities,
    )

    hero = document.split(
        '<header class="hero">',
        1,
    )[1].split(
        "</header>",
        1,
    )[0]

    assert "DEMISPRIMARY" in hero
    assert "WRONGPERSON" not in hero

    # Still valid in its own related-entity card.
    assert "WRONGPERSON" in document


def test_unknown_topic_uses_editorial_fallback() -> None:
    source = TopicSource(
        requested_topic=
            "Example Subject",

        resolved_title=
            "Example Subject",

        extract=(
            "This is a broad subject containing contextual "
            "information across several different dimensions. "
            * 8
        ),

        page_url=
            "https://example.invalid/example",
    )

    entities = [
        _entity(
            "Context One",
            "Overview",
        ),
        _entity(
            "Context Two",
            "Overview",
        ),
        _entity(
            "Context Three",
            "Overview",
        ),
    ]

    intent = infer_site_intent(
        source,
        entities,
    )

    assert intent.family == "editorial"

    document = _render(
        source,
        entities,
    )

    assert (
        'data-layout-family="editorial"'
        in document
    )

    assert 'id="subject-map"' in document
