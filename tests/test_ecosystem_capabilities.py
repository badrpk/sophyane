from pathlib import Path


def test_discovers_supported_badrpk_repositories(
    tmp_path: Path,
):
    from sophyane.ecosystem_capabilities import (
        BADRPK_REPOSITORIES,
        discover_badrpk_capabilities,
    )

    for repository in (
        "neuron",
        "nifdu",
        "veyron",
    ):
        root = (
            tmp_path
            / repository
        )

        root.mkdir()

        (
            root
            / "README.md"
        ).write_text(
            f"# {repository}\n"
            "browser verification repository intelligence"
        )

    discovered = (
        discover_badrpk_capabilities(
            roots=[tmp_path],
            remote_loader=lambda *args, **kwargs: "",
        )
    )

    by_name = {
        item.repository: item
        for item in discovered
    }

    assert set(
        BADRPK_REPOSITORIES
    ) == set(
        by_name
    )

    assert (
        by_name[
            "neuron"
        ].available
        is True
    )

    assert (
        by_name[
            "nifdu"
        ].available
        is True
    )

    assert (
        by_name[
            "veyron"
        ].available
        is True
    )

    assert (
        by_name[
            "xerus"
        ].available
        is False
    )


def test_explicit_repository_reference_has_priority(
    tmp_path: Path,
):
    from sophyane.ecosystem_capabilities import (
        discover_badrpk_capabilities,
        rank_badrpk_capabilities,
    )

    for repository in (
        "neuron",
        "nifdu",
    ):
        root = (
            tmp_path
            / repository
        )

        root.mkdir()

        (
            root
            / "README.md"
        ).write_text(
            "shared generic capability"
        )

    catalog = (
        discover_badrpk_capabilities(
            roots=[tmp_path],
            remote_loader=lambda *args, **kwargs: "",
        )
    )

    ranked = (
        rank_badrpk_capabilities(
            "Use nifdu to inspect the rendered browser artifact",
            capabilities=catalog,
            history_reader=lambda **_: [],
            limit=2,
        )
    )

    assert ranked
    assert (
        ranked[0].repository
        == "nifdu"
    )


def test_verified_history_influences_but_does_not_replace_semantics(
    tmp_path: Path,
):
    from sophyane.ecosystem_capabilities import (
        discover_badrpk_capabilities,
        rank_badrpk_capabilities,
    )

    neuron = (
        tmp_path
        / "neuron"
    )

    nifdu = (
        tmp_path
        / "nifdu"
    )

    neuron.mkdir()
    nifdu.mkdir()

    (
        neuron
        / "README.md"
    ).write_text(
        "repository semantic memory retrieval graph"
    )

    (
        nifdu
        / "README.md"
    ).write_text(
        "browser rendering visual verification"
    )

    catalog = (
        discover_badrpk_capabilities(
            roots=[tmp_path],
            remote_loader=lambda *args, **kwargs: "",
        )
    )

    def history_reader(
        *,
        repository_identity,
        limit,
    ):
        if (
            "neuron"
            in repository_identity
        ):
            return [
                {
                    "accepted": True,
                    "verification_state": "verified",
                    "reward": 1.0,
                    "trace_id": "n1",
                },
                {
                    "accepted": True,
                    "verification_state": "verified",
                    "reward": 1.0,
                    "trace_id": "n2",
                },
            ]

        return []

    ranked = (
        rank_badrpk_capabilities(
            (
                "Inspect browser rendering and visual "
                "verification using nifdu"
            ),
            capabilities=catalog,
            history_reader=history_reader,
            limit=2,
        )
    )

    assert (
        ranked[0].repository
        == "nifdu"
    )

    neuron_item = next(
        item
        for item in ranked
        if (
            item.repository
            == "neuron"
        )
    )

    assert (
        neuron_item.experience_score
        > 0.0
    )
