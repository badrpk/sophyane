from unittest.mock import patch

from sophyane.code_memory.sli_rich_site_compose import (
    Entity,
    _render,
)
from sophyane.code_memory.topic_site_compose import (
    TopicSource,
    retrieve_topic,
)


def _page_payload() -> dict:
    return {
        "query": {
            "pages": [
                {
                    "title":
                        "Demis Hassabis",

                    "extract":
                        (
                            "Demis Hassabis is a British "
                            "artificial intelligence researcher. "
                            * 20
                        ),

                    "fullurl":
                        (
                            "https://en.wikipedia.org/"
                            "wiki/Demis_Hassabis"
                        ),

                    "original": {
                        "source":
                            (
                                "https://example.invalid/"
                                "demis-primary.jpg"
                            )
                    },
                }
            ]
        }
    }


def test_commons_result_cannot_become_primary_subject_image() -> None:
    primary = (
        "https://example.invalid/"
        "demis-primary.jpg"
    )

    unrelated = (
        "https://example.invalid/"
        "unrelated-person.jpg"
    )

    def fake_api(
        base,
        parameters,
        timeout=25,
    ):
        del base, timeout

        if (
            parameters.get("prop")
            ==
            "extracts|pageimages|info"
        ):
            return _page_payload()

        raise AssertionError(
            parameters
        )

    def fake_download(
        url,
    ):
        if url == primary:
            return None

        if url == unrelated:
            return (
                "data:image/jpeg;base64,"
                "UNRELATED"
            )

        raise AssertionError(
            url
        )

    with (
        patch(
            "sophyane.code_memory."
            "topic_site_compose._search_title",
            return_value="Demis Hassabis",
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._api_json",
            side_effect=fake_api,
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._commons_images",
            return_value=[
                (
                    "Unrelated person",
                    unrelated,
                )
            ],
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._download_data_uri",
            side_effect=fake_download,
        ),
    ):
        source = retrieve_topic(
            "Demis Hassabis"
        )

    # Supplementary search imagery may exist.
    assert len(source.images) == 1

    assert (
        source.images[0][0]
        ==
        "Unrelated person"
    )

    # But it must never acquire primary-subject semantics.
    assert (
        source.image_data_uri
        is None
    )

    assert (
        source.image_url
        ==
        primary
    )


def test_verified_primary_page_image_remains_primary_subject_image() -> None:
    primary = (
        "https://example.invalid/"
        "demis-primary.jpg"
    )

    primary_data = (
        "data:image/jpeg;base64,"
        "VERIFIEDPRIMARY"
    )

    with (
        patch(
            "sophyane.code_memory."
            "topic_site_compose._search_title",
            return_value="Demis Hassabis",
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._api_json",
            return_value=_page_payload(),
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._commons_images",
            return_value=[],
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._download_data_uri",
            return_value=primary_data,
        ),
    ):
        source = retrieve_topic(
            "Demis Hassabis"
        )

    assert (
        source.image_data_uri
        ==
        primary_data
    )

    assert source.images == [
        (
            "Demis Hassabis",
            primary,
            primary_data,
        )
    ]


def test_rich_site_without_primary_image_uses_fallback_not_entity_photo() -> None:
    source = TopicSource(
        requested_topic=
            "Demis Hassabis",

        resolved_title=
            "Demis Hassabis",

        extract=(
            "Demis Hassabis is a British "
            "artificial intelligence researcher. "
            * 20
        ),

        page_url=
            (
                "https://en.wikipedia.org/"
                "wiki/Demis_Hassabis"
            ),

        image_url=
            (
                "https://example.invalid/"
                "demis-primary.jpg"
            ),

        image_data_uri=None,
    )

    wrong_person = (
        "data:image/jpeg;base64,"
        "WRONGPERSON"
    )

    entities = [
        Entity(
            title=
                "Related person",

            extract=
                (
                    "Related profile text. "
                    * 20
                ),

            url=
                "https://example.invalid/"
                "related",

            image=
                wrong_person,

            category=
                "People",
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

    assert (
        wrong_person
        not in hero
    )

    assert (
        "data:image/svg+xml"
        in hero
    )

    # The entity image is still allowed in its own card.
    assert (
        wrong_person
        in document
    )


def test_rich_site_primary_image_is_used_when_identity_bound() -> None:
    primary = (
        "data:image/jpeg;base64,"
        "DEMISPRIMARY"
    )

    source = TopicSource(
        requested_topic=
            "Demis Hassabis",

        resolved_title=
            "Demis Hassabis",

        extract=(
            "Demis Hassabis is a British "
            "artificial intelligence researcher. "
            * 20
        ),

        page_url=
            (
                "https://en.wikipedia.org/"
                "wiki/Demis_Hassabis"
            ),

        image_data_uri=
            primary,
    )

    document = _render(
        source,
        [],
    )

    hero = document.split(
        '<header class="hero">',
        1,
    )[1].split(
        "</header>",
        1,
    )[0]

    assert primary in hero


def test_identity_bound_thumbnail_is_preferred_over_oversized_original() -> None:
    thumbnail = (
        "https://example.invalid/"
        "demis-thumbnail.jpg"
    )

    original = (
        "https://example.invalid/"
        "demis-original.jpg"
    )

    thumbnail_data = (
        "data:image/jpeg;base64,"
        "DEMISTHUMBNAIL"
    )

    payload = {
        "query": {
            "pages": [
                {
                    "title":
                        "Demis Hassabis",

                    "extract":
                        (
                            "Demis Hassabis is a British "
                            "artificial intelligence researcher. "
                            * 20
                        ),

                    "fullurl":
                        (
                            "https://en.wikipedia.org/"
                            "wiki/Demis_Hassabis"
                        ),

                    "thumbnail": {
                        "source":
                            thumbnail,
                    },

                    "original": {
                        "source":
                            original,
                    },
                }
            ]
        }
    }

    seen = []

    def fake_download(
        url,
    ):
        seen.append(
            url
        )

        if url == thumbnail:
            return thumbnail_data

        raise AssertionError(
            "Oversized original should not "
            f"be selected first: {url}"
        )

    with (
        patch(
            "sophyane.code_memory."
            "topic_site_compose._search_title",
            return_value="Demis Hassabis",
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._api_json",
            return_value=payload,
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._commons_images",
            return_value=[],
        ),
        patch(
            "sophyane.code_memory."
            "topic_site_compose._download_data_uri",
            side_effect=fake_download,
        ),
    ):
        source = retrieve_topic(
            "Demis Hassabis"
        )

    assert source.image_url == thumbnail

    assert (
        source.image_data_uri
        ==
        thumbnail_data
    )

    assert seen == [
        thumbnail
    ]
