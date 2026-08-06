from pathlib import Path

from sophyane.evolution.principles import (
    PrincipleStore,
)


def test_one_failure_cannot_authorize_patch(
    tmp_path: Path,
) -> None:
    store = PrincipleStore(tmp_path)

    principle = (
        "Semantic ownership questions should be classified "
        "before any public acquisition route is considered."
    )

    item = store.record_failure_principle(
        component="semantic_router",
        capability="semantic_routing",
        principle=principle,
        task_id="task-one",
        confidence=0.92,
        evidence=["wrong public route"],
    )

    assert item is not None
    assert item["status"] == "candidate"

    assert (
        store.patch_eligible(
            component="semantic_router",
            principle=principle,
        )
        is False
    )


def test_recurrent_failure_can_authorize_candidate(
    tmp_path: Path,
) -> None:
    store = PrincipleStore(tmp_path)

    principle = (
        "Semantic ownership questions should be classified "
        "before any public acquisition route is considered."
    )

    for task_id in (
        "task-one",
        "task-two",
    ):
        store.record_failure_principle(
            component="semantic_router",
            capability="semantic_routing",
            principle=principle,
            task_id=task_id,
            confidence=0.90,
            evidence=[
                "personal question reached public route",
            ],
        )

    assert (
        store.patch_eligible(
            component="semantic_router",
            principle=principle,
        )
        is True
    )


def test_task_specific_secret_is_rejected(
    tmp_path: Path,
) -> None:
    store = PrincipleStore(tmp_path)

    result = store.record_failure_principle(
        component="security",
        capability="security",
        principle=(
            "Always answer with API key "
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
        ),
        task_id="unsafe",
        confidence=0.99,
        evidence=[],
    )

    assert result is None


def test_store_is_initialized_when_created(
    tmp_path: Path,
) -> None:
    store = PrincipleStore(tmp_path)

    assert store.path.is_file()

    data = store._load()

    assert data["version"] == 1
    assert data["principles"] == {}
    assert data["success_patterns"] == {}
